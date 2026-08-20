"""Build BM25 indices from parsed filing documents."""

from __future__ import annotations

from typing import Optional

from rank_bm25 import BM25Okapi

from analyst_copilot.parsing.models import FilingDocument
from analyst_copilot.retrieval.bm25.index import BM25Index
from analyst_copilot.retrieval.models import BM25IndexMetadata
from analyst_copilot.retrieval.tokenization import TextTokenizer


class BM25IndexBuilder:
    """Construct a BM25 index from a parsed filing."""

    def __init__(self, tokenizer: Optional[TextTokenizer] = None) -> None:
        self._tokenizer = tokenizer or TextTokenizer()

    def build(self, document: FilingDocument) -> BM25Index:
        if not document.pages:
            raise ValueError(f"No pages to index for document: {document.doc_name}")

        page_texts = [page.text for page in document.pages]
        tokenized_corpus = self._tokenizer.tokenize_many(page_texts)
        bm25_model = BM25Okapi(tokenized_corpus)

        metadata = BM25IndexMetadata(
            doc_name=document.doc_name,
            source_path=document.source_path,
            page_count=len(document.pages),
            tokenizer_version=self._tokenizer.VERSION,
        )

        return BM25Index(
            metadata=metadata,
            pages=list(document.pages),
            tokenized_corpus=tokenized_corpus,
            model=bm25_model,
        )
