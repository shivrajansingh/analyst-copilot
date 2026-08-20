"""High-level filing indexing workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from analyst_copilot.parsing.html_filing_parser import parse_filing_html
from analyst_copilot.parsing.models import FilingDocument
from analyst_copilot.retrieval.bm25.builder import BM25IndexBuilder
from analyst_copilot.retrieval.bm25.index import BM25Index
from analyst_copilot.retrieval.bm25.storage import BM25IndexStore


class FilingIndexer:
    """Parse a filing and build a persisted BM25 index."""

    def __init__(
        self,
        builder: Optional[BM25IndexBuilder] = None,
        store: Optional[BM25IndexStore] = None,
    ) -> None:
        self._builder = builder or BM25IndexBuilder()
        self._store = store or BM25IndexStore()

    def parse(self, filing_path: Union[Path, str], doc_name: Optional[str] = None) -> FilingDocument:
        return parse_filing_html(filing_path, doc_name=doc_name)

    def build_index(self, document: FilingDocument) -> BM25Index:
        return self._builder.build(document)

    def index_filing(
        self,
        filing_path: Union[Path, str],
        doc_name: Optional[str] = None,
        save: bool = True,
    ) -> BM25Index:
        document = self.parse(filing_path, doc_name=doc_name)
        index = self.build_index(document)
        if save:
            self._store.save(index)
        return index

    def load_index(self, doc_name: str) -> BM25Index:
        return self._store.load(doc_name)

    def index_exists(self, doc_name: str) -> bool:
        return self._store.exists(doc_name)
