"""Index documents into a collection, and load a collection's indices back."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple, Union

from analyst_copilot.collections.models import CollectionDocument
from analyst_copilot.collections.store import CollectionNotFound, CollectionStore
from analyst_copilot.parsing.registry import parse_document
from analyst_copilot.retrieval.bm25.builder import BM25IndexBuilder
from analyst_copilot.retrieval.vector.builder import VectorIndexBuilder
from analyst_copilot.services.indexing.models import FilingIndices

logger = logging.getLogger(__name__)

# Answering one question touches every document in the folder, so the indices
# are cached between questions. A 200-page filing's vectors are a few MB, and
# the cap is on documents rather than bytes because that is what the eviction
# decision is actually about: how many filings a working session moves between.
_CACHE_CAPACITY = 24


class CollectionIndexer:
    """Build and load per-document indices inside one collection."""

    def __init__(
        self,
        store: Optional[CollectionStore] = None,
        vector_builder: Optional[VectorIndexBuilder] = None,
        cache_capacity: int = _CACHE_CAPACITY,
    ) -> None:
        self._store = store or CollectionStore()
        self._vector_builder = vector_builder or VectorIndexBuilder()
        self._cache: "OrderedDict[Tuple[str, str, float], FilingIndices]" = OrderedDict()
        self._cache_capacity = cache_capacity

    @property
    def store(self) -> CollectionStore:
        return self._store

    # -- writing ------------------------------------------------------------ #
    def index_document(
        self,
        collection: str,
        source_path: Union[Path, str],
        doc_name: Optional[str] = None,
    ) -> FilingIndices:
        """
        Parse one document, write its Markdown, and build both indices.

        The Markdown is written before embedding starts, so a run that dies on a
        network call still leaves behind what the parser read.
        """
        path = Path(source_path)
        name = doc_name or path.stem
        self._store.create(collection)

        document = parse_document(path, doc_name=name)
        self._store.markdown_store(collection).save(document)

        indices = FilingIndices(
            doc_name=name,
            bm25_index=BM25IndexBuilder().build(document),
            vector_index=self._vector_builder.build(document),
        )
        self._store.bm25_store(collection).save(indices.bm25_index)
        self._store.vector_store(collection).save(indices.vector_index)

        try:
            self._store.add_document(
                collection,
                CollectionDocument(
                    doc_name=name,
                    source_file=path.name,
                    source_format=document.source_format,
                    segment_count=document.page_count,
                    added_at=time.time(),
                ),
            )
        except CollectionNotFound as exc:
            # Indexing a large filing takes minutes, and the folder can be
            # deleted while it runs. Say so plainly: the job did not fail
            # because the document was bad.
            raise CollectionNotFound(
                f"Folder {collection!r} was deleted while {name!r} was being indexed."
            ) from exc

        self._invalidate(collection, name)
        return indices

    # -- reading ------------------------------------------------------------ #
    def document_is_indexed(self, collection: str, doc_name: str) -> bool:
        return self._store.bm25_store(collection).exists(doc_name) and self._store.vector_store(
            collection
        ).exists(doc_name)

    def ready_documents(self, collection: str) -> List[str]:
        """Members both retrievers can serve. These are what a question searches."""
        found = self._store.load(collection)
        if found is None:
            return []
        return [
            document.doc_name
            for document in found.documents
            if self.document_is_indexed(collection, document.doc_name)
        ]

    def load_document(self, collection: str, doc_name: str) -> FilingIndices:
        key = (collection, doc_name, self._stamp(collection, doc_name))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        indices = FilingIndices(
            doc_name=doc_name,
            bm25_index=self._store.bm25_store(collection).load(doc_name),
            vector_index=self._store.vector_store(collection).load(doc_name),
        )
        self._cache[key] = indices
        while len(self._cache) > self._cache_capacity:
            self._cache.popitem(last=False)
        return indices

    def load_collection(self, collection: str) -> List[FilingIndices]:
        """Every searchable document in the folder, in name order."""
        loaded: List[FilingIndices] = []
        for doc_name in self.ready_documents(collection):
            try:
                loaded.append(self.load_document(collection, doc_name))
            except (FileNotFoundError, ValueError) as exc:
                # One unreadable index must not take the folder down with it:
                # the other documents can still answer the question, and the
                # library screen already reports this one as broken.
                logger.warning(
                    "skipping %s in folder %s: %s", doc_name, collection, exc
                )
        return loaded

    def _stamp(self, collection: str, doc_name: str) -> float:
        """
        Modification time of the index, so a rebuild invalidates the cache.

        Without it, re-indexing a document mid-session would keep answering
        questions from the embeddings it replaced.
        """
        metadata = self._store.vector_store(collection).index_dir(doc_name) / "metadata.json"
        try:
            return metadata.stat().st_mtime
        except OSError:
            return 0.0

    def _invalidate(self, collection: str, doc_name: str) -> None:
        for key in [k for k in self._cache if k[0] == collection and k[1] == doc_name]:
            self._cache.pop(key, None)
