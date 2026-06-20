"""
Draft Generator: one Claude call → structured JSON for all sections.
"""
import json
import re
from typing import Dict, Any

import anthropic

from src.config import ANTHROPIC_API_KEY, LLM_MODEL, MAX_HEADLINE_LEN, MAX_BULLET_LEN, MAX_BULLETS

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Default output section order (matches actual PPTX structure)
DEFAULT_SECTIONS = [
    "제안 배경 또는 문제 정의",
    "사업 이해 또는 고객/시장 이해",
    "제안 목적",
    "추진 전략 또는 제안 프레임",
    "세부 실행 방안",
    "운영 및 관리 체계",
    "성과 측정 또는 검증 기준",
    "기대효과 또는 결론",
]

_SYSTEM = """당신은 올림플래닛(Olimplanet)의 수석 제안서 작성 전문가입니다.
올림플래닛은 XR·이머시브 체험 마케팅을 전문으로 하는 애드테크 기업입니다.

아래 [신규 요청]과 [레퍼런스]를 바탕으로 제안서 초안을 작성하십시오.

규칙:
- 레퍼런스의 구조·논리·톤앤매너를 참조하되, 신규 요청의 맥락에 맞게 재구성
- 고객사명·제품명은 "[고객사]", "[제품명]"으로 표시
- headline은 {max_headline}자 이내의 임팩트 있는 한 문장
- bullets는 각 {max_bullet}자 이내, {max_bullets}개 이내
- 한국어로 작성, 전문적이고 설득력 있는 톤
- 반드시 JSON만 출력 (설명 텍스트 없이)"""

_USER = """[신규 제안 요청]
- 산업군: {industry}
- 고객사 유형: {client_type}
- 프로젝트 유형: {project_type}
- 제안 목적: {proposal_purpose}
- 강조 가치: {emphasized_values}
- 톤앤매너: {tone_and_manner}
- 핵심 키워드: {key_needs_keywords}

[참조 레퍼런스 (Top {n_refs}개)]
{references_text}

[출력 형식 - JSON only]
{{
  "cover": {{
    "title": "제안서 제목 (50자 이내)",
    "subtitle": "핵심 가치를 담은 부제 (한 문장)"
  }},
  "sections": [
    {{
      "section_name": "섹션명 (아래 목록 중 하나)",
      "headline": "슬라이드 핵심 헤드라인",
      "subtitle": "헤드라인을 보완하는 서브타이틀",
      "bullets": ["핵심 내용 1", "핵심 내용 2", "핵심 내용 3"],
      "notes": "발표자 참고 노트 (1~2문장)"
    }}
  ]
}}

[생성할 섹션 목록 - 반드시 이 순서로, 모두 포함]
{section_list}"""


def _build_references_text(results: list, max_chars_per_section: int = 400) -> str:
    """Format top-3 retrieved docs into a compact reference block."""
    parts = []
    for i, r in enumerate(results, 1):
        m = r["metadata"]
        lines = [
            f"--- 레퍼런스 {i}: {r['doc_id']} ---",
            f"산업군: {m['industry']} | 유형: {m['project_type']} | 톤: {m['tone_and_manner']}",
            f"강조 가치: {m['emphasized_values']}",
        ]
        # Include top 2 sections by semantic score
        for sec in r["sections"][:2]:
            text_preview = sec["text"][:max_chars_per_section].replace("\n", " ")
            lines.append(f"[{sec['section_name']}] {text_preview}...")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def generate_draft(retrieve_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Single Claude call → full proposal draft as structured dict.

    Returns:
    {
        "cover": {"title": str, "subtitle": str},
        "sections": [{"section_name", "headline", "subtitle", "bullets", "notes"}, ...],
        "query": <original query dict>,
        "references": <top-3 doc ids and scores>
    }
    """
    query = retrieve_result["query"]
    results = retrieve_result["results"]

    references_text = _build_references_text(results)
    section_list = "\n".join(f"{i+1}. {s}" for i, s in enumerate(DEFAULT_SECTIONS))

    system_prompt = _SYSTEM.format(
        max_headline=MAX_HEADLINE_LEN,
        max_bullet=MAX_BULLET_LEN,
        max_bullets=MAX_BULLETS,
    )
    user_prompt = _USER.format(
        industry=query.get("industry", ""),
        client_type=query.get("client_type", ""),
        project_type=query.get("project_type", ""),
        proposal_purpose=query.get("proposal_purpose", ""),
        emphasized_values=", ".join(query.get("emphasized_values", [])),
        tone_and_manner=query.get("tone_and_manner", ""),
        key_needs_keywords=", ".join(query.get("key_needs_keywords", [])),
        references_text=references_text,
        n_refs=len(results),
        section_list=section_list,
    )

    msg = _client.messages.create(
        model=LLM_MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    draft = json.loads(raw)

    # Attach metadata for assembler and logging
    draft["query"] = query
    draft["references"] = [
        {"doc_id": r["doc_id"], "score": r["score"], "industry": r["metadata"]["industry"]}
        for r in results
    ]
    return draft
