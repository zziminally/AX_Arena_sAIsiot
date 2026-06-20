"""
ProposalPilot — Streamlit Web UI (v3)
Phase machine: idle → generating → preview → done
Run: venv/bin/streamlit run app.py
"""
import json
import queue
import re
import threading
import time
from pathlib import Path

import anthropic
import streamlit as st

from src.config import ANTHROPIC_API_KEY, LLM_MODEL
from src.retriever import retrieve
from src.generator import build_prompts, _USER_SLIDE2, regenerate_section
from src.validator import validate_draft, enforce_limits
from src.assembler import assemble

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ProposalPilot — 올림플래닛",
    page_icon="🚀",
    layout="wide",
)

# ── Background generation thread ───────────────────────────────────────────────

def _gen_thread(system_prompt: str, user_prompt: str,
                q: queue.Queue, stop_ev: threading.Event) -> None:
    """Stream Claude into queue. Sentinel: ("done"|"stopped"|"error", payload)."""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        with client.messages.stream(
            model=LLM_MODEL,
            max_tokens=16000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                if stop_ev.is_set():
                    q.put(("stopped", None))
                    return
                q.put(("chunk", chunk))
        q.put(("done", None))
    except Exception as e:
        q.put(("error", str(e)))


# ── Session state helpers ──────────────────────────────────────────────────────

_DEFAULTS = {
    "phase": "idle",
    "retrieve_result": None,
    "draft": None,
    "output_path": None,
    # generation
    "gen_started": False,
    "gen_thread": None,
    "gen_queue": None,
    "gen_stop": None,
    "stream_raw": "",
    "gen_error": None,
    "gen_system_prompt": "",
    "gen_user_prompt": "",
    "stop_confirm": False,
    # preview
    "preview_initialized": False,
    "regen_pending": None,
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _reset():
    for k, v in _DEFAULTS.items():
        st.session_state[k] = v
    # Clear all edit widget keys
    for key in list(st.session_state.keys()):
        if key.startswith("edit_") or key.startswith("regen_instr_"):
            del st.session_state[key]


# ── Phase: IDLE ────────────────────────────────────────────────────────────────

EXAMPLES = {
    "자동차 XR": (
        "국내 완성차 브랜드 신차 출시를 앞두고 XR 기반 통합 체험 마케팅을 기획 중입니다. "
        "소비자가 전시장 방문 전에 AR 쇼룸과 인터랙티브 콘텐츠를 통해 차량 기술 가치를 체험하도록 기획해 주세요."
    ),
    "가전 hybrid": (
        "프리미엄 가전 브랜드의 신제품 출시 캠페인입니다. 오프라인 체험 팝업스토어와 "
        "디지털 XR 콘텐츠를 결합한 하이브리드 체험 마케팅 전략이 필요합니다."
    ),
    "식음료 popup": (
        "신규 F&B 브랜드 론칭을 위한 팝업 공간 기획 제안입니다. "
        "브랜드 세계관을 감성적으로 전달하고 SNS 바이럴을 유도할 수 있는 체험형 팝업 스토어 운영 전략이 필요합니다."
    ),
}


def _render_idle():
    col_input, col_example = st.columns([3, 1])

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
                "AR 쇼룸과 인터랙티브 콘텐츠로 차량 기술 가치를 전달해주세요."
            ),
            label_visibility="collapsed",
        )
        if st.button(
            "제안서 생성",
            type="primary",
            disabled=not (user_input or "").strip(),
            use_container_width=True,
        ):
            st.session_state.phase = "generating"
            st.rerun()


# ── Phase: GENERATING ─────────────────────────────────────────────────────────

