"""
ProposalPilot — Streamlit Web UI
Run: venv/bin/streamlit run app.py
"""
import time
from pathlib import Path

import streamlit as st

from src.retriever import retrieve
from src.generator import generate_draft
from src.assembler import assemble

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ProposalPilot — 올림플래닛",
    page_icon="🚀",
    layout="wide",
)

# ── Header ────────────────────────────────────────────────────────────────────

st.title("ProposalPilot")
st.caption("올림플래닛 AI 제안서 생성 시스템 · Powered by Claude + OpenAI Embeddings")

st.divider()

# ── Input form ────────────────────────────────────────────────────────────────

EXAMPLES = {
    "자동차 XR": (
        "국내 완성차 브랜드 신차 출시를 앞두고 XR 기반 통합 체험 마케팅을 기획 중입니다. "
        "소비자가 전시장 방문 전에 차량의 기술 사양을 몰입감 있게 체험할 수 있도록 AR 쇼룸과 "
        "인터랙티브 콘텐츠를 포함한 제안을 원합니다."
    ),
    "가전 hybrid": (
        "프리미엄 가전 브랜드의 신제품 출시 캠페인입니다. 오프라인 체험 팝업스토어와 "
        "디지털 XR 콘텐츠를 결합한 하이브리드 체험 마케팅 전략이 필요합니다. "
        "브랜드 프리미엄 이미지를 강화하고 실구매 전환율을 높이는 것이 핵심 목표입니다."
    ),
    "식음료 popup": (
        "신규 F&B 브랜드 론칭을 위한 팝업 공간 기획 제안입니다. "
        "브랜드 세계관을 감성적으로 전달하고 SNS 바이럴을 유도할 수 있는 "
        "체험형 팝업 스토어 운영 전략이 필요합니다."
    ),
}

col_input, col_example = st.columns([3, 1])

# Inject example text into session state before the widget renders
with col_example:
    st.markdown("**예시 시나리오**")
    for label in EXAMPLES:
        if st.button(label, use_container_width=True):
            st.session_state["proposal_input"] = EXAMPLES[label]

with col_input:
    user_input = st.text_area(
        "제안 요청 내용",
        key="proposal_input",
        height=160,
        placeholder=(
            "예) 국내 완성차 브랜드 신차 출시를 앞두고 XR 기반 통합 체험 마케팅을 기획 중입니다. "
            "소비자가 전시장 방문 전에 AR 쇼룸과 인터랙티브 콘텐츠를 통해 차량 기술 가치를 체험하도록 기획해 주세요."
        ),
        label_visibility="collapsed",
    )
    generate_btn = st.button(
        "제안서 생성",
        type="primary",
        disabled=not (user_input or "").strip(),
        use_container_width=True,
    )

# ── Pipeline execution ────────────────────────────────────────────────────────

if generate_btn and user_input.strip():
    t_start = time.time()

    # ── Step 1: Retrieve ─────────────────────────────────────────────────────
    with st.status("레퍼런스 검색 중...", expanded=True) as status:
        st.write("요청 분석 중 (LLM)...")
        retrieve_result = retrieve(user_input)
        q = retrieve_result["query"]
        results = retrieve_result["results"]

        st.write(f"분석 완료 → 산업군: **{q['industry']}** | 유형: **{q['project_type']}**")
        st.write(f"Top-{len(results)} 레퍼런스 확보")
        status.update(label="레퍼런스 검색 완료", state="complete")

    # ── Step 2: Generate draft ───────────────────────────────────────────────
    with st.status("제안서 초안 생성 중...", expanded=True) as status:
        st.write("Claude로 8개 섹션 초안 작성 중...")
        draft = generate_draft(retrieve_result)
        st.write(f"표지: **{draft['cover']['title']}**")
        st.write(f"섹션 수: {len(draft.get('sections', []))}개")
        status.update(label="초안 생성 완료", state="complete")

    # ── Step 3: Assemble PPT ─────────────────────────────────────────────────
    with st.status("PPT 파일 생성 중...", expanded=True) as status:
        template_path = str(Path(results[0]["metadata"]["file_path"]))
        output_path = assemble(draft, template_path)
        status.update(label="PPT 생성 완료", state="complete")

    elapsed = time.time() - t_start

    # ── Results display ──────────────────────────────────────────────────────
    st.success(f"완료! 처리 시간: **{elapsed:.1f}초**")

    col_refs, col_draft = st.columns(2)

    # Reference results
    with col_refs:
        st.subheader("검색된 레퍼런스")
        for i, r in enumerate(results, 1):
            m = r["metadata"]
            with st.expander(
                f"**{i}. [{r['doc_id']}]** {m['industry']} · {m['project_type']}  "
                f"— score `{r['score']}`",
                expanded=(i == 1),
            ):
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Hybrid Score", r["score"])
                col_b.metric("Semantic", r["semantic_score"])
                col_c.metric("Metadata", r["metadata_score"])

                st.caption(f"Best section: **{r['best_section']}**")
                st.caption(f"Tone: {m['tone_and_manner']}")
                st.caption(f"강조 가치: {m['emphasized_values']}")

                st.markdown("**매칭 섹션 텍스트 미리보기**")
                for sec in r["sections"][:2]:
                    preview = sec["text"][:200].replace("\n", " ")
                    st.markdown(
                        f"> **{sec['section_name']}** _(score: {sec['semantic_score']:.3f})_  \n"
                        f"> {preview}..."
                    )

    # Draft preview
    with col_draft:
        st.subheader("생성된 제안서 초안")
        st.markdown(f"### {draft['cover']['title']}")
        st.caption(draft['cover'].get('subtitle', ''))

        for sec in draft.get("sections", []):
            with st.expander(f"**{sec['section_name']}**", expanded=False):
                st.markdown(f"**{sec.get('headline', '')}**")
                if sec.get("subtitle"):
                    st.caption(sec["subtitle"])
                for bullet in sec.get("bullets", []):
                    st.markdown(f"- {bullet}")
                if sec.get("notes"):
                    st.info(f"발표 노트: {sec['notes']}")

    # Download button
    st.divider()
    st.subheader("파일 다운로드")

    pptx_bytes = output_path.read_bytes()
    filename = output_path.name
    st.download_button(
        label=f"PPTX 다운로드 — {filename}",
        data=pptx_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        type="primary",
        use_container_width=True,
    )

    # Query details
    with st.expander("요청 분석 상세 (Request Analyzer 출력)"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"- **산업군**: {q.get('industry')}")
            st.markdown(f"- **고객사 유형**: {q.get('client_type')}")
            st.markdown(f"- **프로젝트 유형**: {q.get('project_type')}")
            st.markdown(f"- **제안 목적**: {q.get('proposal_purpose')}")
        with col2:
            st.markdown(f"- **제안 단계**: {q.get('proposal_stage')}")
            st.markdown(f"- **톤앤매너**: {q.get('tone_and_manner')}")
            st.markdown(f"- **핵심 키워드**: {', '.join(q.get('key_needs_keywords', []))}")
            st.markdown(f"- **강조 가치**: {', '.join(q.get('emphasized_values', []))}")
        st.markdown(f"**벡터 검색 쿼리**: {q.get('query_text')}")
