"""Shared helpers for rendering document content as Markdown.

Markdown is the one representation the retrieval and QA layers see, so these
helpers decide what those layers can know. Two properties matter more than
prettiness:

1. **Tables survive as tables.** A 10-K's answer is usually a line item in a
   financial statement. Flattened to prose, `Purchases of PP&E (1,577) (1,373)`
   loses which column is which year -- and the verifier then has to accept any
   of three figures as support. A Markdown table keeps the row label attached
   to its columns.
2. **No content is invented.** Empty cells stay empty, merged cells repeat
   nothing, and a row of numbers is never re-ordered to fit a header.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

# Markdown gives `|` structural meaning inside a table row, so any pipe in the
# data has to be escaped or the row silently gains a column.
_PIPE = re.compile(r"\|")
_WHITESPACE = re.compile(r"[ \t   ]+")
_BLANK_RUN = re.compile(r"\n{3,}")


def clean_cell(value: object) -> str:
    """Render one table cell as a single line of Markdown-safe text."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ")
    text = _PIPE.sub(r"\|", text)
    return _WHITESPACE.sub(" ", text).strip()


def normalize_text(text: str) -> str:
    """Collapse whitespace runs and blank-line runs without joining paragraphs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WHITESPACE.sub(" ", line).rstrip() for line in text.split("\n")]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def render_table(
    rows: Sequence[Sequence[object]],
    header: Optional[Sequence[object]] = None,
) -> str:
    """
    Render rows as a GitHub-flavoured Markdown table.

    When no header is given the first row is promoted, because a table whose
    first row is column labels is overwhelmingly the common case in filings and
    spreadsheets. A table with a single row is emitted as a header-only table
    rather than a bare separator, which no renderer accepts.
    """
    cleaned = [[clean_cell(cell) for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(cell for cell in row)]
    if not cleaned and header is None:
        return ""

    if header is None:
        header_cells, body = cleaned[0], cleaned[1:]
    else:
        header_cells, body = [clean_cell(cell) for cell in header], cleaned

    width = max([len(header_cells)] + [len(row) for row in body] or [0])
    if width == 0:
        return ""

    header_cells, body = _drop_empty_columns(_pad(header_cells, width), body, width)
    width = len(header_cells)
    if width == 0:
        return ""
    # A table whose header row is entirely blank renders as a headerless block
    # in most viewers; numbering the columns keeps it legible and keeps the
    # column count explicit for anything reading the Markdown back.
    if not any(header_cells):
        header_cells = [f"col {i + 1}" for i in range(width)]

    lines = [
        "| " + " | ".join(header_cells) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend("| " + " | ".join(_pad(row, width)) + " |" for row in body)
    return "\n".join(lines)


def _pad(row: Sequence[str], width: int) -> List[str]:
    return list(row) + [""] * (width - len(row))


def _drop_empty_columns(
    header: List[str],
    body: List[List[str]],
    width: int,
) -> Tuple[List[str], List[List[str]]]:
    """
    Remove columns that are empty in every row.

    SEC filers pad financial tables with narrow spacer cells -- a statement with
    three year columns routinely renders as eleven. Those columns carry no
    content, but they triple the table's character count and push the figures
    apart from their row labels, which is exactly the association the Markdown
    table exists to preserve.
    """
    padded = [_pad(row, width) for row in body]
    keep = [
        column
        for column in range(width)
        if header[column] or any(row[column] for row in padded)
    ]
    if len(keep) == width:
        return header, padded
    return (
        [header[column] for column in keep],
        [[row[column] for column in keep] for row in padded],
    )


def heading(text: str, level: int = 2) -> str:
    """A Markdown heading, or nothing when there is no text to head."""
    label = clean_cell(text)
    if not label:
        return ""
    return f"{'#' * max(1, min(level, 6))} {label}"


def join_blocks(blocks: Iterable[str]) -> str:
    """Join rendered blocks with blank lines, dropping the empty ones."""
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())
