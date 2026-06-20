"""
Draft Generator: one Claude call → structured JSON for all sections.
"""
import json
import re
from typing import Dict, Any

import anthropic

from src.config import ANTHROPIC_API_KEY, LLM_MODEL, MAX_HEADLINE_LEN, MAX_BULLET_LEN, MAX_BULLETS

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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

== 필수 규칙 ==
1. 레퍼런스의 논리 구조·전략 프레임·톤앤매너를 충실히 참조하되, 신규 요청의 산업/고객/목적에 맞게 완전히 재구성
2. 고객사명·제품명은 "[고객사]", "[제품명]"으로 표시
3. headline: {max_headline}자 이내, 임팩트 있는 핵심 한 문장 (반드시 포함)
4. subtitle: 헤드라인을 보완하는 전략적 서술 1문장. 40자 초과 시 자연스러운 의미 단위에서 \\n 으로 줄 구분 (반드시 포함)
5. bullets: 구체적인 실행/전략 내용 {max_bullets}개, 각 {max_bullet}자 이내 (반드시 포함, 절대 생략 금지)
6. notes: 발표 시 강조할 맥락 1~2문장 (반드시 포함)
7. 한국어로 작성, 전문적이고 설득력 있는 톤
8. JSON만 출력 — 마크다운 코드 블록, 설명 텍스트 일절 금지"""

_USER = """[신규 제안 요청]
- 산업군: {industry}
- 고객사 유형: {client_type}
- 프로젝트 유형: {project_type}
- 제안 목적: {proposal_purpose}
- 강조 가치: {emphasized_values}
- 톤앤매너: {tone_and_manner}
- 핵심 키워드: {key_needs_keywords}

[참조 레퍼런스 (Top {n_refs}개) — 구조·논리·표현을 최대한 반영]
{references_text}

[출력 형식 — JSON only, 모든 필드 필수]
{{
  "cover": {{
    "title": "제안서 제목 (50자 이내, 고객·산업·핵심 가치 포함)",
    "subtitle": "핵심 가치를 담은 부제 (한 문장, 50자 초과 시 \\n 으로 분리)"
  }},
  "sections": [
    {{
      "section_name": "섹션명",
      "headline": "슬라이드 핵심 헤드라인 ({max_headline}자 이내)",
      "subtitle": "헤드라인 보완 서브타이틀 (40자 초과 시 \\n 분리)",
      "bullets": [
        "구체적 내용 1 ({max_bullet}자 이내)",
        "구체적 내용 2",
        "구체적 내용 3",
        "구체적 내용 4",
        "구체적 내용 5"
      ],
      "notes": "발표자 참고 노트"
    }}
  ]
}}

[생성할 섹션 — 이 순서대로 8개 모두 포함]
{section_list}

중요: sections 배열에 반드시 8개 항목이 있어야 하며, 각 항목마다 headline·subtitle·bullets·notes 모두 포함."""

_USER_SLIDE2 = """위 초안의 각 섹션에 대해 두 번째 슬라이드용 보조 콘텐츠를 생성하십시오.
각 섹션에서 첫 번째 슬라이드가 "전략/방향"을 다뤘다면, 두 번째 슬라이드는 "구체적 실행/근거/사례"를 다룹니다.

[출력 형식 — JSON only]
{{
  "sections_slide2": [
    {{
      "section_name": "섹션명 (위와 동일)",
      "headline": "두 번째 슬라이드 헤드라인",
      "subtitle": "서브타이틀",
      "bullets": ["실행 내용 1", "실행 내용 2", "실행 내용 3", "실행 내용 4"],
      "notes": "발표자 노트"
    }}
  ]
}}"""


def _build_references_text(results: list, max_chars_per_section: int = 800) -> str:
    """Format top-3 retrieved docs into a rich reference block with all sections."""
    parts = []
    for i, r in enumerate(results, 1):
        m = r["metadata"]
        lines = [
            f"━━ 레퍼런스 {i}: {r['doc_id']} (점수: {r['score']}) ━━",
            f"산업군: {m['industry']} | 프로젝트 유형: {m['project_type']}",
            f"제안 목적: {m['proposal_purpose']}",
            f"톤앤매너: {m['tone_and_manner']} | 강조 가치: {m['emphasized_values']}",
            "",
        ]
        # Include all sections sorted by semantic score
        for sec in r["sections"]:
            preview = sec["text"][:max_chars_per_section].replace("\n", " ").strip()
            lines.append(f"[{sec['section_name']}]")
            lines.append(preview)
            lines.append("")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def generate_draft(retrieve_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Claude call → full proposal draft.

    Returns:
    {
        "cover": {"title", "subtitle"},
        "sections": [{"section_name", "headline", "subtitle", "bullets", "notes"}, ...],
        "sections_slide2": [...],   # second slide content per section
        "query": ...,
        "references": ...
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
        max_headline=MAX_HEADLINE_LEN,
        max_bullet=MAX_BULLET_LEN,
        max_bullets=MAX_BULLETS,
    )

    # First call: main draft
    msg = _client.messages.create(
        model=LLM_MODEL,
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    draft = json.loads(raw)

    # Second call: slide-2 content for each section
    slide2_msg = _client.messages.create(
        model=LLM_MODEL,
        max_tokens=8000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": raw},
            {"role": "user", "content": _USER_SLIDE2},
        ],
    )

    raw2 = slide2_msg.content[0].text.strip()
    raw2 = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw2, flags=re.DOTALL).strip()
    try:
        draft2 = json.loads(raw2)
        draft["sections_slide2"] = draft2.get("sections_slide2", [])
    except json.JSONDecodeError:
        draft["sections_slide2"] = []

    # Attach metadata
    draft["query"] = query
    draft["references"] = [
        {"doc_id": r["doc_id"], "score": r["score"], "industry": r["metadata"]["industry"]}
        for r in results
    ]
    return draft
