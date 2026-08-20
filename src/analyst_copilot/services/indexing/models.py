"""Domain models for filing indexing services."""

from __future__ import annotations

from dataclasses import dataclass

from analyst_copilot.retrieval.bm25.index import BM25Index
from analyst_copilot.retrieval.vector.index import VectorIndex


@dataclass
class FilingIndices:
    """BM25 and vector indices for a single filing."""

    doc_name: str
    bm25_index: BM25Index
    vector_index: VectorIndex
