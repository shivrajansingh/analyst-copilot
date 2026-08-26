"""Word (.docx) → Markdown.

Word does not store pages. Pagination is produced by the renderer from fonts,
margins and widow rules, and none of that is in the file -- so the only page
boundaries that genuinely exist are the ones an author inserted by hand.

The parser uses those where they exist and labels the result a page. Where they
do not, it falls back to headings and then to size, and labels the result a
section: a made-up page number would be a citation an analyst cannot check
against their own copy of the document.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from analyst_copilot.parsing.base import DocumentParser, ParsedSegment
from analyst_copilot.parsing.formats import DocumentFormat
from analyst_copilot.parsing.markdown import heading, join_blocks, normalize_text, render_table
from analyst_copilot.parsing.models import SegmentKind

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# Explicit breaks an author inserted: a hard page break inside a run, and the
# "page break before" paragraph property.
_PAGE_BREAK_XPATH = f".//{_W_NS}br[@{_W_NS}type='page']"
_BREAK_BEFORE_XPATH = f".//{_W_NS}pageBreakBefore"

_SPLIT_HEADING_LEVELS = (1, 2)
_FALLBACK_CHARS_PER_SECTION = 3500


class DocxParser(DocumentParser):
    """Markdown segments from a Word document, split on real breaks only."""

    format = DocumentFormat.DOCX
    segmentation = "unknown"

    def segments(self, path: Path) -> List[ParsedSegment]:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(str(path))
        body = document.element.body

        blocks: List[str] = []
        boundaries: List[int] = []   # indices in `blocks` that start a new page
        heading_starts: List[int] = []

        for child in body.iterchildren():
            tag = child.tag
            if tag == f"{_W_NS}p":
                paragraph = Paragraph(child, document)
                if _breaks_before(child) and blocks:
                    boundaries.append(len(blocks))
                rendered = _paragraph_markdown(paragraph)
                if _is_split_heading(paragraph):
                    heading_starts.append(len(blocks))
                if rendered:
                    blocks.append(rendered)
                if _breaks_after(child):
                    boundaries.append(len(blocks))
            elif tag == f"{_W_NS}tbl":
                rendered = _table_markdown(Table(child, document))
                if rendered:
                    blocks.append(rendered)

        if not blocks:
            return []

        if boundaries:
            self.segmentation = "word-page-break"
            return _cut(blocks, boundaries, SegmentKind.PAGE, "page")
        if len(heading_starts) > 1:
            self.segmentation = "heading"
            return _cut(blocks, heading_starts, SegmentKind.SECTION, "section")

        self.segmentation = "fallback-chunk"
        return _chunk(join_blocks(blocks))


def _cut(
    blocks: List[str],
    boundaries: List[int],
    kind: SegmentKind,
    noun: str,
) -> List[ParsedSegment]:
    cuts = sorted({b for b in boundaries if 0 < b < len(blocks)})
    starts = [0] + cuts
    ends = cuts + [len(blocks)]
    segments: List[ParsedSegment] = []
    for number, (start, end) in enumerate(zip(starts, ends), start=1):
        markdown = join_blocks(blocks[start:end])
        segments.append(
            ParsedSegment(markdown=markdown, kind=kind, label=f"{noun} {number}")
        )
    return segments


def _chunk(text: str) -> List[ParsedSegment]:
    return [
        ParsedSegment(
            markdown=text[start : start + _FALLBACK_CHARS_PER_SECTION],
            kind=SegmentKind.SECTION,
            label=f"part {number}",
        )
        for number, start in enumerate(
            range(0, max(len(text), 1), _FALLBACK_CHARS_PER_SECTION), start=1
        )
    ]


def _breaks_before(element) -> bool:
    return element.find(_BREAK_BEFORE_XPATH) is not None


def _breaks_after(element) -> bool:
    return element.find(_PAGE_BREAK_XPATH) is not None


def _heading_level(paragraph) -> Optional[int]:
    style = (getattr(paragraph.style, "name", "") or "").strip()
    if not style.lower().startswith("heading"):
        return None
    tail = style.split()[-1]
    return int(tail) if tail.isdigit() else None


def _is_split_heading(paragraph) -> bool:
    level = _heading_level(paragraph)
    return level in _SPLIT_HEADING_LEVELS and bool(paragraph.text.strip())


def _paragraph_markdown(paragraph) -> str:
    text = normalize_text(paragraph.text)
    if not text:
        return ""
    level = _heading_level(paragraph)
    if level:
        return heading(text, level)
    style = (getattr(paragraph.style, "name", "") or "").lower()
    if "list" in style:
        return f"- {text}"
    return text


def _table_markdown(table) -> str:
    rows = [[cell.text for cell in row.cells] for row in table.rows]
    return render_table(rows)
