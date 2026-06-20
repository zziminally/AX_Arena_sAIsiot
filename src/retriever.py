"""
Hybrid Retriever: metadata scoring (40%) + semantic similarity (60%).

Flow:
  1. Request Analyzer (LLM) → structured query
  2. Semantic search in ChromaDB → top-K candidates
  3. Hybrid re-ranking → top-FINAL_TOP_K distinct documents
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

import anthropic

from src.config import (
    ANTHROPIC_API_KEY, LLM_MODEL, ANALYZER_MODEL,
    TOP_K, FINAL_TOP_K, ALPHA,
)
from src.validator import validate_query
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
  "query_text": "벡터 검색용 핵심 요약 (2~3문장, 산업군+캠페인 목적+체험 방식 포함)",
  "client_name": "고객사 짧은 식별자 (2~5자, 예: 현대자동차→현대, 삼성전자→삼성. 입력에서 특정 회사명을 알 수 없으면 산업군 기반으로 표현 예: 식음료 대기업)",
  "product_name": "제품·브랜드명 (2~5자, 알 수 없으면 '신제품' 또는 '신규 브랜드')"
}}"""


def analyze_request(user_input: str, max_retries: int = 2) -> Dict[str, Any]:
    """LLM call 1: free-text input → structured query dict. Retries on parse/validation failure."""
    last_err: Exception = RuntimeError("analyze_request: no attempts made")
    for attempt in range(1, max_retries + 2):
        try:
            msg = _client.messages.create(
                model=ANALYZER_MODEL,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": _ANALYZER_USER.format(user_input=user_input),
                }],
                system=_ANALYZER_SYSTEM,
            )
            raw = msg.content[0].text.strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
            query = json.loads(raw)
            validate_query(query)
            return query
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            if attempt <= max_retries:
                continue
    raise RuntimeError(f"analyze_request failed after {max_retries + 1} attempts: {last_err}") from last_err


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
    ⑤ analyzer(Haiku)와 초기 벡터 검색을 ThreadPoolExecutor로 병렬 실행.
       - 초기 검색: user_input 원문으로 임베딩 → 빠르게 후보 확보
       - analyzer 완료 후: query_text로 정밀 검색 (refined)
       두 결과를 합산해 중복 제거 후 hybrid scoring에 사용.
    """
    # Step 1+2: analyzer와 초기 검색 병렬 실행
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_query = pool.submit(analyze_request, user_input)
        future_hits  = pool.submit(search, user_input, TOP_K * 3)
        query    = future_query.result()
        initial_hits = future_hits.result()

    # Step 2b: analyzer의 query_text로 정밀 검색 (user_input과 다를 때만)
    if query["query_text"].strip() != user_input.strip():
        refined_hits = search(query["query_text"], n_results=TOP_K * 3)
    else:
        refined_hits = []

    # 두 결과 합산 (chunk_id 기준 중복 제거, refined 우선)
    seen: set = set()
    raw_hits: list = []
    for hit in refined_hits + initial_hits:
        chunk_id = hit["metadata"].get("doc_id", "") + hit["metadata"].get("section_name", "")
        if chunk_id not in seen:
            seen.add(chunk_id)
            raw_hits.append(hit)

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


def explain_recommendation(query: Dict[str, Any], result: Dict[str, Any]) -> str:
    """Return a detailed markdown explanation for why this document was recommended."""
    m = result["metadata"]
    q_industry = query.get("industry", "")
    doc_industry = m.get("industry", "")
    score = result["score"]
    sem = result["semantic_score"]
    meta_s = result["metadata_score"]

    grade = "최상위 매칭" if score >= 0.75 else "높은 적합도" if score >= 0.60 else "중간 적합도" if score >= 0.45 else "참고 가능"

    lines: List[str] = []

    # Score overview
    lines.append(
        f"**종합 유사도 {score:.3f}** ({grade}) &nbsp;|&nbsp; "
        f"내용 유사도 {sem:.3f} &nbsp;|&nbsp; 메타데이터 적합도 {meta_s:.3f}"
    )
    lines.append("")

    # Industry match — most impactful signal (weight 0.5)
    if doc_industry == q_industry:
        lines.append(
            f"**산업군 완전 일치 ({doc_industry})** — "
            f"메타데이터 점수의 50%를 차지하는 최우선 신호로, 요청하신 '{q_industry}' 산업의 "
            f"실제 올림플래닛 납품 제안서입니다. 동일 산업의 고객 특성·경쟁 환경·구매 의사결정 구조가 "
            f"그대로 반영되어 있어 전략 프레임을 직접 재사용할 수 있습니다."
        )
    elif doc_industry == "확장 레퍼런스":
        lines.append(
            "**XR 전문 확장 레퍼런스** — "
            "산업군은 다르지만 올림플래닛의 핵심 XR·이머시브 체험 설계 방법론이 집약된 문서입니다. "
            "공간 기획, 인터랙션 플로우, 콘텐츠 연출 측면에서 산업 무관하게 직접 활용 가능한 "
            "베스트 프랙티스가 포함되어 있습니다."
        )
    else:
        lines.append(
            f"**유사 산업군 참조 ({doc_industry})** — "
            f"요청 산업({q_industry})과 인접한 분야의 제안서입니다. 소비자 접점 전략·체험 마케팅 "
            f"실행 구조가 유사하여 전략 골격과 섹션 구성을 참고할 수 있으나, "
            f"산업 특수성(규제·채널·고객군)은 신규 제안서에서 별도 반영이 필요합니다."
        )

    # Project type keyword overlap
    q_kw: set = set()
    for t in query.get("project_type", "").split(","):
        q_kw |= PROJECT_TYPE_KEYWORDS.get(t.strip(), set())
    d_kw = PROJECT_TYPE_KEYWORDS.get(m.get("project_type", ""), set())
    common = sorted(q_kw & d_kw)
    if common:
        lines.append(
            f"**전략 키워드 {len(common)}개 일치** ({', '.join(common[:5])}) — "
            f"요청하신 프로젝트 유형({query.get('project_type', '').strip()})과 "
            f"이 문서의 접근 방식({m.get('project_type', '')})이 실행 레벨에서 직접 겹칩니다. "
            f"키워드 일치 수({len(common)})가 많을수록 세부 실행 방안을 더 많이 재활용할 수 있습니다."
        )
    else:
        lines.append(
            f"**프로젝트 유형** ({m.get('project_type', '')}) — "
            f"요청과 실행 방식은 다르지만, 제안서의 논리 전개 방식과 "
            f"섹션 구조를 구성 참고용으로 활용할 수 있습니다."
        )

    # Proposal purpose
    purpose = m.get("proposal_purpose", "")
    if purpose:
        lines.append(f"**이 제안서의 목적** — {purpose}")

    # Top relevant sections with scores
    top_secs = sorted(result.get("sections", []), key=lambda s: -s["semantic_score"])[:3]
    if top_secs:
        sec_parts = " / ".join(
            f"'{s['section_name']}'({s['semantic_score']:.3f})" for s in top_secs
        )
        lines.append(
            f"**내용 유사도 상위 섹션** — {sec_parts}. "
            f"유사도 수치가 높을수록 해당 섹션의 논리 구조·표현 방식을 신규 제안서에 직접 반영합니다."
        )

    return "\n\n".join(lines)
