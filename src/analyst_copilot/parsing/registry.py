"""One entry point for parsing any supported document.

Everything upstream of this module -- the API, the bulk indexer, the QA service
-- knows only `parse_document(path)`. Adding a format is registering a parser
here; no caller changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional, Union

from analyst_copilot.parsing.base import DocumentParser, ParseError
from analyst_copilot.parsing.formats import (
    SUPPORTED_SUFFIXES,
    DocumentFormat,
    UnsupportedFormat,
    detect_format,
)
from analyst_copilot.parsing.models import FilingDocument
from analyst_copilot.parsing.parsers import (
    CsvParser,
    DocxParser,
    ExcelParser,
    HtmlParser,
    PdfParser,
    PlainTextParser,
)

# Parsers are built per call rather than shared: several of them record how they
# segmented the document they just read, so a shared instance would report the
# previous document's segmentation to a concurrent caller.
_FACTORIES: Dict[DocumentFormat, Callable[[], DocumentParser]] = {
    DocumentFormat.PDF: PdfParser,
    DocumentFormat.HTML: HtmlParser,
    DocumentFormat.DOCX: DocxParser,
    DocumentFormat.XLSX: ExcelParser,
    DocumentFormat.CSV: CsvParser,
    DocumentFormat.MARKDOWN: lambda: PlainTextParser(DocumentFormat.MARKDOWN),
    DocumentFormat.TEXT: lambda: PlainTextParser(DocumentFormat.TEXT),
}

__all__ = [
    "SUPPORTED_SUFFIXES",
    "DocumentFormat",
    "ParseError",
    "UnsupportedFormat",
    "detect_format",
    "get_parser",
    "parse_document",
    "supported_formats",
]


def supported_formats() -> tuple:
    return tuple(_FACTORIES)


def get_parser(document_format: DocumentFormat) -> DocumentParser:
    """The parser for a format, or `UnsupportedFormat` if none is registered."""
    factory = _FACTORIES.get(document_format)
    if factory is None:
        raise UnsupportedFormat(f"No parser registered for {document_format.value!r}.")
    return factory()


def parse_document(
    path: Union[Path, str],
    doc_name: Optional[str] = None,
    document_format: Optional[DocumentFormat] = None,
) -> FilingDocument:
    """
    Parse any supported document into Markdown segments.

    Pass `document_format` only to override detection -- for a file whose
    extension lies and whose contents cannot be sniffed.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"No such document: {file_path}")

    resolved = document_format or detect_format(file_path)
    return get_parser(resolved).parse(file_path, doc_name=doc_name)
