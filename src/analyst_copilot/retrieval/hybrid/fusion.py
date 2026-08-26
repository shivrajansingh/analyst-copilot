"""Score normalization and fusion for hybrid retrieval.

Scores are keyed by whatever identifies a page to the caller. Searching one
document keys by `page_index`; searching a folder keys by `(doc_name,
page_index)`, because page 59 exists in every filing in it. The arithmetic is
identical either way, so the key is typed as a hashable rather than an int.
"""

from __future__ import annotations

from typing import Dict, Hashable, List, Tuple, TypeVar

Key = TypeVar("Key", bound=Hashable)


def min_max_normalize(scores: Dict[Key, float]) -> Dict[Key, float]:
    """Normalize scores to [0, 1]. Empty input returns empty output."""
    if not scores:
        return {}

    values = list(scores.values())
    min_score = min(values)
    max_score = max(values)

    if max_score == min_score:
        return {key: 1.0 if max_score > 0 else 0.0 for key in scores}

    scale = max_score - min_score
    return {key: (score - min_score) / scale for key, score in scores.items()}


def weighted_fusion(
    bm25_scores: Dict[Key, float],
    vector_scores: Dict[Key, float],
    bm25_weight: float,
    vector_weight: float,
) -> Dict[Key, float]:
    """
    Fuse lexical and dense scores with min-max normalization.

    Page indices that appear in only one retriever still receive a partial score.
    """
    candidate_ids = set(bm25_scores) | set(vector_scores)
    if not candidate_ids:
        return {}

    bm25_norm = min_max_normalize(bm25_scores)
    vector_norm = min_max_normalize(vector_scores)

    fused: Dict[Key, float] = {}
    for page_idx in candidate_ids:
        fused[page_idx] = (
            bm25_weight * bm25_norm.get(page_idx, 0.0)
            + vector_weight * vector_norm.get(page_idx, 0.0)
        )
    return fused


def ranks_from_scores(scores: Dict[Key, float]) -> Dict[Key, int]:
    """Convert scores to 1-based ranks (highest score = rank 1)."""
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return {page_idx: rank for rank, (page_idx, _) in enumerate(ordered, start=1)}


def reciprocal_rank_fusion(
    rank_lists: List[Dict[Key, int]],
    rrf_k: int = 60,
) -> Dict[int, float]:
    """
    Reciprocal Rank Fusion: sum 1 / (k + rank) across retrievers.

    Pages missing from a list contribute 0 from that retriever.
    """
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    fused: Dict[Key, float] = {}
    candidate_ids = set().union(*rank_lists) if rank_lists else set()
    for page_idx in candidate_ids:
        total = 0.0
        for ranks in rank_lists:
            rank = ranks.get(page_idx)
            if rank is not None:
                total += 1.0 / (rrf_k + rank)
        fused[page_idx] = total
    return fused


def combine_fusion_scores(
    rrf_scores: Dict[Key, float],
    weighted_scores: Dict[Key, float],
    rrf_weight: float,
    weighted_weight: float,
) -> Dict[int, float]:
    """Blend RRF ranks with min-max weighted lexical/dense scores."""
    rrf_norm = min_max_normalize(rrf_scores)
    weighted_norm = min_max_normalize(weighted_scores)
    candidate_ids = set(rrf_norm) | set(weighted_norm)
    return {
        page_idx: (
            rrf_weight * rrf_norm.get(page_idx, 0.0)
            + weighted_weight * weighted_norm.get(page_idx, 0.0)
        )
        for page_idx in candidate_ids
    }


def rank_by_score(scores: Dict[Key, float], top_k: int) -> List[Tuple[Key, float]]:
    """Return top-k (page_index, score) pairs sorted by descending score."""
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ranked[:top_k]
