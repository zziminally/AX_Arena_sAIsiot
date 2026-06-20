"""
Hybrid Retriever: metadata scoring (40%) + semantic similarity (60%).

Flow:
  1. Request Analyzer (LLM) → structured query
  2. Semantic search in ChromaDB → top-K candidates
  3. Hybrid re-ranking → top-FINAL_TOP_K distinct documents
"""
import json
import re
from typing import List, Dict, Any, Optional

import anthropic

from src.config import (
    ANTHROPIC_API_KEY, LLM_MODEL,
    TOP_K, FINAL_TOP_K, ALPHA,
)
from src.vector_store import search

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Industry similarity map ───────────────────────────────────────────────────

INDUSTRY_ALIASES: Dict[str, List[str]] = {
    "자동차":    ["모빌리티", "자동차 제조", "전기차", "자동차 제조 기업", "자동차 제조업",
                "해외 자동차 제조 기업", "국내 자동차 제조 기업"],
    "가전":      ["전자", "생활가전", "프리미엄 가전", "프리미엄 가전 브랜드"],
    "식음료":    ["F&B", "식품", "음료", "외식", "프랜차이즈", "레스토랑",
                "신규 F&B 브랜드", "이탈리안 레스토랑 브랜드", "대형 치킨 프랜차이즈",
                "외식 브랜드", "분식 프랜차이즈"],
    "부동산":    ["분양", "시행사", "체험관", "시행사 또는 분양 마케팅사"],
    "확장 레퍼런스": [],  # always eligible as fallback
}

PROJECT_TYPE_KEYWORDS: Dict[str, set] = {
    "브랜드/캠페인 전략":       {"전략", "캠페인", "브랜드 전략", "런칭", "통합"},
    "프로젝트/공간 기획":       {"팝업", "공간", "쇼룸", "체험존", "공간 기획", "동선"},
    "XR/디지털 콘텐츠 설계":    {"XR", "AR", "콘텐츠", "디지털", "메타버스", "XR 콘텐츠"},
    "고객 여정/CRM 설계":       {"여정", "전환", "CRM", "리드", "재방문", "고객 여정"},
    "콘텐츠 연출/스토리텔링":    {"스토리보드", "연출", "세계관", "내러티브", "스토리"},
    "운영/KPI 관리":            {"운영", "KPI", "성과", "관리", "리포트"},
}


# ── Request Analyzer ──────────────────────────────────────────────────────────

_ANALYZER_SYSTEM = """당신은 올림플래닛의 시니어 제안 매니저입니다.
사용자의 신규 제안 요청을 분석하여 아래 JSON 형식으로 정확히 구조화하십시오.

[참조 가능한 산업군]: 자동차, 가전, 식음료, 패션, 금융, 부동산, 기타
[참조 가능한 프로젝트 유형]: 브랜드/캠페인 전략, 프로젝트/공간 기획, XR/디지털 콘텐츠 설계,
                            고객 여정/CRM 설계, 콘텐츠 연출/스토리텔링, 운영/KPI 관리
[참조 가능한 톤앤매너 패턴]: 프리미엄·전략적·설득형, 기술지향·정교한·설계형,
                            감성적·라이프스타일형·기획형, 운영중심·체계적·관리형

반드시 JSON만 출력하십시오. 설명 텍스트 없이."""

_ANALYZER_USER = """[신규 제안 요청]
{user_input}

[출력 형식]
{{
  "industry": "산업군",
  "client_type": "고객사 유형 설명",
  "project_type": "프로젝트 유형 (위 목록 중 가장 가까운 것, 복수 가능 — 쉼표 구분)",
  "proposal_purpose": "제안 목적 한 문장",
  "proposal_stage": "제안 단계 추정",
  "key_needs_keywords": ["핵심 니즈 키워드 3~7개"],
  "emphasized_values": ["강조 가치 2~4개"],
  "tone_and_manner": "톤앤매너 (위 패턴 중 가장 가까운 것)",
  "query_text": "벡터 검색용 핵심 요약 (2~3문장, 산업군+캠페인 목적+체험 방식 포함)"
}}"""


def analyze_request(user_input: str) -> Dict[str, Any]:
    """LLM call 1: free-text input → structured query dict."""
    msg = _client.messages.create(
        model=LLM_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": _ANALYZER_USER.format(user_input=user_input),
        }],
        system=_ANALYZER_SYSTEM,
    )
    raw = msg.content[0].text.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    return json.loads(raw)


