"""Persist and load vector indices to disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from analyst_copilot.config.settings import get_settings
from analyst_copilot.parsing.html_filing_parser import PARSER_VERSION
from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.models import VectorIndexMetadata
from analyst_copilot.retrieval.vector.index import VectorIndex

_METADATA_FILE = "metadata.json"
_VECTORS_FILE = "vectors.npz"
_PAGES_FILE = "pages.json"


class VectorIndexStore:
    """File-based storage for dense vector indices."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        settings = get_settings()
        root = base_dir or settings.storage_dir / "vector_indices"
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def index_dir(self, doc_name: str) -> Path:
        return self._root / doc_name

    def save(self, index: VectorIndex) -> Path:
        target_dir = self.index_dir(index.doc_name)
        target_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = target_dir / _METADATA_FILE
        vectors_path = target_dir / _VECTORS_FILE
        pages_path = target_dir / _PAGES_FILE

        metadata_path.write_text(
            json.dumps(self._metadata_to_dict(index.metadata), indent=2),
            encoding="utf-8",
        )
        np.savez_compressed(
            vectors_path,
            vectors=np.asarray(index.vectors, dtype=np.float32),
        )
        pages_path.write_text(
            json.dumps(self._pages_to_dict(index.pages), indent=2),
            encoding="utf-8",
        )

        return target_dir

    def load(self, doc_name: str) -> VectorIndex:
        target_dir = self.index_dir(doc_name)
        metadata_path = target_dir / _METADATA_FILE
        vectors_path = target_dir / _VECTORS_FILE
        pages_path = target_dir / _PAGES_FILE

        if not all(path.exists() for path in (metadata_path, vectors_path, pages_path)):
            raise FileNotFoundError(f"Vector index not found for document: {doc_name}")

        metadata = self._metadata_from_dict(
            json.loads(metadata_path.read_text(encoding="utf-8"))
        )
        pages = self._pages_from_dict(
            json.loads(pages_path.read_text(encoding="utf-8")),
            doc_name=metadata.doc_name,
        )
        vectors_array = np.load(vectors_path)["vectors"]
        vectors: List[List[float]] = vectors_array.tolist()

        if len(pages) != len(vectors):
            raise ValueError("Vector index page count does not match embedding count")

        return VectorIndex(metadata=metadata, pages=pages, vectors=vectors)

    def load_pages(self, doc_name: str) -> Optional[List[Page]]:
        """
        Read a filing's page text without loading its vectors.

        `pages.json` holds the full page text -- only the copy sent to the
        embedding API was truncated -- so this is the cheapest way to show a
        reader what is actually on a page.
        """
        pages_path = self.index_dir(doc_name) / _PAGES_FILE
        if not pages_path.exists():
            return None
        try:
            payload = json.loads(pages_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return self._pages_from_dict(payload, doc_name)

    def load_metadata(self, doc_name: str) -> Optional[VectorIndexMetadata]:
        """
        Read an index's metadata without loading its vectors.

        A library view needs the model and page count for every filing at once;
        `load` would decompress the whole embedding array to get them.
        """
        payload = self._read_metadata(doc_name)
        if payload is None:
            return None
        try:
            return self._metadata_from_dict(payload)
        except KeyError:
            return None

    def is_stale(self, doc_name: str) -> bool:
        """
        Index files are present but cannot be searched as configured.

        Distinct from absent: the vectors exist, they were just built by a
        different parser, a different embedding model, or at a different
        truncation cap. A UI should offer to rebuild rather than to add.
        """
        return self._read_metadata(doc_name) is not None and not self.exists(doc_name)

    def _read_metadata(self, doc_name: str) -> Optional[Dict[str, Any]]:
        """Parsed metadata when every index file is present, else None."""
        target_dir = self.index_dir(doc_name)
        if not all(
            (target_dir / name).exists()
            for name in (_METADATA_FILE, _VECTORS_FILE, _PAGES_FILE)
        ):
            return None
        try:
            return json.loads((target_dir / _METADATA_FILE).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def exists(self, doc_name: str) -> bool:
        """
        True only when a usable index is on disk.

        An index whose embeddings were built by an older parser, or by a
        different embedding model, is reported as absent so callers rebuild
        rather than search stale page boundaries.
        """
        payload = self._read_metadata(doc_name)
        if payload is None:
            return False
        if payload.get("parser_version") != PARSER_VERSION:
            return False
        settings = get_settings()
        if payload.get("embedding_model") != settings.resolved_embedding_model:
            return False
        # The truncation cap decides how much of each page was embedded, so
        # changing it changes the vectors. Without this check, widening the
        # evidence window would silently reuse embeddings of the old, shorter
        # text and the change would appear to have no effect.
        return payload.get("max_chars_per_page") == settings.retrieval_max_chars_per_page

    @staticmethod
    def _metadata_to_dict(metadata: VectorIndexMetadata) -> Dict[str, Any]:
        return {
            "doc_name": metadata.doc_name,
            "source_path": metadata.source_path,
            "page_count": metadata.page_count,
            "embedding_model": metadata.embedding_model,
            "dimensions": metadata.dimensions,
            "max_chars_per_page": metadata.max_chars_per_page,
            "parser_version": metadata.parser_version,
        }

    @staticmethod
    def _metadata_from_dict(payload: Dict[str, Any]) -> VectorIndexMetadata:
        return VectorIndexMetadata(
            doc_name=payload["doc_name"],
            source_path=payload["source_path"],
            page_count=payload["page_count"],
            embedding_model=payload["embedding_model"],
            dimensions=payload["dimensions"],
            max_chars_per_page=payload["max_chars_per_page"],
            parser_version=payload.get("parser_version", "unknown"),
        )

    @staticmethod
    def _pages_to_dict(pages: List[Page]) -> List[Dict[str, Any]]:
        return [
            {
                "page_index": page.page_index,
                "printed_page": page.printed_page,
                "text": page.text,
            }
            for page in pages
        ]

    @staticmethod
    def _pages_from_dict(payload: List[Dict[str, Any]], doc_name: str) -> List[Page]:
        return [
            Page(
                doc_name=doc_name,
                page_index=item["page_index"],
                text=item["text"],
                printed_page=item.get("printed_page"),
            )
            for item in payload
        ]
