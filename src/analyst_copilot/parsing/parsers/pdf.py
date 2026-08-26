"""PDF → Markdown, one segment per page.

PDF is the reference implementation of the parsing contract because its page
boundaries are explicit: the format stores pages, so no boundary has to be
inferred and a citation of "page 61" means the page an analyst sees at 61.

Layout is recovered with `pdfplumber`, which exposes table geometry. The page is
cut into horizontal bands at the tables' bounding boxes, so prose and tables
come out interleaved in reading order and neither is duplicated inside the
other. When `pdfplumber` is unavailable or fails on a page, the parser degrades
to `pypdf`'s plain text extraction rather than dropping the page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from analyst_copilot.parsing.base import DocumentParser, ParsedSegment
from analyst_copilot.parsing.formats import DocumentFormat
from analyst_copilot.parsing.markdown import join_blocks, normalize_text, render_table
from analyst_copilot.parsing.models import SegmentKind

logger = logging.getLogger(__name__)

# Bands thinner than this are gutters between stacked tables, not prose.
_MIN_BAND_HEIGHT = 4.0
# A "table" of one column is nearly always a mis-detected text block; rendering
# it as a table would bury a paragraph in pipe characters.
_MIN_TABLE_COLUMNS = 2
# Vertical gap, in points, below which two same-geometry tables are one striped
# table. A statement line is ~9pt on an ~18pt pitch, so one blank row fits.
_MAX_STRIPE_GAP = 26.0


class PdfParser(DocumentParser):
    """One Markdown segment per PDF page, with tables preserved as tables."""

    format = DocumentFormat.PDF
    segmentation = "pdf-page"

    def __init__(self, extract_tables: bool = True) -> None:
        self._extract_tables = extract_tables

    def segments(self, path: Path) -> List[ParsedSegment]:
        if self._extract_tables:
            rendered = self._with_pdfplumber(path)
            if rendered is not None:
                return rendered
        return self._with_pypdf(path)

    # -- primary path ------------------------------------------------------ #
    def _with_pdfplumber(self, path: Path) -> Optional[List[ParsedSegment]]:
        try:
            import pdfplumber
        except ImportError:
            logger.info("pdfplumber not installed; falling back to plain PDF text")
            return None

        try:
            with pdfplumber.open(str(path)) as pdf:
                return [
                    ParsedSegment(
                        markdown=self._render_page(page, number),
                        kind=SegmentKind.PAGE,
                        label=f"page {number}",
                        printed_page=None,
                    )
                    for number, page in enumerate(pdf.pages, start=1)
                ]
        except Exception as exc:  # noqa: BLE001 - pdfminer raises broadly
            logger.warning("pdfplumber failed on %s (%s); using pypdf", path.name, exc)
            return None

    def _render_page(self, page, number: int) -> str:
        try:
            tables = [t for t in page.find_tables() if self._is_tabular(t)]
        except Exception:  # noqa: BLE001 - a single bad page must not kill the file
            tables = []

        if not tables:
            return normalize_text(page.extract_text() or "")

        blocks: List[str] = []
        cursor = 0.0
        for run in _merge_striped_runs(sorted(tables, key=lambda t: t.bbox[1])):
            top, bottom = run.top, run.bottom
            blocks.append(self._text_band(page, cursor, top))
            blocks.append(self._render_run(page, run))
            cursor = max(cursor, bottom)
        blocks.append(self._text_band(page, cursor, float(page.height)))

        rendered = join_blocks(blocks)
        # A page whose tables all failed to render still has to yield its text.
        return rendered or normalize_text(page.extract_text() or "")

    @staticmethod
    def _is_tabular(table) -> bool:
        try:
            return len(table.columns) >= _MIN_TABLE_COLUMNS
        except Exception:  # noqa: BLE001
            return False

    def _render_run(self, page, run: "_TableRun") -> str:
        """
        Render one run of table geometry as a single Markdown table.

        A single detected table is extracted as found. A run of several -- the
        shaded rows of a striped statement, each found separately -- is
        re-extracted across the whole band with the shared column edges pinned
        and rows detected from text, which recovers the unshaded rows that fall
        in the gaps between them.
        """
        if len(run.tables) == 1:
            return self._render_table(run.tables[0])

        try:
            band = page.crop((run.x0, run.top, run.x1, run.bottom))
            rows = band.extract_table(
                {
                    "vertical_strategy": "explicit",
                    "explicit_vertical_lines": list(run.edges),
                    "horizontal_strategy": "text",
                }
            )
        except Exception:  # noqa: BLE001 - degenerate crops and empty bands
            rows = None

        if rows:
            return render_table(rows)
        # Falling back row-by-row still beats dropping the band entirely.
        return join_blocks(self._render_table(t) for t in run.tables)

    @staticmethod
    def _text_band(page, top: float, bottom: float) -> str:
        """Prose lying between two tables, extracted without their cells."""
        if bottom - top < _MIN_BAND_HEIGHT:
            return ""
        try:
            band = page.crop((0, max(0.0, top), page.width, min(float(page.height), bottom)))
            return normalize_text(band.extract_text() or "")
        except Exception:  # noqa: BLE001 - crop rejects degenerate boxes
            return ""

    @staticmethod
    def _render_table(table) -> str:
        try:
            rows: Sequence[Sequence[object]] = table.extract()
        except Exception:  # noqa: BLE001
            return ""
        return render_table(rows or [])

    # -- fallback ---------------------------------------------------------- #
    @staticmethod
    def _with_pypdf(path: Path) -> List[ParsedSegment]:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        segments: List[ParsedSegment] = []
        for number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("page %d of %s did not extract: %s", number, path.name, exc)
                text = ""
            segments.append(
                ParsedSegment(
                    markdown=normalize_text(text),
                    kind=SegmentKind.PAGE,
                    label=f"page {number}",
                )
            )
        return segments


@dataclass
class _TableRun:
    """One or more detected tables that are really a single striped table."""

    tables: List[object]
    edges: Tuple[float, ...]
    x0: float
    top: float
    x1: float
    bottom: float


def _merge_striped_runs(tables: Sequence[object]) -> List[_TableRun]:
    """
    Group vertically adjacent tables that share their column edges.

    Financial statements are printed with alternating row shading, and the fills
    are what table detection latches onto -- so a twenty-row cash flow statement
    comes back as ten one-row tables with identical column geometry, eighteen
    points apart, with the unshaded rows sitting in the gaps as loose text.
    Grouping them restores the statement as one table.
    """
    runs: List[_TableRun] = []
    for table in tables:
        edges = _column_edges(table)
        x0, top, x1, bottom = (float(v) for v in table.bbox)
        current = runs[-1] if runs else None
        if (
            current is not None
            and current.edges == edges
            and top - current.bottom <= _MAX_STRIPE_GAP
        ):
            current.tables.append(table)
            current.x0 = min(current.x0, x0)
            current.x1 = max(current.x1, x1)
            current.bottom = max(current.bottom, bottom)
            continue
        runs.append(_TableRun([table], edges, x0, top, x1, bottom))
    return runs


def _column_edges(table) -> Tuple[float, ...]:
    """The table's vertical cell boundaries, rounded so near-identical geometry matches."""
    try:
        values = {round(float(cell[0]), 1) for cell in table.cells if cell}
        values |= {round(float(cell[2]), 1) for cell in table.cells if cell}
    except Exception:  # noqa: BLE001
        x0, _, x1, _ = table.bbox
        values = {round(float(x0), 1), round(float(x1), 1)}
    return tuple(sorted(values))


def page_count(path: Path) -> Tuple[int, str]:
    """The PDF's page count and which library reported it. Cheap: no text extraction."""
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages), "pypdf"
