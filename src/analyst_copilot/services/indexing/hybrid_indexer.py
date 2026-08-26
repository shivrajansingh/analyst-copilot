"""Build and persist BM25 + vector indices for a filing."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from analyst_copilot.parsing.markdown_store import MarkdownPageStore
from analyst_copilot.parsing.models import FilingDocument
from analyst_copilot.parsing.registry import parse_document
from analyst_copilot.retrieval.bm25.builder import BM25IndexBuilder
from analyst_copilot.retrieval.bm25.storage import BM25IndexStore
from analyst_copilot.retrieval.vector.builder import VectorIndexBuilder
from analyst_copilot.retrieval.vector.storage import VectorIndexStore
from analyst_copilot.services.indexing.models import FilingIndices


class HybridFilingIndexer:
    """Parse a document of any supported format and build both indices."""

    def __init__(
        self,
        vector_builder: Optional[VectorIndexBuilder] = None,
        bm25_store: Optional[BM25IndexStore] = None,
        vector_store: Optional[VectorIndexStore] = None,
        markdown_store: Optional[MarkdownPageStore] = None,
    ) -> None:
        self._vector_builder = vector_builder or VectorIndexBuilder()
        self._bm25_store = bm25_store or BM25IndexStore()
        self._vector_store = vector_store or VectorIndexStore()
        self._markdown_store = markdown_store or MarkdownPageStore()

    def parse(self, filing_path: Union[Path, str], doc_name: Optional[str] = None) -> FilingDocument:
        """
        Parse any supported format into Markdown segments, and write them out.

        The Markdown is persisted here rather than at save time because it is
        the parse result, not an index artifact: a run that fails while
        embedding should still leave behind what the parser read, which is the
        first thing anyone looks at when a citation is wrong.
        """
        document = parse_document(filing_path, doc_name=doc_name)
        self._markdown_store.save(document)
        return document

    def build_indices(self, document: FilingDocument) -> FilingIndices:
        bm25_index = BM25IndexBuilder().build(document)
        vector_index = self._vector_builder.build(document)
        return FilingIndices(
            doc_name=document.doc_name,
            bm25_index=bm25_index,
            vector_index=vector_index,
        )

    def save_indices(self, indices: FilingIndices) -> None:
        """
        Persist both indices for an already-built filing.

        Split out of `index_filing` so a caller that needs to report progress
        can drive parse -> build -> save itself and still keep the pairing of
        the two stores in one place.
        """
        self._bm25_store.save(indices.bm25_index)
        self._vector_store.save(indices.vector_index)

    def index_filing(
        self,
        filing_path: Union[Path, str],
        doc_name: Optional[str] = None,
        save: bool = True,
    ) -> FilingIndices:
        document = self.parse(filing_path, doc_name=doc_name)
        indices = self.build_indices(document)
        if save:
            self.save_indices(indices)
        return indices

    def load_indices(self, doc_name: str) -> FilingIndices:
        return FilingIndices(
            doc_name=doc_name,
            bm25_index=self._bm25_store.load(doc_name),
            vector_index=self._vector_store.load(doc_name),
        )

    def indices_exist(self, doc_name: str) -> bool:
        return self._bm25_store.exists(doc_name) and self._vector_store.exists(doc_name)
