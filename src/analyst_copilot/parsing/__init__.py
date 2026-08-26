"""Document parsing: any supported format in, Markdown segments out."""

from analyst_copilot.parsing.base import DocumentParser, ParseError, ParsedSegment
from analyst_copilot.parsing.formats import (
    SUPPORTED_SUFFIXES,
    DocumentFormat,
    UnsupportedFormat,
    detect_format,
)
from analyst_copilot.parsing.html_filing_parser import parse_filing_html
from analyst_copilot.parsing.markdown_store import MarkdownManifest, MarkdownPageStore
from analyst_copilot.parsing.models import FilingDocument, Page, SegmentKind
from analyst_copilot.parsing.registry import get_parser, parse_document, supported_formats
from analyst_copilot.parsing.version import PARSER_VERSION

__all__ = [
    "PARSER_VERSION",
    "SUPPORTED_SUFFIXES",
    "DocumentFormat",
    "DocumentParser",
    "FilingDocument",
    "MarkdownManifest",
    "MarkdownPageStore",
    "Page",
    "ParseError",
    "ParsedSegment",
    "SegmentKind",
    "UnsupportedFormat",
    "detect_format",
    "get_parser",
    "parse_document",
    "parse_filing_html",
    "supported_formats",
]
