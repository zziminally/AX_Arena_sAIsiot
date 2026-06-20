"""
Retrieval evaluator — measures precision@3 and MRR without LLM calls.

Uses pre-analyzed query dicts (bypasses Request Analyzer) so the eval
runs in ~1s instead of ~10s per scenario.
"""
from typing import Dict, List, Any

from src.vector_store import search
from src.retriever import _metadata_score, _soft_keyword_match
from src.config import TOP_K, FINAL_TOP_K

# ── Ground-truth test cases ────────────────────────────────────────────────────
# Each case defines: pre-analyzed query + which doc_ids count as relevant.
# "relevant" = same-industry doc whose project_type meaningfully overlaps.

TEST_CASES: List[Dict[str, Any]] = [
    {
        "name": "자동차 XR",
        "query": {
            "industry": "자동차",
            "project_type": "XR/디지털 콘텐츠 설계, 브랜드/캠페인 전략, 콘텐츠 연출/스토리텔링",
            "key_needs_keywords": ["XR 시승", "신차 출시", "체험 마케팅", "기술 데모", "몰입형 콘텐츠", "AR", "인터랙티브"],
            "tone_and_manner": "기술지향·정교한·설계형",
            "query_text": "자동차 신차 출시를 위한 XR 기반 통합 체험 마케팅. AR 쇼룸과 인터랙티브 콘텐츠로 기술 가치를 전달하고 시승 전환을 유도하는 전략.",
        },
        "relevant": {"OP-S1-01", "OP-S1-02", "OP-S1-03", "OP-S1-04", "OP-S1-05"},
        "highly_relevant": {"OP-S1-03", "OP-S1-01"},  # XR + 브랜드 캠페인
    },
    {
        "name": "가전 hybrid",
        "query": {
            "industry": "가전",
            "project_type": "브랜드/캠페인 전략, XR/디지털 콘텐츠 설계, 프로젝트/공간 기획",
            "key_needs_keywords": ["프리미엄 가전", "신제품 출시", "XR 체험", "팝업스토어", "라이프스타일", "기능 시각화", "상담 전환"],
            "tone_and_manner": "프리미엄·라이프스타일형·설득형",
            "query_text": "프리미엄 가전 신제품 출시를 위한 오프라인 팝업 + XR 디지털 하이브리드 체험. 브랜드 프리미엄 강화 및 상담 전환율 향상.",
        },
        "relevant": {"OP-S2-01", "OP-S2-02", "OP-S2-03", "OP-S2-04", "OP-S2-05"},
        "highly_relevant": {"OP-S2-03", "OP-S2-01"},  # XR + 브랜드 캠페인
    },
    {
        "name": "식음료 popup",
        "query": {
            "industry": "식음료",
            "project_type": "프로젝트/공간 기획, 브랜드/캠페인 전략, 콘텐츠 연출/스토리텔링",
            "key_needs_keywords": ["팝업 스토어", "브랜드 세계관", "체험형 공간", "SNS 바이럴", "F&B 론칭", "감성 전달", "방문자 참여"],
            "tone_and_manner": "감성적·라이프스타일형·기획형",
            "query_text": "신규 F&B 브랜드 론칭을 위한 체험형 팝업 스토어 기획. 브랜드 세계관을 감성 공간으로 구현하고 SNS 바이럴을 유도하는 전략.",
        },
        "relevant": {"OP-S3-01", "OP-S3-02", "OP-S3-03", "OP-S3-04", "OP-S3-05", "OP-S4-05"},
        "highly_relevant": {"OP-S3-01", "OP-S3-02", "OP-S3-03"},
    },
]


# ── Evaluation logic ───────────────────────────────────────────────────────────

def _retrieve_with_alpha(query: Dict, alpha: float, n: int = FINAL_TOP_K) -> List[str]:
    """Run hybrid retrieval with a given alpha, return top-n doc_ids."""
    raw_hits = search(query["query_text"], n_results=TOP_K * 3)

    doc_map: Dict[str, Dict] = {}
    for hit in raw_hits:
        m = hit["metadata"]
        doc_id = m["doc_id"]
        if doc_id == "COMPANY_PROFILE":
            continue
        if doc_id not in doc_map:
            doc_map[doc_id] = {"doc_id": doc_id, "metadata": m, "sections": []}
        doc_map[doc_id]["sections"].append(hit["semantic_score"])

    scored = []
    for doc_id, doc in doc_map.items():
        top_scores = sorted(doc["sections"], reverse=True)
        sem = sum(top_scores[:2]) / min(2, len(top_scores))
        ms = _metadata_score(doc["metadata"], query)
        hs = alpha * ms + (1 - alpha) * sem
        scored.append((doc_id, hs, doc["metadata"].get("project_type", "")))

    scored.sort(key=lambda x: -x[1])

    # Diversity cap
    final, type_count = [], {}
    for doc_id, score, pt in scored:
        if type_count.get(pt, 0) >= 2:
            continue
        type_count[pt] = type_count.get(pt, 0) + 1
        final.append(doc_id)
        if len(final) >= n:
            break
    return final


def _precision_at_k(retrieved: List[str], relevant: set, k: int = 3) -> float:
    return sum(1 for d in retrieved[:k] if d in relevant) / k


def _mrr(retrieved: List[str], relevant: set) -> float:
    for i, d in enumerate(retrieved, 1):
        if d in relevant:
            return 1.0 / i
    return 0.0


def evaluate(alpha: float, verbose: bool = False) -> Dict[str, float]:
    """Run all test cases with given alpha, return aggregate metrics."""
    p3_scores, mrr_scores, hp3_scores = [], [], []

    for tc in TEST_CASES:
        retrieved = _retrieve_with_alpha(tc["query"], alpha)
        p3 = _precision_at_k(retrieved, tc["relevant"])
        mrr = _mrr(retrieved, tc["relevant"])
        hp3 = _precision_at_k(retrieved, tc["highly_relevant"])

        p3_scores.append(p3)
        mrr_scores.append(mrr)
        hp3_scores.append(hp3)

        if verbose:
            print(f"  [{tc['name']}] top3={retrieved}  P@3={p3:.2f}  MRR={mrr:.2f}  H-P@3={hp3:.2f}")

    return {
        "precision_at_3": sum(p3_scores) / len(p3_scores),
        "mrr":            sum(mrr_scores) / len(mrr_scores),
        "high_precision": sum(hp3_scores) / len(hp3_scores),
    }


def sweep_alpha(alphas=None, verbose: bool = True) -> float:
    """Try multiple alpha values and return the best one by composite score."""
    if alphas is None:
        alphas = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]

    best_alpha, best_score = alphas[0], -1.0
    if verbose:
        print(f"{'alpha':>6}  {'P@3':>6}  {'MRR':>6}  {'H-P@3':>6}  {'composite':>10}")
        print("-" * 50)

    for alpha in alphas:
        m = evaluate(alpha)
        composite = 0.4 * m["precision_at_3"] + 0.4 * m["mrr"] + 0.2 * m["high_precision"]
        if verbose:
            print(f"  {alpha:.2f}   {m['precision_at_3']:.3f}   {m['mrr']:.3f}   "
                  f"{m['high_precision']:.3f}   {composite:.3f}")
        if composite > best_score:
            best_score, best_alpha = composite, alpha

    if verbose:
        print(f"\n  Best alpha: {best_alpha} (composite={best_score:.3f})")
    return best_alpha
