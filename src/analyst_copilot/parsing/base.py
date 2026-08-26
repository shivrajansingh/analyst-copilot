"""The contract every format parser implements."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from analyst_copilot.parsing.formats import DocumentFormat
from analyst_copilot.parsing.models import FilingDocument, Page, SegmentKind


class ParseError(RuntimeError):
    """A document matched a parser but could not be read."""


@dataclass
class ParsedSegment:
    """
    One segment produced by a format parser, before it becomes a `Page`.

    Parsers deal only in content and labels; the ordinal, the document name and
    the format stamp are applied centrally so no parser can number its own
    segments differently from the rest.
    """

    markdown: str
    kind: SegmentKind = SegmentKind.PAGE
    label: Optional[str] = None
    printed_page: Optional[int] = None


class DocumentParser(abc.ABC):
    """
    Converts one source format into ordered Markdown segments.

    A parser has exactly two jobs: find the boundaries the source genuinely
    has, and render what falls between them as Markdown. It never decides how
    segments are numbered, stored, chunked or embedded.
    """

    #: The format this parser claims.
    format: DocumentFormat
    #: How this parser finds boundaries, recorded on the document.
    segmentation: str = "unknown"

    @abc.abstractmethod
    def segments(self, path: Path) -> List[ParsedSegment]:
        """Read the file and return its segments in document order."""

    def parse(self, path: Union[Path, str], doc_name: Optional[str] = None) -> FilingDocument:
        """Read a file into a `FilingDocument` of Markdown segments."""
        file_path = Path(path)
        if doc_name is None:
            doc_name = file_path.stem

        try:
            raw_segments = self.segments(file_path)
        except ParseError:
            raise
        except Exception as exc:  # noqa: BLE001 - every library raises its own
            raise ParseError(
                f"Could not parse {file_path.name!r} as {self.format.value}: {exc}"
            ) from exc

        pages: List[Page] = []
        for index, segment in enumerate(raw_segments):
            if not segment.markdown.strip():
                continue
            pages.append(
                Page(
                    doc_name=doc_name,
                    # The ordinal counts segments the source declared, including
                    # any that rendered empty, so dropping a blank page here does
                    # not silently renumber every page after it.
                    page_index=index,
                    text=segment.markdown,
                    printed_page=segment.printed_page,
                    segment_kind=segment.kind,
                    segment_label=segment.label,
                    source_format=self.format,
                )
            )

        return FilingDocument(
            doc_name=doc_name,
            source_path=str(file_path.resolve()),
            pages=pages,
            source_format=self.format,
            segmentation=self.segmentation,
        )
