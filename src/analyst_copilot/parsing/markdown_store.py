"""Page-level Markdown on disk: one file per segment, plus a manifest.

Why the Markdown is written out at all, when the indices already carry the text:

- It is the artifact a human can check. When a citation looks wrong, the
  question is always "what did the system actually read on that page", and the
  answer should be a file you can open, not a field inside a pickle.
- It decouples parsing from embedding. Re-chunking, re-weighting or re-embedding
  can all replay from the Markdown without re-parsing a 200-page PDF.
- It is the contract between formats. A CSV and a 10-K look identical here, so
  everything downstream can be written once.

Layout:

    storage/markdown/{doc_name}/
        manifest.json
        page-001.md      (paginated sources)
        sheet-001.md     (worksheets)
        part-001.md      (row blocks, headings, chunks)
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from analyst_copilot.config.settings import get_settings
from analyst_copilot.parsing.formats import DocumentFormat
from analyst_copilot.parsing.models import FilingDocument, Page, SegmentKind
from analyst_copilot.parsing.version import PARSER_VERSION

_MANIFEST_FILE = "manifest.json"

# The filename says what the segment is, so a directory listing distinguishes a
# real page from a block we cut ourselves without opening anything.
_FILE_PREFIX: Dict[SegmentKind, str] = {
    SegmentKind.PAGE: "page",
    SegmentKind.SHEET: "sheet",
    SegmentKind.TABLE: "table",
    SegmentKind.SECTION: "part",
}


@dataclass
class MarkdownManifest:
    """What was parsed, how it was segmented, and where each segment lives."""

    doc_name: str
    source_path: str
    source_format: DocumentFormat
    segmentation: str
    parser_version: str
    segment_count: int
    created_at: float
    segments: List[Dict[str, object]]

    @property
    def is_current(self) -> bool:
        return self.parser_version == PARSER_VERSION


class MarkdownPageStore:
    """Write and read the per-segment Markdown for a document."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        root = base_dir or get_settings().storage_dir / "markdown"
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def document_dir(self, doc_name: str) -> Path:
        return self._root / doc_name

    def save(self, document: FilingDocument) -> Path:
        """
        Write every segment, replacing whatever was there before.

        The directory is cleared first so a document that re-parses to fewer
        segments cannot leave the tail of its previous parse on disk, where a
        reader would take the stale files for current pages.
        """
        target = self.document_dir(document.doc_name)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

        entries: List[Dict[str, object]] = []
        for ordinal, page in enumerate(document.pages, start=1):
            filename = self.filename_for(page, ordinal)
            (target / filename).write_text(page.text, encoding="utf-8")
            entries.append(
                {
                    "file": filename,
                    "page_index": page.page_index,
                    "kind": page.segment_kind.value,
                    "label": page.citation_label,
                    "printed_page": page.printed_page,
                    "char_count": len(page.text),
                }
            )

        manifest = MarkdownManifest(
            doc_name=document.doc_name,
            source_path=document.source_path,
            source_format=document.source_format,
            segmentation=document.segmentation,
            parser_version=PARSER_VERSION,
            segment_count=len(entries),
            created_at=time.time(),
            segments=entries,
        )
        (target / _MANIFEST_FILE).write_text(
            json.dumps(_manifest_to_dict(manifest), indent=2), encoding="utf-8"
        )
        return target

    @staticmethod
    def filename_for(page: Page, ordinal: int) -> str:
        prefix = _FILE_PREFIX.get(page.segment_kind, "part")
        return f"{prefix}-{ordinal:03d}.md"

    def load_manifest(self, doc_name: str) -> Optional[MarkdownManifest]:
        path = self.document_dir(doc_name) / _MANIFEST_FILE
        if not path.exists():
            return None
        try:
            return _manifest_from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None

    def exists(self, doc_name: str) -> bool:
        manifest = self.load_manifest(doc_name)
        return manifest is not None and manifest.is_current

    def load_pages(self, doc_name: str) -> Optional[List[Page]]:
        """Rebuild the parsed segments from disk, without re-reading the source."""
        manifest = self.load_manifest(doc_name)
        if manifest is None:
            return None
        directory = self.document_dir(doc_name)
        pages: List[Page] = []
        for entry in manifest.segments:
            path = directory / str(entry["file"])
            if not path.exists():
                return None
            pages.append(
                Page(
                    doc_name=doc_name,
                    page_index=int(entry["page_index"]),
                    text=path.read_text(encoding="utf-8"),
                    printed_page=entry.get("printed_page"),
                    segment_kind=SegmentKind(str(entry.get("kind", "page"))),
                    segment_label=entry.get("label"),
                    source_format=manifest.source_format,
                )
            )
        return pages

    def load_markdown(self, doc_name: str, page_index: int) -> Optional[str]:
        """One segment's Markdown, addressed the way a citation addresses it."""
        manifest = self.load_manifest(doc_name)
        if manifest is None:
            return None
        for entry in manifest.segments:
            if int(entry["page_index"]) == page_index:
                path = self.document_dir(doc_name) / str(entry["file"])
                return path.read_text(encoding="utf-8") if path.exists() else None
        return None

    def delete(self, doc_name: str) -> None:
        shutil.rmtree(self.document_dir(doc_name), ignore_errors=True)


def _manifest_to_dict(manifest: MarkdownManifest) -> Dict[str, object]:
    return {
        "doc_name": manifest.doc_name,
        "source_path": manifest.source_path,
        "source_format": manifest.source_format.value,
        "segmentation": manifest.segmentation,
        "parser_version": manifest.parser_version,
        "segment_count": manifest.segment_count,
        "created_at": manifest.created_at,
        "segments": manifest.segments,
    }


def _manifest_from_dict(payload: Dict[str, object]) -> MarkdownManifest:
    return MarkdownManifest(
        doc_name=str(payload["doc_name"]),
        source_path=str(payload.get("source_path", "")),
        source_format=DocumentFormat(str(payload.get("source_format", "html"))),
        segmentation=str(payload.get("segmentation", "unknown")),
        parser_version=str(payload.get("parser_version", "unknown")),
        segment_count=int(payload.get("segment_count", 0)),
        created_at=float(payload.get("created_at", 0.0)),
        segments=list(payload.get("segments", [])),  # type: ignore[arg-type]
    )
