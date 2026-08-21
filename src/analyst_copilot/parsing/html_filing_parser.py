"""Parse SEC EDGAR HTML filings into page-aligned plain text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Union

from bs4 import BeautifulSoup

from analyst_copilot.parsing.models import FilingDocument, Page

# SEC filers mark page boundaries inconsistently, and every variant missed here
# sends a whole filing down the character-chunking fallback, which destroys its
# page numbering. Observed across the 79-filing corpus:
#
#   <hr>  page-break-after   74 filings
#   <p>   page-break-after    1 filing  (3M_2018_10K)
#   <hr>  page-break-before   2 filings (GENERALMILLS_2019_10K, MICROSOFT_2016_10K)
#
# `before` and `after` both mark the same boundary, so splitting on either
# yields the same pages. The CSS4 `break-*` spelling is accepted too.
PAGE_BREAK_PATTERN = re.compile(
    r"<(?:p|hr|div)[^>]*(?:page-)?break-(?:after|before)\s*:\s*always[^>]*>",
    re.IGNORECASE,
)
SEC_TEXT_PATTERN = re.compile(r"<TEXT>(.*)</TEXT>", re.DOTALL | re.IGNORECASE)
PRINTED_PAGE_PATTERN = re.compile(r"\b(\d{1,4})\s*$")

# Bump when a parsing change alters page boundaries or numbering. Persisted
# indices record this and are treated as absent when it no longer matches, so a
# parser fix can never be masked by stale embeddings on disk.
PARSER_VERSION = "3"

# Fallback when a filing carries no page-break markers at all.
FALLBACK_CHARS_PER_PAGE = 3500


def _extract_html_body(raw: str) -> str:
    """Return inner HTML from SEC <TEXT> wrapper, or full content."""
    match = SEC_TEXT_PATTERN.search(raw)
    return match.group(1) if match else raw


def _html_to_text(html_fragment: str) -> str:
    """Convert an HTML fragment to normalized plain text."""
    soup = BeautifulSoup(html_fragment, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _detect_printed_page_number(text: str) -> Optional[int]:
    """
    Many SEC filings print a page number at the bottom of each page.
    Returns that number when the trailing token looks like a page footer.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return None
    match = PRINTED_PAGE_PATTERN.search(cleaned)
    if not match:
        return None
    value = int(match.group(1))
    if 1 <= value <= 2000:
        return value
    return None


def _split_html_pages(html: str) -> List[str]:
    """Split HTML on explicit page-break markers used in many 10-K/10-Q filings."""
    parts = PAGE_BREAK_PATTERN.split(html)
    if len(parts) > 1:
        return parts
    return [html]


def _fallback_pages(html: str) -> List[str]:
    """Character-based fallback for filings without page-break markers."""
    text = _html_to_text(html)
    if not text:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + FALLBACK_CHARS_PER_PAGE])
        start += FALLBACK_CHARS_PER_PAGE
    return chunks


def parse_filing_html(path: Union[Path, str], doc_name: Optional[str] = None) -> FilingDocument:
    """
    Parse a filing HTML file into pages with preserved page metadata.

    Strategy:
    1. Extract SEC <TEXT> block when present.
    2. Split on `page-break-{after,before}: always` on <hr>/<p>/<div>.
    3. Extract printed footer page numbers where possible (reference only —
       see Page.citation_page for why they are not used for citations).
    4. Fall back to fixed-size text chunks when no page breaks exist.
    """
    file_path = Path(path)
    if doc_name is None:
        doc_name = file_path.stem

    raw = file_path.read_text(encoding="utf-8", errors="ignore")
    html = _extract_html_body(raw)
    html_parts = _split_html_pages(html)

    pages: List[Page] = []

    if len(html_parts) == 1 and not PAGE_BREAK_PATTERN.search(html):
        text_chunks = _fallback_pages(html)
        for index, text in enumerate(text_chunks):
            if not text.strip():
                continue
            pages.append(
                Page(
                    doc_name=doc_name,
                    page_index=index,
                    text=text,
                    printed_page=_detect_printed_page_number(text),
                )
            )
    else:
        for index, fragment in enumerate(html_parts):
            text = _html_to_text(fragment)
            if not text.strip():
                continue
            pages.append(
                Page(
                    doc_name=doc_name,
                    page_index=index,
                    text=text,
                    printed_page=_detect_printed_page_number(text),
                )
            )

    return FilingDocument(
        doc_name=doc_name,
        source_path=str(file_path.resolve()),
        pages=pages,
    )
