"""Where a collection's files live, on both sides of the pipeline.

The folder an analyst creates is mirrored twice: once under `filings/` for the
uploaded originals, and once under `storage/` for everything derived from them.

    filings/{collection}/{doc}.pdf

    storage/collections/{collection}/
        collection.json
        markdown/{doc}/page-001.md
        bm25_indices/{doc}/...
        vector_indices/{doc}/...

Mirroring rather than flattening keeps two properties worth having: a
collection can be deleted, copied or inspected as one directory, and two
collections can hold documents of the same name without colliding -- which they
will, because `Q1` and `10-K` are what people call files.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import List, Optional

from analyst_copilot.collections.models import (
    Collection,
    CollectionDocument,
    InvalidCollectionName,
    sanitize_collection_name,
)
from analyst_copilot.config.settings import get_settings
from analyst_copilot.parsing.markdown_store import MarkdownPageStore
from analyst_copilot.retrieval.bm25.storage import BM25IndexStore
from analyst_copilot.retrieval.vector.storage import VectorIndexStore

_MANIFEST_FILE = "collection.json"


class CollectionNotFound(LookupError):
    """No collection of that name exists."""


class CollectionStore:
    """Create, list and delete collections, and hand out their scoped stores."""

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        filings_dir: Optional[Path] = None,
    ) -> None:
        settings = get_settings()
        self._root = Path(storage_dir or settings.storage_dir) / "collections"
        self._filings_root = Path(filings_dir or settings.filings_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    # -- layout ------------------------------------------------------------ #
    def collection_dir(self, name: str) -> Path:
        return self._root / name

    def uploads_dir(self, name: str) -> Path:
        """Where the collection's original files are kept."""
        return self._filings_root / name

    def markdown_store(self, name: str) -> MarkdownPageStore:
        return MarkdownPageStore(base_dir=self.collection_dir(name) / "markdown")

    def bm25_store(self, name: str) -> BM25IndexStore:
        return BM25IndexStore(base_dir=self.collection_dir(name) / "bm25_indices")

    def vector_store(self, name: str) -> VectorIndexStore:
        return VectorIndexStore(base_dir=self.collection_dir(name) / "vector_indices")

    # -- lifecycle ---------------------------------------------------------- #
    def create(self, name: str, description: str = "") -> Collection:
        """
        Create a collection, or return the existing one of that name.

        Creation is idempotent because the natural client is an upload form: a
        second file dropped into "Boeing 2022" must land in the folder the first
        one made, not fail because it is already there.
        """
        safe = sanitize_collection_name(name)
        existing = self.load(safe)
        if existing is not None:
            return existing

        now = time.time()
        collection = Collection(
            name=safe, created_at=now, updated_at=now, description=description
        )
        self.collection_dir(safe).mkdir(parents=True, exist_ok=True)
        self.uploads_dir(safe).mkdir(parents=True, exist_ok=True)
        self._write(collection)
        return collection

    def load(self, name: str) -> Optional[Collection]:
        path = self.collection_dir(name) / _MANIFEST_FILE
        if not path.exists():
            return None
        try:
            return Collection.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None

    def require(self, name: str) -> Collection:
        collection = self.load(name)
        if collection is None:
            raise CollectionNotFound(f"No folder named {name!r}.")
        return collection

    def exists(self, name: str) -> bool:
        return (self.collection_dir(name) / _MANIFEST_FILE).exists()

    def list_all(self) -> List[Collection]:
        if not self._root.is_dir():
            return []
        found = [
            self.load(path.name)
            for path in sorted(self._root.iterdir())
            if path.is_dir()
        ]
        return [collection for collection in found if collection is not None]

    def delete(self, name: str, remove_uploads: bool = False) -> None:
        """
        Remove a collection's derived data, and optionally its originals.

        Uploads are kept by default: indices are regenerable and the source
        files are not, so deleting both on one action is the kind of thing an
        analyst only discovers is irreversible afterwards.
        """
        shutil.rmtree(self.collection_dir(name), ignore_errors=True)
        if remove_uploads:
            shutil.rmtree(self.uploads_dir(name), ignore_errors=True)

    # -- membership --------------------------------------------------------- #
    def add_document(self, name: str, document: CollectionDocument) -> Collection:
        """Record a document as a member, replacing any earlier entry of that name."""
        collection = self.require(name)
        collection.documents = [
            existing
            for existing in collection.documents
            if existing.doc_name != document.doc_name
        ]
        if not document.added_at:
            document.added_at = time.time()
        collection.documents.append(document)
        collection.documents.sort(key=lambda item: item.doc_name.lower())
        collection.updated_at = time.time()
        self._write(collection)
        return collection

    def remove_document(self, name: str, doc_name: str) -> Collection:
        collection = self.require(name)
        member = collection.find(doc_name)
        collection.documents = [
            existing for existing in collection.documents if existing.doc_name != doc_name
        ]
        collection.updated_at = time.time()
        self._write(collection)

        self.markdown_store(name).delete(doc_name)
        for directory in (
            self.bm25_store(name).index_dir(doc_name),
            self.vector_store(name).index_dir(doc_name),
        ):
            shutil.rmtree(directory, ignore_errors=True)
        if member is not None and member.source_file:
            (self.uploads_dir(name) / member.source_file).unlink(missing_ok=True)
        return collection

    def source_path(self, name: str, doc_name: str) -> Path:
        """The original file for one member document."""
        collection = self.require(name)
        member = collection.find(doc_name)
        if member is None or not member.source_file:
            raise CollectionNotFound(f"{doc_name!r} is not in folder {name!r}.")
        return self.uploads_dir(name) / member.source_file

    def _write(self, collection: Collection) -> None:
        directory = self.collection_dir(collection.name)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / _MANIFEST_FILE).write_text(
            json.dumps(collection.to_dict(), indent=2), encoding="utf-8"
        )


__all__ = [
    "Collection",
    "CollectionDocument",
    "CollectionNotFound",
    "CollectionStore",
    "InvalidCollectionName",
    "sanitize_collection_name",
]
