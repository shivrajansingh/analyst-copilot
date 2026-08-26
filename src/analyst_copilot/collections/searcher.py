"""Hybrid retrieval across every document in a collection.

Searching a folder is not the same problem as searching a document, and the
difference is entirely about **comparability of scores**.

Per-document retrieval min-max normalizes each retriever's scores over one
filing's pages, which is sound because the only question is which of those
pages wins. Run that per document and merge, and every filing's best page
normalizes to ~1.0 -- the merge becomes "one page from each document", ranked
by nothing.

So the candidates are pooled *before* normalization: raw scores from every
document go into one dictionary keyed by `(doc_name, page_index)`, and the
normalization happens once over the pool. Two consequences worth being explicit
about:

- **Cosine similarity is comparable across documents by construction.** Same
  model, same vector space; a 0.71 in one filing means what it means in another.
  This is the signal the ranking rests on, and it carries weight 0.9.
- **BM25 is not.** Its idf is computed over one document's pages, so a term that
  is rare in a 10-K and common in an 8-K scores differently for reasons that
  have nothing to do with relevance. Pooling raw BM25 across documents is
  therefore approximate. It is done anyway, at weight 0.1, because the
  alternative -- dropping lexical search from folder queries -- loses exact
  line-item matching entirely. Worth revisiting if the weight ever rises.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from analyst_copilot.config.settings import get_settings
from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.bm25.searcher import BM25Searcher
from analyst_copilot.retrieval.hybrid.boosting import StatementTitleBooster
from analyst_copilot.retrieval.hybrid.fusion import rank_by_score, weighted_fusion
from analyst_copilot.retrieval.hybrid.query_expansion import FinancialQueryExpander
from analyst_copilot.retrieval.models import ScoredPage, SearchResult
from analyst_copilot.retrieval.vector.searcher import VectorSearcher
from analyst_copilot.services.indexing.models import FilingIndices

# (doc_name, page_index) -- page 59 exists in every filing in the folder.
PageKey = Tuple[str, int]


class CollectionSearcher:
    """Rank pages from many documents against one question."""

    def __init__(
        self,
        bm25_searcher: Optional[BM25Searcher] = None,
        vector_searcher: Optional[VectorSearcher] = None,
        query_expander: Optional[FinancialQueryExpander] = None,
        statement_booster: Optional[StatementTitleBooster] = None,
        bm25_weight: Optional[float] = None,
        vector_weight: Optional[float] = None,
        candidate_pool: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._bm25_searcher = bm25_searcher or BM25Searcher()
        self._vector_searcher = vector_searcher or VectorSearcher()
        self._query_expander = query_expander or FinancialQueryExpander()
        self._statement_booster = statement_booster or StatementTitleBooster(
            multiplier=settings.hybrid_statement_boost
        )
        self._bm25_weight = (
            bm25_weight if bm25_weight is not None else settings.hybrid_bm25_weight
        )
        self._vector_weight = (
            vector_weight if vector_weight is not None else settings.hybrid_vector_weight
        )
        self._candidate_pool = (
            candidate_pool if candidate_pool is not None else settings.hybrid_candidate_pool
        )

    def search(
        self,
        indices: Sequence[FilingIndices],
        query: str,
        top_k: int = 5,
        collection_name: str = "",
    ) -> SearchResult:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not indices:
            return SearchResult(query=query, doc_name=collection_name, hits=[])

        expanded = self._query_expander.expand(query)
        # Embed once for the whole folder. Per-document embedding would be one
        # network round trip per filing for a single question.
        query_vector = self._vector_searcher.embed_query(expanded)

        bm25_scores: Dict[PageKey, float] = {}
        vector_scores: Dict[PageKey, float] = {}
        pages: Dict[PageKey, Page] = {}

        for entry in indices:
            doc_name = entry.bm25_index.doc_name
            pool = min(self._candidate_pool, len(entry.bm25_index.pages))
            if pool <= 0:
                continue

            for hit in self._bm25_searcher.search(entry.bm25_index, expanded, top_k=pool).hits:
                bm25_scores[(doc_name, hit.page.page_index)] = hit.score
            for hit in self._vector_searcher.search(
                entry.vector_index, expanded, top_k=pool, query_vector=query_vector
            ).hits:
                vector_scores[(doc_name, hit.page.page_index)] = hit.score

            for page in entry.bm25_index.pages:
                pages[(doc_name, page.page_index)] = page

        fused = weighted_fusion(
            bm25_scores=bm25_scores,
            vector_scores=vector_scores,
            bm25_weight=self._bm25_weight,
            vector_weight=self._vector_weight,
        )
        fused = self._statement_booster.apply(query, pages, fused)

        hits: List[ScoredPage] = []
        for rank, (key, score) in enumerate(rank_by_score(fused, top_k=top_k), start=1):
            if score <= 0:
                continue
            hits.append(
                ScoredPage(
                    page=pages[key],
                    score=score,
                    rank=rank,
                    bm25_score=bm25_scores.get(key),
                    vector_score=vector_scores.get(key),
                )
            )

        return SearchResult(query=query, doc_name=collection_name, hits=hits)