def _render_generating():
    # ── First entry: retrieve + start thread ──────────────────────────────────
    if not st.session_state.gen_started:
        with st.status("레퍼런스 검색 중...", expanded=True) as s:
            try:
                result = retrieve(st.session_state.proposal_input)
                st.session_state.retrieve_result = result
                q = result["query"]
                s.update(
                    label=f"검색 완료 — {q['industry']} / {q['project_type'][:25]}",
                    state="complete",
                )
            except Exception as e:
                s.update(label="검색 실패", state="error")
                st.error(f"레퍼런스 검색 오류: {e}")
                if st.button("처음으로"):
                    _reset()
                    st.rerun()
                return

        sp, up = build_prompts(st.session_state.retrieve_result)
        stop_ev = threading.Event()
        q = queue.Queue()
        t = threading.Thread(target=_gen_thread, args=(sp, up, q, stop_ev), daemon=True)
        t.start()

        st.session_state.gen_started      = True
        st.session_state.gen_thread       = t
        st.session_state.gen_queue        = q
        st.session_state.gen_stop         = stop_ev
        st.session_state.gen_system_prompt = sp
        st.session_state.gen_user_prompt   = up
        st.session_state.stream_raw        = ""
        st.rerun()
        return

    # ── Poll queue ────────────────────────────────────────────────────────────
    gen_done = gen_stopped = False
    q = st.session_state.gen_queue
    while True:
        try:
            kind, val = q.get_nowait()
            if kind == "chunk":
                st.session_state.stream_raw += val
            elif kind == "done":
                gen_done = True
                break
            elif kind == "stopped":
                gen_stopped = True
                break
            elif kind == "error":
                st.session_state.gen_error = val
                gen_done = True
                break
        except queue.Empty:
            break

    # ── Progress display ──────────────────────────────────────────────────────
    raw = st.session_state.stream_raw
    found = re.findall(r'"section_name"\s*:\s*"([^"]+)"', raw)
    pct = min(len(found) / 8, 1.0)

    st.subheader("초안 생성 중...")
    st.progress(pct, text=f"섹션 {len(found)} / 8 완성")
    if found:
        st.caption(f"작성 중: **{found[-1]}**")

    # ── Stop button / confirm dialog ──────────────────────────────────────────
    if st.session_state.stop_confirm:
        st.warning("생성을 중지하시겠습니까? 처음 화면으로 돌아갑니다.")
        col_ok, col_cancel = st.columns(2)
        with col_ok:
            if st.button("확인", type="primary", use_container_width=True):
                if st.session_state.get("gen_stop"):
                    st.session_state.gen_stop.set()
                _reset()
                st.rerun()
        with col_cancel:
            if st.button("계속 생성", use_container_width=True):
                st.session_state.stop_confirm = False
                st.rerun()
    else:
        if st.button("⏹ 생성 중지", type="secondary"):
            st.session_state.stop_confirm = True
            st.rerun()

    # ── Transition to preview ─────────────────────────────────────────────────
    if gen_done:
        _finish_generation()
    elif not st.session_state.stop_confirm:
        # 확인 대기 중엔 polling 멈춤
        time.sleep(0.15)
        st.rerun()


def _finish_generation():
    raw = st.session_state.stream_raw
    raw_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()

    draft = None
    try:
        draft = json.loads(raw_clean)
        validate_draft(draft)
    except Exception:
        # Try to salvage complete sections from partial JSON
        sections = _extract_partial_sections(raw)
        if sections:
            cover_m = re.search(r'"title"\s*:\s*"([^"]+)"', raw)
            cover_title = cover_m.group(1) if cover_m else "제안서 초안"
            draft = {"cover": {"title": cover_title, "subtitle": "(생성 중 중지됨)"}, "sections": sections}
        else:
            err = st.session_state.gen_error or "JSON 파싱 실패"
            st.error(f"초안 생성 실패: {err}")
            if st.button("처음으로"):
                _reset()
                st.rerun()
            return

    # Slide-2 (best-effort, non-streaming)
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        slide2 = client.messages.create(
            model=LLM_MODEL, max_tokens=8000,
            system=st.session_state.gen_system_prompt,
            messages=[
                {"role": "user", "content": st.session_state.gen_user_prompt},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _USER_SLIDE2},
            ],
        )
        raw2 = re.sub(r"^```(?:json)?\s*|\s*```$", "",
                      slide2.content[0].text.strip(), flags=re.DOTALL).strip()
        draft["sections_slide2"] = json.loads(raw2).get("sections_slide2", [])
    except Exception:
        draft["sections_slide2"] = []

    enforce_limits(draft)
    rr = st.session_state.retrieve_result
    draft["query"] = rr["query"]
    draft["references"] = [
        {"doc_id": r["doc_id"], "score": r["score"], "industry": r["metadata"]["industry"]}
        for r in rr["results"]
    ]

    st.session_state.draft = draft
    st.session_state.phase = "preview"
    st.rerun()


