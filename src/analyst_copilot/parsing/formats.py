"""Which formats the system accepts, and how a file is recognised as one."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple, Union


class DocumentFormat(str, Enum):
    """A source format the pipeline knows how to normalize to Markdown."""

    PDF = "pdf"
    HTML = "html"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    MARKDOWN = "markdown"
    TEXT = "text"

    @property
    def is_paginated(self) -> bool:
        """
        Whether the format carries page boundaries worth preserving.

        Spreadsheets and delimited data have no pages, and inventing some would
        put a page number on a citation that the analyst cannot check against
        the original. Those formats are segmented by sheet or row block instead.
        """
        return self in (DocumentFormat.PDF, DocumentFormat.HTML, DocumentFormat.DOCX)


_BY_SUFFIX: Dict[str, DocumentFormat] = {
    ".pdf": DocumentFormat.PDF,
    ".htm": DocumentFormat.HTML,
    ".html": DocumentFormat.HTML,
    ".xhtml": DocumentFormat.HTML,
    ".docx": DocumentFormat.DOCX,
    ".xlsx": DocumentFormat.XLSX,
    ".xlsm": DocumentFormat.XLSX,
    ".csv": DocumentFormat.CSV,
    ".tsv": DocumentFormat.CSV,
    ".md": DocumentFormat.MARKDOWN,
    ".markdown": DocumentFormat.MARKDOWN,
    ".txt": DocumentFormat.TEXT,
    ".text": DocumentFormat.TEXT,
}

SUPPORTED_SUFFIXES: Tuple[str, ...] = tuple(sorted(_BY_SUFFIX))

# Enough bytes to see any of the magic numbers below.
_SNIFF_BYTES = 2048

# Formats whose container is unambiguous on disk. `.docx`/`.xlsx` are both ZIP
# archives, so magic alone cannot separate them -- the suffix decides between
# those two and sniffing only has to catch a mislabelled PDF or HTML file.
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"


class UnsupportedFormat(ValueError):
    """The file's extension and contents match no parser."""


def format_of_suffix(suffix: str) -> Optional[DocumentFormat]:
    return _BY_SUFFIX.get(suffix.lower())


def detect_format(path: Union[Path, str]) -> DocumentFormat:
    """
    Identify a document's format from its extension, checked against its bytes.

    The extension is the primary signal because it is the only thing that can
    distinguish the two ZIP-based Office formats. Content sniffing exists to
    catch the common upload mistake -- a PDF or an HTML page saved under the
    wrong name -- rather than to second-guess a correct extension.
    """
    file_path = Path(path)
    by_suffix = format_of_suffix(file_path.suffix)
    sniffed = _sniff(file_path)

    if by_suffix is None:
        if sniffed is None:
            raise UnsupportedFormat(
                f"Cannot determine the format of {file_path.name!r}. "
                f"Supported extensions: {', '.join(SUPPORTED_SUFFIXES)}."
            )
        return sniffed

    # A PDF is never anything else, whatever it is called; and a file named
    # `.pdf` that carries no PDF header would only fail deeper in the stack.
    if sniffed is DocumentFormat.PDF or by_suffix is DocumentFormat.PDF:
        if sniffed is DocumentFormat.PDF:
            return DocumentFormat.PDF
        raise UnsupportedFormat(
            f"{file_path.name!r} is named as a PDF but does not start with %PDF-."
        )

    # HTML saved as .txt is common enough to be worth honouring; the reverse
    # (plain text named .html) parses to itself either way.
    if sniffed is DocumentFormat.HTML and by_suffix is DocumentFormat.TEXT:
        return DocumentFormat.HTML

    return by_suffix


def _sniff(path: Path) -> Optional[DocumentFormat]:
    try:
        with path.open("rb") as handle:
            head = handle.read(_SNIFF_BYTES)
    except OSError:
        return None

    if head.startswith(_PDF_MAGIC):
        return DocumentFormat.PDF
    if head.startswith(_ZIP_MAGIC):
        return None  # docx vs xlsx: only the suffix knows
    lowered = head.lstrip().lower()
    if lowered.startswith((b"<!doctype html", b"<html", b"<?xml", b"<sec-document")):
        return DocumentFormat.HTML
    return None