# ── Hybrid Scoring ────────────────────────────────────────────────────────────

def _metadata_score(doc_meta: Dict, query: Dict) -> float:
    """
    Weighted metadata match score [0, 1].
    - industry (0.5):  exact=0.5, alias=0.25, 확장레퍼런스=0.1
    - project_type (0.3): keyword overlap ratio
    - key_needs_keywords (0.2): query∩doc overlap ratio
    """
    score = 0.0
    q_industry = query.get("industry", "")

    # Industry
    doc_industry = doc_meta.get("industry", "")
    if doc_industry == q_industry:
        score += 0.5
    elif doc_industry == "확장 레퍼런스":
        score += 0.1
    else:
        aliases = INDUSTRY_ALIASES.get(q_industry, [])
        if doc_industry in aliases:
            score += 0.25

    # Project type
    q_type_str = query.get("project_type", "")
    q_kw: set = set()
    for t in q_type_str.split(","):
        q_kw |= PROJECT_TYPE_KEYWORDS.get(t.strip(), set())
    d_kw = PROJECT_TYPE_KEYWORDS.get(doc_meta.get("project_type", ""), set())
    if q_kw:
        score += 0.3 * len(q_kw & d_kw) / len(q_kw)

    # Key needs keywords
    q_needs = set(query.get("key_needs_keywords", []))
    d_needs = set(doc_meta.get("key_needs_keywords", "").split("|"))
    if q_needs:
        score += 0.2 * len(q_needs & d_needs) / len(q_needs)

    return min(score, 1.0)


def _hybrid_score(semantic: float, metadata: float) -> float:
    return ALPHA * metadata + (1 - ALPHA) * semantic


# ── Main retrieval ────────────────────────────────────────────────────────────

def retrieve(user_input: str) -> Dict[str, Any]:
    """
    Full retrieval pipeline.
    Returns:
        {
          "query": structured query dict,
          "results": [
            {
              "doc_id": ...,
              "score": hybrid_score,
              "semantic_score": ...,
              "metadata_score": ...,
              "best_section": section_name,
              "sections": [{ "section_name", "text", "semantic_score" }, ...]
            },
            ...
          ]
        }
    """
    # Step 1: Analyze request
    query = analyze_request(user_input)

    # Step 2: Semantic search (exclude company profile from main retrieval)
    raw_hits = search(query["query_text"], n_results=TOP_K * 3)

    # Step 3: Aggregate by doc_id (max pooling per document)
    doc_map: Dict[str, Dict] = {}
    for hit in raw_hits:
        m = hit["metadata"]
        doc_id = m["doc_id"]
        if doc_id == "COMPANY_PROFILE":
            continue
        if doc_id not in doc_map:
            doc_map[doc_id] = {
                "doc_id":         doc_id,
                "metadata":       m,
                "semantic_score": hit["semantic_score"],
                "sections":       [],
            }
        else:
            # Keep highest semantic score
            if hit["semantic_score"] > doc_map[doc_id]["semantic_score"]:
                doc_map[doc_id]["semantic_score"] = hit["semantic_score"]
                doc_map[doc_id]["metadata"] = m
        doc_map[doc_id]["sections"].append({
            "section_name":  m["section_name"],
            "text":          hit["text"],
            "semantic_score": hit["semantic_score"],
        })

    # Step 4: Hybrid scoring & re-rank
    scored: List[Dict] = []
    for doc_id, doc in doc_map.items():
        ms = _metadata_score(doc["metadata"], query)
        hs = _hybrid_score(doc["semantic_score"], ms)
        scored.append({
            "doc_id":          doc_id,
            "score":           round(hs, 4),
            "semantic_score":  round(doc["semantic_score"], 4),
            "metadata_score":  round(ms, 4),
            "best_section":    max(doc["sections"], key=lambda s: s["semantic_score"])["section_name"],
            "metadata":        doc["metadata"],
            "sections":        sorted(doc["sections"], key=lambda s: -s["semantic_score"]),
        })

    scored.sort(key=lambda x: -x["score"])

    # Step 5: Top-K with diversity (same project_type capped at 2)
    final: List[Dict] = []
    type_count: Dict[str, int] = {}
    for doc in scored:
        pt = doc["metadata"].get("project_type", "")
        if type_count.get(pt, 0) >= 2:
            continue
        type_count[pt] = type_count.get(pt, 0) + 1
        final.append(doc)
        if len(final) >= FINAL_TOP_K:
            break

    return {"query": query, "results": final}