def _extract_partial_sections(raw: str):
    """Best-effort: pull complete section dicts from a truncated JSON stream."""
    results = []
    for m in re.finditer(
        r'\{[^{}]*"section_name"\s*:[^{}]*"headline"\s*:[^{}]*"bullets"\s*:\s*\[[^\]]*\][^{}]*\}',
        raw, re.DOTALL
    ):
        try:
            sec = json.loads(m.group())
            if sec.get("section_name") and sec.get("headline"):
                results.append(sec)
        except Exception:
            pass
    return results


# ── Phase: PREVIEW ─────────────────────────────────────────────────────────────

def _sync_draft_to_widgets():
    """Populate edit widget keys from draft (only once per preview session)."""
    draft = st.session_state.draft
    st.session_state["edit_cover_title"]    = draft["cover"].get("title", "")
    st.session_state["edit_cover_subtitle"] = draft["cover"].get("subtitle", "")
    for i, sec in enumerate(draft.get("sections", [])):
        st.session_state[f"edit_headline_{i}"] = sec.get("headline", "")
        st.session_state[f"edit_subtitle_{i}"] = sec.get("subtitle", "")
        st.session_state[f"edit_bullets_{i}"]  = "\n".join(sec.get("bullets", []))
    st.session_state.preview_initialized = True


def _collect_widgets_to_draft():
    """Read all edit widgets and write back into draft (before assembly)."""
    draft = st.session_state.draft
    draft["cover"]["title"]    = st.session_state.get("edit_cover_title",    draft["cover"]["title"])
    draft["cover"]["subtitle"] = st.session_state.get("edit_cover_subtitle", draft["cover"].get("subtitle", ""))
    for i, sec in enumerate(draft.get("sections", [])):
        sec["headline"] = st.session_state.get(f"edit_headline_{i}", sec.get("headline", ""))
        sec["subtitle"] = st.session_state.get(f"edit_subtitle_{i}", sec.get("subtitle", ""))
        raw_bullets = st.session_state.get(f"edit_bullets_{i}", "")
        sec["bullets"] = [b.strip() for b in raw_bullets.split("\n") if b.strip()]


