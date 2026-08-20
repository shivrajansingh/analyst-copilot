"""Hybrid retrieval combining BM25 and dense vector search."""

from __future__ import annotations

from typing import List, Optional

from analyst_copilot.config.settings import get_settings
from analyst_copilot.retrieval.bm25.index import BM25Index
from analyst_copilot.retrieval.bm25.searcher import BM25Searcher
from analyst_copilot.retrieval.hybrid.boosting import StatementTitleBooster
from analyst_copilot.retrieval.hybrid.fusion import (
    combine_fusion_scores,
    ranks_from_scores,
    reciprocal_rank_fusion,
    rank_by_score,
    weighted_fusion,
)
from analyst_copilot.retrieval.hybrid.query_expansion import FinancialQueryExpander
from analyst_copilot.retrieval.models import ScoredPage, SearchResult
from analyst_copilot.retrieval.vector.index import VectorIndex
from analyst_copilot.retrieval.vector.searcher import VectorSearcher


class HybridSearcher:
    """Merge BM25 and vector retrieval into a single ranked result set."""

    def __init__(
        self,
        bm25_searcher: Optional[BM25Searcher] = None,
        vector_searcher: Optional[VectorSearcher] = None,
        query_expander: Optional[FinancialQueryExpander] = None,
        statement_booster: Optional[StatementTitleBooster] = None,
        bm25_weight: Optional[float] = None,
        vector_weight: Optional[float] = None,
        candidate_pool: Optional[int] = None,
        rrf_k: Optional[int] = None,
        rrf_weight: Optional[float] = None,
        weighted_weight: Optional[float] = None,
        statement_boost: Optional[float] = None,
    ) -> None:
        settings = get_settings()
        self._bm25_searcher = bm25_searcher or BM25Searcher()
        self._vector_searcher = vector_searcher or VectorSearcher()
        self._query_expander = query_expander or FinancialQueryExpander()
        boost = statement_boost if statement_boost is not None else settings.hybrid_statement_boost
        self._statement_booster = statement_booster or StatementTitleBooster(multiplier=boost)
        self._bm25_weight = bm25_weight if bm25_weight is not None else settings.hybrid_bm25_weight
        self._vector_weight = vector_weight if vector_weight is not None else settings.hybrid_vector_weight
        self._candidate_pool = candidate_pool if candidate_pool is not None else settings.hybrid_candidate_pool
        self._rrf_k = rrf_k if rrf_k is not None else settings.hybrid_rrf_k
        self._rrf_weight = rrf_weight if rrf_weight is not None else settings.hybrid_rrf_weight
        self._weighted_weight = (
            weighted_weight if weighted_weight is not None else settings.hybrid_weighted_weight
        )

    def search(
        self,
        bm25_index: BM25Index,
        vector_index: VectorIndex,
        query: str,
        top_k: int = 5,
    ) -> SearchResult:
        if bm25_index.doc_name != vector_index.doc_name:
            raise ValueError("BM25 and vector indices must belong to the same document")

        if top_k <= 0:
            raise ValueError("top_k must be positive")

        expanded_query = self._query_expander.expand(query)
        pool_size = min(self._candidate_pool, len(bm25_index.pages))

        bm25_result = self._bm25_searcher.search(
            bm25_index,
            expanded_query,
            top_k=pool_size,
        )
        vector_result = self._vector_searcher.search(
            vector_index,
            expanded_query,
            top_k=pool_size,
        )

        bm25_scores = {hit.page.page_index: hit.score for hit in bm25_result.hits}
        vector_scores = {hit.page.page_index: hit.score for hit in vector_result.hits}

        rrf_scores = reciprocal_rank_fusion(
            [
                ranks_from_scores(bm25_scores),
                ranks_from_scores(vector_scores),
            ],
            rrf_k=self._rrf_k,
        )
        weighted_scores = weighted_fusion(
            bm25_scores=bm25_scores,
            vector_scores=vector_scores,
            bm25_weight=self._bm25_weight,
            vector_weight=self._vector_weight,
        )
        fused_scores = combine_fusion_scores(
            rrf_scores=rrf_scores,
            weighted_scores=weighted_scores,
            rrf_weight=self._rrf_weight,
            weighted_weight=self._weighted_weight,
        )

        page_lookup = {page.page_index: page for page in bm25_index.pages}
        fused_scores = self._statement_booster.apply(query, page_lookup, fused_scores)
        ranked = rank_by_score(fused_scores, top_k=top_k)

        hits: List[ScoredPage] = []
        for rank, (page_idx, fused_score) in enumerate(ranked, start=1):
            if fused_score <= 0:
                continue
            hits.append(
                ScoredPage(
                    page=page_lookup[page_idx],
                    score=fused_score,
                    rank=rank,
                    bm25_score=bm25_scores.get(page_idx),
                    vector_score=vector_scores.get(page_idx),
                )
            )

        return SearchResult(query=query, doc_name=bm25_index.doc_name, hits=hits)
