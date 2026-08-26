"""Persist and load BM25 indices to disk."""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any, Dict, Optional

from analyst_copilot.config.settings import get_settings
from analyst_copilot.parsing.version import PARSER_VERSION
from analyst_copilot.retrieval.bm25.index import BM25Index
from analyst_copilot.retrieval.models import BM25IndexMetadata

_METADATA_FILE = "metadata.json"
_INDEX_FILE = "bm25_index.pkl"


class BM25IndexStore:
    """File-based storage for BM25 indices."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        settings = get_settings()
        root = base_dir or settings.storage_dir / "bm25_indices"
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def index_dir(self, doc_name: str) -> Path:
        return self._root / doc_name

    def save(self, index: BM25Index) -> Path:
        target_dir = self.index_dir(index.doc_name)
        target_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = target_dir / _METADATA_FILE
        index_path = target_dir / _INDEX_FILE

        metadata_path.write_text(
            json.dumps(self._metadata_to_dict(index.metadata), indent=2),
            encoding="utf-8",
        )
        index_path.write_bytes(pickle.dumps(index))

        return target_dir

    def load(self, doc_name: str) -> BM25Index:
        target_dir = self.index_dir(doc_name)
        metadata_path = target_dir / _METADATA_FILE
        index_path = target_dir / _INDEX_FILE

        if not metadata_path.exists() or not index_path.exists():
            raise FileNotFoundError(f"BM25 index not found for document: {doc_name}")

        metadata = self._metadata_from_dict(
            json.loads(metadata_path.read_text(encoding="utf-8"))
        )
        index = pickle.loads(index_path.read_bytes())

        if index.metadata.doc_name != metadata.doc_name:
            raise ValueError("BM25 index metadata does not match stored index payload")

        return index

    def load_metadata(self, doc_name: str) -> Optional[BM25IndexMetadata]:
        """
        Read an index's metadata without deserialising the index itself.

        A library view needs page counts and versions for every filing at once;
        `load` would unpickle each whole index to get them.
        """
        payload = self._read_metadata(doc_name)
        if payload is None:
            return None
        try:
            return self._metadata_from_dict(payload)
        except KeyError:
            return None

    def is_stale(self, doc_name: str) -> bool:
        """Index files are present but were built by a different parser version."""
        payload = self._read_metadata(doc_name)
        return payload is not None and payload.get("parser_version") != PARSER_VERSION

    def exists(self, doc_name: str) -> bool:
        """
        True only when a usable index is on disk.

        An index built by an older parser is reported as absent, so callers
        rebuild instead of searching stale page boundaries.
        """
        payload = self._read_metadata(doc_name)
        if payload is None:
            return False
        return payload.get("parser_version") == PARSER_VERSION

    def _read_metadata(self, doc_name: str) -> Optional[Dict[str, Any]]:
        """Parsed metadata when every index file is present, else None."""
        target_dir = self.index_dir(doc_name)
        metadata_path = target_dir / _METADATA_FILE
        if not metadata_path.exists() or not (target_dir / _INDEX_FILE).exists():
            return None
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _metadata_to_dict(metadata: BM25IndexMetadata) -> Dict[str, Any]:
        return {
            "doc_name": metadata.doc_name,
            "source_path": metadata.source_path,
            "page_count": metadata.page_count,
            "tokenizer_version": metadata.tokenizer_version,
            "parser_version": metadata.parser_version,
        }

    @staticmethod
    def _metadata_from_dict(payload: Dict[str, Any]) -> BM25IndexMetadata:
        return BM25IndexMetadata(
            doc_name=payload["doc_name"],
            source_path=payload["source_path"],
            page_count=payload["page_count"],
            tokenizer_version=payload.get("tokenizer_version", "v1"),
            parser_version=payload.get("parser_version", "unknown"),
        )