def _render_preview():
    draft = st.session_state.draft

    # ── Handle pending AI section regen ──────────────────────────────────────
    regen = st.session_state.pop("regen_pending", None)
    if regen:
        i, instruction = regen
        sec = draft["sections"][i]
        with st.spinner(f"[{sec['section_name']}] 재생성 중..."):
            try:
                new_sec = regenerate_section(
                    sec["section_name"], instruction, sec,
                    st.session_state.retrieve_result,
                )
                draft["sections"][i] = new_sec
                st.session_state[f"edit_headline_{i}"] = new_sec.get("headline", "")
                st.session_state[f"edit_subtitle_{i}"] = new_sec.get("subtitle", "")
                st.session_state[f"edit_bullets_{i}"]  = "\n".join(new_sec.get("bullets", []))
                st.toast(f"[{sec['section_name']}] 재생성 완료")
            except Exception as e:
                st.error(f"재생성 실패: {e}")

    # ── Initialize widget values from draft (first visit) ────────────────────
    if not st.session_state.preview_initialized:
        _sync_draft_to_widgets()

    # ── Header ────────────────────────────────────────────────────────────────
    col_h, col_btn = st.columns([4, 1])
    with col_h:
        st.subheader("초안 미리보기 및 수정")
        st.caption("내용을 직접 편집하거나 AI 재생성을 요청하세요.")
    with col_btn:
        if st.button("↩ 처음으로", use_container_width=True):
            _reset()
            st.rerun()

    # ── Cover ─────────────────────────────────────────────────────────────────
    with st.expander("**표지**", expanded=True):
        st.text_input("제목", key="edit_cover_title")
        st.text_input("부제목", key="edit_cover_subtitle")

    # ── Sections ──────────────────────────────────────────────────────────────
    for i, sec in enumerate(draft.get("sections", [])):
        with st.expander(f"**{i+1}. {sec['section_name']}**", expanded=False):
            c1, c2 = st.columns([2, 1])
            with c1:
                st.text_input("헤드라인", key=f"edit_headline_{i}")
                st.text_input("서브타이틀", key=f"edit_subtitle_{i}")
                st.text_area(
                    "불릿 포인트 (줄바꿈으로 구분)",
                    key=f"edit_bullets_{i}",
                    height=130,
                )
            with c2:
                st.markdown("**AI 재생성**")
                instr = st.text_area(
                    "수정 지시사항",
                    key=f"regen_instr_{i}",
                    height=100,
                    placeholder="예) 더 구체적인 실행 방안 위주로 작성해줘",
                    label_visibility="collapsed",
                )
                if st.button("재생성", key=f"regen_btn_{i}", use_container_width=True):
                    if (instr or "").strip():
                        st.session_state["regen_pending"] = (i, instr.strip())
                        st.rerun()
                    else:
                        st.warning("지시사항을 입력하세요.")

    # ── Finalize ──────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("검색된 레퍼런스")
    rr = st.session_state.retrieve_result
    ref_cols = st.columns(len(rr["results"]))
    for col, r in zip(ref_cols, rr["results"]):
        with col:
            m = r["metadata"]
            st.metric(r["doc_id"], f"score {r['score']}")
            st.caption(f"{m['industry']} · {m['project_type']}")

    st.divider()
    if st.button("최종 PPT 생성", type="primary", use_container_width=True):
        _collect_widgets_to_draft()
        with st.spinner("PPT 조립 중..."):
            try:
                template_path = str(Path(rr["results"][0]["metadata"]["file_path"]))
                output_path = assemble(st.session_state.draft, template_path)
                st.session_state.output_path = str(output_path)
                st.session_state.phase = "done"
                st.rerun()
            except Exception as e:
                st.error(f"PPT 생성 오류: {e}")


# ── Phase: DONE ───────────────────────────────────────────────────────────────

def _render_done():
    st.success("PPT 생성 완료!")

    output_path = Path(st.session_state.output_path)
    pptx_bytes = output_path.read_bytes()

    st.download_button(
        label=f"⬇ PPTX 다운로드 — {output_path.name}",
        data=pptx_bytes,
        file_name=output_path.name,
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        type="primary",
        use_container_width=True,
    )

    # Summary
    draft = st.session_state.draft
    st.markdown(f"### {draft['cover']['title']}")
    st.caption(draft['cover'].get('subtitle', ''))

    with st.expander("섹션 목록"):
        for sec in draft.get("sections", []):
            st.markdown(f"**{sec['section_name']}** — {sec.get('headline', '')}")

    st.divider()
    if st.button("새 제안서 생성", use_container_width=True):
        _reset()
        st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("ProposalPilot")
st.caption("올림플래닛 AI 제안서 생성 시스템 · Powered by Claude + OpenAI Embeddings")
st.divider()

phase = st.session_state.phase
if   phase == "idle":       _render_idle()
elif phase == "generating": _render_generating()
elif phase == "preview":    _render_preview()
elif phase == "done":       _render_done()
