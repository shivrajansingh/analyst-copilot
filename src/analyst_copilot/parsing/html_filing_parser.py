"""Backwards-compatible entry point for HTML filing parsing.

The HTML reader now lives in `parsing.parsers.html`, alongside the parsers for
the other formats, and `parsing.registry.parse_document` dispatches to it. This
module stays because scripts, tests and docs reference `parse_filing_html` by
name, and because an HTML-only caller should not have to know about the
registry.

New code should call `analyst_copilot.parsing.parse_document`, which accepts any
supported format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from analyst_copilot.parsing.models import FilingDocument
from analyst_copilot.parsing.parsers.html import (
    FALLBACK_CHARS_PER_PAGE,
    _extract_html_body,
    PAGE_BREAK_PATTERN,
    PRINTED_PAGE_PATTERN,
    SEC_TEXT_PATTERN,
    HtmlParser,
    detect_printed_page_number,
)
from analyst_copilot.parsing.version import PARSER_VERSION

__all__ = [
    "FALLBACK_CHARS_PER_PAGE",
    "PAGE_BREAK_PATTERN",
    "PARSER_VERSION",
    "PRINTED_PAGE_PATTERN",
    "SEC_TEXT_PATTERN",
    "parse_filing_html",
]


def parse_filing_html(
    path: Union[Path, str],
    doc_name: Optional[str] = None,
) -> FilingDocument:
    """Parse an HTML filing into Markdown segments, one per page break."""
    return HtmlParser().parse(path, doc_name=doc_name)


# Kept under their original private names for the tests that exercise them.
_detect_printed_page_number = detect_printed_page_number
__all__.append("_extract_html_body")
