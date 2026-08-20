"""Search a vector index via cosine similarity."""

from __future__ import annotations

from typing import List, Optional

from analyst_copilot.embeddings import get_embedding_client
from analyst_copilot.embeddings.base import EmbeddingClient
from analyst_copilot.retrieval.models import ScoredPage, SearchResult
from analyst_copilot.retrieval.vector.index import VectorIndex
from analyst_copilot.retrieval.vector.similarity import cosine_similarity_matrix


class VectorSearcher:
    """Run dense vector search against a page embedding index."""

    def __init__(self, embedding_client: Optional[EmbeddingClient] = None) -> None:
        self._embedding_client = embedding_client or get_embedding_client()

    def search(
        self,
        index: VectorIndex,
        query: str,
        top_k: int = 5,
    ) -> SearchResult:
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        query_vector = self._embedding_client.embed_query(query)
        scores = cosine_similarity_matrix(query_vector, index.vectors)

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
                    vector_score=score,
                )
            )

        return SearchResult(query=query, doc_name=index.doc_name, hits=hits)
