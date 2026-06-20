"""
ProposalPilot — End-to-end CLI
Usage: venv/bin/python run.py "신규 제안 요청 내용"
"""
import sys
import json
import time
from pathlib import Path

from src.retriever import retrieve
from src.generator import generate_draft
from src.assembler import assemble


def main(user_input: str) -> None:
    print("=== ProposalPilot ===\n")
    t0 = time.time()

    # ── Step 1: Retrieve ───────────────────────────────────────────────────
    print("[1/3] 레퍼런스 검색 중...")
    result = retrieve(user_input)
    q = result["query"]
    print(f"  분석 → 산업군: {q['industry']} | 유형: {q['project_type']}")
    print(f"  추천 레퍼런스:")
    for r in result["results"]:
        print(f"    [{r['doc_id']}] {r['metadata']['industry']:8s} | "
              f"score={r['score']} | {r['best_section']}")

    # ── Step 2: Generate draft ─────────────────────────────────────────────
    print("\n[2/3] 제안서 초안 생성 중...")
    draft = generate_draft(result)

    # [고객사]/[제품명] placeholder 교체
    # analyzer가 "[고객사]" 자체를 반환할 경우도 방어
    import re as _re
    _ph = _re.compile(r"^\[.+\]$")

    def _safe(val: str, fallback: str) -> str:
        val = (val or "").strip()
        return fallback if (not val or _ph.match(val)) else val

    client_name  = _safe(q.get("client_name",  ""), q.get("industry", "고객사") + " 대기업")
    product_name = _safe(q.get("product_name", ""), "신규 브랜드")

    def _sub(text: str) -> str:
        return text.replace("[고객사]", client_name).replace("[제품명]", product_name)

    draft["cover"]["title"]    = _sub(draft["cover"].get("title", ""))
    draft["cover"]["subtitle"] = _sub(draft["cover"].get("subtitle", ""))
    for sec in draft.get("sections", []) + draft.get("sections_slide2", []):
        for field in ("act_tagline", "headline", "subtitle", "notes"):
            if field in sec:
                sec[field] = _sub(sec[field])
        sec["bullets"] = [_sub(b) for b in sec.get("bullets", [])]
    print(f"  표지: {draft['cover']['title']}")
    print(f"  섹션 수: {len(draft.get('sections', []))}")
    for s in draft.get("sections", []):
        bullets_count = len(s.get("bullets", []))
        print(f"    [{s['section_name']}] headline={bool(s.get('headline'))} "
              f"subtitle={bool(s.get('subtitle'))} bullets={bullets_count}")

    # ── Step 3: Assemble PPT ───────────────────────────────────────────────
    print("\n[3/3] PPT 조립 중...")
    stored_path = Path(result["results"][0]["metadata"]["file_path"])
    if stored_path.exists():
        template_path = str(stored_path)
    else:
        from src.config import PROPOSALS_DIR
        template_path = str(PROPOSALS_DIR / stored_path.name)
    output_path = assemble(draft, template_path)
    print(f"  저장: {output_path}")

    # ── Save full retrieval log ────────────────────────────────────────────
    log_path = output_path.with_suffix(".json")
    log = {
        "user_input":     user_input,
        "query":          draft["query"],
        "references":     draft["references"],
        "cover":          draft["cover"],
        "sections":       draft.get("sections", []),
        "sections_slide2": draft.get("sections_slide2", []),
    }
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  로그:  {log_path}")

    elapsed = time.time() - t0
    print(f"\n✓ 완료 ({elapsed:.1f}s)")
    print(f"  → {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: venv/bin/python run.py '제안 요청 내용'")
        sys.exit(1)
    main(" ".join(sys.argv[1:]))
