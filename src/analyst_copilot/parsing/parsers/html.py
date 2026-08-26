"""HTML → Markdown, one segment per page break.

HTML has no pages. What SEC filers ship is a paginated document rendered to
HTML, with the original page boundaries surviving as explicit CSS page-break
markers -- so the boundaries here are recovered, not invented, and a filing with
no markers at all falls back to fixed-size chunks rather than pretending.

The upgrade over plain text extraction is tables. A filing's answer is usually a
line item in a financial statement, and flattening `Purchases of PP&E (1,577)
(1,373) (1,420)` into prose loses which figure belongs to which year. Data
tables are rendered as Markdown tables; the layout tables SEC filers nest around
everything are unwrapped instead, since rendering those would bury the page in
pipes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from bs4 import BeautifulSoup, NavigableString, Tag

from analyst_copilot.parsing.base import DocumentParser, ParsedSegment
from analyst_copilot.parsing.formats import DocumentFormat
from analyst_copilot.parsing.markdown import normalize_text, render_table
from analyst_copilot.parsing.models import SegmentKind

# SEC filers mark page boundaries inconsistently, and every variant missed here
# sends a whole filing down the chunking fallback, which destroys its page
# numbering. Observed across the 79-filing corpus:
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

# Fallback when a document carries no page-break markers at all.
FALLBACK_CHARS_PER_PAGE = 3500

# Tags whose end implies a line break in the rendered document.
_BLOCK_TAGS = (
    "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote",
)
_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

# A table narrower than this is a layout wrapper or a single-column list, not
# data worth the pipes.
_MIN_TABLE_COLUMNS = 2
# Bound on the innermost-outward table passes, so malformed markup cannot loop.
_MAX_TABLE_PASSES = 8


class HtmlParser(DocumentParser):
    """One Markdown segment per page break, with financial tables preserved."""

    format = DocumentFormat.HTML
    segmentation = "page-break"

    def segments(self, path: Path) -> List[ParsedSegment]:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        html = _extract_html_body(raw)
        parts = PAGE_BREAK_PATTERN.split(html)

        if len(parts) == 1 and not PAGE_BREAK_PATTERN.search(html):
            self.segmentation = "fallback-chunk"
            return _fallback_segments(html)

        self.segmentation = "page-break"
        return [
            ParsedSegment(
                markdown=fragment_to_markdown(fragment),
                kind=SegmentKind.PAGE,
                label=f"page {number}",
                printed_page=None,
            )
            for number, fragment in enumerate(parts, start=1)
        ]

    def parse(self, path, doc_name: Optional[str] = None):
        document = super().parse(path, doc_name=doc_name)
        # Printed footers are detected from the rendered Markdown rather than
        # the HTML, so the number picked up is the one a reader would see.
        for page in document.pages:
            page.printed_page = detect_printed_page_number(page.text)
            if page.segment_kind is not SegmentKind.PAGE:
                continue
            page.segment_label = f"page {page.display_page}"
        document.segmentation = self.segmentation
        return document


def _extract_html_body(raw: str) -> str:
    """Return inner HTML from the SEC <TEXT> wrapper, or the full content."""
    match = SEC_TEXT_PATTERN.search(raw)
    return match.group(1) if match else raw


def fragment_to_markdown(html_fragment: str) -> str:
    """Convert one page's HTML into Markdown."""
    soup = BeautifulSoup(html_fragment, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    _render_tables(soup)
    _mark_line_breaks(soup)
    _mark_headings(soup)

    text = soup.get_text()
    return normalize_text(text)


def _render_tables(soup: BeautifulSoup) -> None:
    """
    Replace data tables with Markdown, innermost first.

    SEC filers nest tables for layout, so an outer table's rows are a mix of its
    own cells and every inner table's. Working innermost-outward means each
    table is rendered against only its own rows, and the layout wrappers left
    behind have a single column and are unwrapped rather than rendered.
    """
    for _ in range(_MAX_TABLE_PASSES):
        innermost = [t for t in soup.find_all("table") if not t.find("table")]
        if not innermost:
            return
        for table in innermost:
            rendered = _table_to_markdown(table)
            if rendered:
                table.replace_with(NavigableString(f"\n\n{rendered}\n\n"))
            else:
                table.unwrap()


def _table_to_markdown(table: Tag) -> str:
    rows: List[List[str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        rows.append([cell.get_text(separator=" ", strip=True) for cell in cells])

    populated = [row for row in rows if any(cell for cell in row)]
    if len(populated) < 2:
        return ""
    if max(len(row) for row in populated) < _MIN_TABLE_COLUMNS:
        return ""
    return render_table(populated)


def _mark_line_breaks(soup: BeautifulSoup) -> None:
    for tag in soup.find_all("br"):
        tag.replace_with(NavigableString("\n"))
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append(NavigableString("\n"))


def _mark_headings(soup: BeautifulSoup) -> None:
    for name, level in _HEADING_LEVELS.items():
        for tag in soup.find_all(name):
            text = tag.get_text(separator=" ", strip=True)
            if text:
                tag.replace_with(NavigableString(f"\n\n{'#' * level} {text}\n\n"))


def detect_printed_page_number(text: str) -> Optional[int]:
    """
    Many filings print a page number at the bottom of each page.

    Returns that number when the trailing token looks like a page footer. It is
    reference-only -- see `Page.citation_page` for why it is not cited.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return None
    match = PRINTED_PAGE_PATTERN.search(cleaned)
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 2000 else None


def _fallback_segments(html: str) -> List[ParsedSegment]:
    """
    Fixed-size chunks for a document with no page-break markers at all.

    These are labelled `section`, not `page`: the boundaries are ours, and
    calling them pages would put a number on a citation that corresponds to
    nothing in the source document.
    """
    text = fragment_to_markdown(html)
    if not text:
        return []
    segments: List[ParsedSegment] = []
    for number, start in enumerate(range(0, len(text), FALLBACK_CHARS_PER_PAGE), start=1):
        segments.append(
            ParsedSegment(
                markdown=text[start : start + FALLBACK_CHARS_PER_PAGE],
                kind=SegmentKind.SECTION,
                label=f"part {number}",
            )
        )
    return segments
