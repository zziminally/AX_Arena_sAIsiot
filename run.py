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
    print(f"  표지: {draft['cover']['title']}")
    print(f"  섹션 수: {len(draft.get('sections', []))}")

    # ── Step 3: Assemble PPT ───────────────────────────────────────────────
    print("\n[3/3] PPT 조립 중...")
    template_path = str(Path(result["results"][0]["metadata"]["file_path"]))
    output_path = assemble(draft, template_path)
    print(f"  저장: {output_path}")

    # ── Save retrieval log ─────────────────────────────────────────────────
    log_path = output_path.with_suffix(".json")
    log = {
        "user_input":  user_input,
        "query":       draft["query"],
        "references":  draft["references"],
        "cover":       draft["cover"],
        "sections":    [
            {"section_name": s["section_name"], "headline": s["headline"]}
            for s in draft.get("sections", [])
        ],
    }
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2))
    print(f"  로그:  {log_path}")

    elapsed = time.time() - t0
    print(f"\n✓ 완료 ({elapsed:.1f}s)")
    print(f"  → {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: venv/bin/python run.py '제안 요청 내용'")
        sys.exit(1)
    main(" ".join(sys.argv[1:]))
