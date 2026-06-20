"""
Phase 1 — Indexing pipeline
Usage: venv/bin/python ingest.py [--reset]
"""
import sys
import time

from src.ingestor import load_metadata, build_chunks
from src.vector_store import index_chunks, count, reset


def main():
    reset_flag = "--reset" in sys.argv
    print("=== ProposalPilot — Indexing Pipeline ===\n")

    if reset_flag:
        print("[0] Resetting existing collection...")
        reset()
        print()

    t0 = time.time()

    print("[1/3] Loading metadata CSV...")
    metadata = load_metadata()
    print(f"  {len(metadata)} documents loaded\n")

    print("[2/3] Parsing PPTX files and building chunks...")
    chunks = build_chunks(metadata)
    doc_count = len({c["metadata"]["doc_id"] for c in chunks})
    print(f"  {len(chunks)} chunks from {doc_count} documents\n")

    # Preview chunk distribution
    from collections import Counter
    sec_counts = Counter(c["metadata"]["doc_id"] for c in chunks)
    for doc_id, n in sorted(sec_counts.items()):
        print(f"    {doc_id}: {n} chunks")
    print()

    print("[3/3] Embedding and indexing into ChromaDB...")
    index_chunks(chunks)

    elapsed = time.time() - t0
    total = count()
    print(f"\n✓ Done: {total} chunks in ChromaDB  ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
