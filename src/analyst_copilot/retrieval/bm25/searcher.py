"""Search a BM25 index and return ranked pages."""

from __future__ import annotations

from typing import List, Optional

from analyst_copilot.retrieval.bm25.index import BM25Index
from analyst_copilot.retrieval.models import ScoredPage, SearchResult
from analyst_copilot.retrieval.tokenization import TextTokenizer


class BM25Searcher:
    """Run lexical search against a BM25 index."""

    def __init__(self, tokenizer: Optional[TextTokenizer] = None) -> None:
        self._tokenizer = tokenizer or TextTokenizer()

    def search(
        self,
        index: BM25Index,
        query: str,
        top_k: int = 5,
    ) -> SearchResult:
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        query_tokens = self._tokenizer.tokenize(query)
        if not query_tokens:
            return SearchResult(query=query, doc_name=index.doc_name, hits=[])

        scores = index.model.get_scores(query_tokens)
        ranked_indices = sorted(
            range(len(scores)),
            key=lambda idx: scores[idx],
            reverse=True,
        )

        hits: List[ScoredPage] = []
        rank = 0
        for page_idx in ranked_indices:
            score = float(scores[page_idx])
            if score <= 0:
                continue
            rank += 1
            if rank > top_k:
                break
            hits.append(
                ScoredPage(
                    page=index.pages[page_idx],
                    score=score,
                    rank=rank,
                )
            )

        return SearchResult(query=query, doc_name=index.doc_name, hits=hits)
