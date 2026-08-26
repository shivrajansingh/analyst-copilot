"""Domain models for document collections."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analyst_copilot.parsing.formats import DocumentFormat

# A collection name becomes a directory under both `filings/` and `storage/`,
# and is echoed in citations, so it is restricted to characters that are safe
# in a path and readable in an answer.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_MAX_NAME_LENGTH = 80

# Reserved because the per-document layout already owns these names directly
# under `storage/`, and a collection called `markdown` would collide with it.
RESERVED_NAMES = frozenset({"markdown", "bm25_indices", "vector_indices", "collections"})


class InvalidCollectionName(ValueError):
    """The requested collection name cannot be used as a directory."""


def sanitize_collection_name(name: Optional[str]) -> str:
    """
    Derive a storage-safe collection name from user input.

    Path separators are stripped rather than escaped, so a name of
    `../../etc` cannot walk out of the storage root.
    """
    if not name or not name.strip():
        raise InvalidCollectionName("A folder name is required.")

    cleaned = _SAFE_NAME.sub(" ", name).strip(" ._-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise InvalidCollectionName(f"Folder name {name!r} has no usable characters.")
    if cleaned.lower() in RESERVED_NAMES:
        raise InvalidCollectionName(f"{cleaned!r} is reserved. Choose another name.")
    return cleaned[:_MAX_NAME_LENGTH]


@dataclass
class CollectionDocument:
    """One document inside a collection, and how it got there."""

    doc_name: str
    source_file: str          # filename as stored, with its real extension
    source_format: Optional[DocumentFormat] = None
    segment_count: Optional[int] = None
    added_at: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "doc_name": self.doc_name,
            "source_file": self.source_file,
            "source_format": self.source_format.value if self.source_format else None,
            "segment_count": self.segment_count,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "CollectionDocument":
        raw_format = payload.get("source_format")
        return cls(
            doc_name=str(payload["doc_name"]),
            source_file=str(payload.get("source_file", "")),
            source_format=DocumentFormat(str(raw_format)) if raw_format else None,
            segment_count=payload.get("segment_count"),  # type: ignore[arg-type]
            added_at=float(payload.get("added_at", 0.0)),
        )


@dataclass
class Collection:
    """
    A named folder of documents that are searched together.

    The unit an analyst works with is a question, and a question is rarely
    about one file: "how did margin move over three years" spans three annual
    reports. A collection is that grouping made explicit, so retrieval can span
    the documents while every citation still names exactly one of them.
    """

    name: str
    created_at: float = 0.0
    updated_at: float = 0.0
    description: str = ""
    documents: List[CollectionDocument] = field(default_factory=list)

    @property
    def document_names(self) -> List[str]:
        return [document.doc_name for document in self.documents]

    def find(self, doc_name: str) -> Optional[CollectionDocument]:
        return next((d for d in self.documents if d.doc_name == doc_name), None)

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "description": self.description,
            "documents": [document.to_dict() for document in self.documents],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "Collection":
        return cls(
            name=str(payload["name"]),
            created_at=float(payload.get("created_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
            description=str(payload.get("description", "")),
            documents=[
                CollectionDocument.from_dict(item)
                for item in payload.get("documents", [])  # type: ignore[union-attr]
            ],
        )
