# HTML parsing

**Module:** `analyst_copilot.parsing`

SEC filings in `filings/` are HTML (often wrapped in EDGAR `<DOCUMENT>` / `<TEXT>`). Citations must include a **page number**, so parsing is page-aligned.

## Models (`parsing/models.py`)

- `Page`: `doc_name`, `page_index` (0-based split index), `text`, `printed_page` (footer number when detected)
- `Page.citation_page`: **`page_index`** — the number used for citations and scoring
- `Page.display_page`: `page_index + 1`, for human-facing text
- `FilingDocument`: `doc_name`, `source_path`, `pages`

### Why citations use `page_index`, not `printed_page`

The practice key numbers evidence with `evidence_page_num`, a 0-based page ordinal. Measured over the 141 gold evidence blocks that can be located in parsed text:

| Citation source | Agreement with gold |
| --------------- | ------------------- |
| `page_index` | **77% exact, 92% within ±1** |
| `printed_page` | off by +1 on 50 blocks, −1 on 44 blocks — no consistent direction |

Printed footers are unreliable because the page-break marker sits *before* the footer in some filings and *after* it in others, so the same footer number attaches to different segments. `printed_page` is still parsed and stored, but only as reference metadata.

## Parser (`parsing/html_filing_parser.py`)

`parse_filing_html(path)`:

1. Read UTF-8 (ignore errors).
2. Unwrap `<TEXT>...</TEXT>` when present.
3. Split on `page-break-after: always` **or `page-break-before: always`**, matched on `<hr>`, `<p>` or `<div>` (and the CSS4 `break-*` spelling).
4. Convert each fragment to text with BeautifulSoup (`lxml`); drop script/style.
5. Detect a trailing integer footer as `printed_page` (range 1–2000).
6. If there are **no** page-break markers, fall back to ~3500-character chunks.

### The `<hr>` regression

The pattern originally matched `<p[^>]*page-break-after...>` only. Across the corpus:

| Marker | Filings |
| ------ | ------- |
| `<hr style="page-break-after:always">` | 74 |
| `<hr style="page-break-before:always">` | 2 (`GENERALMILLS_2019_10K`, `MICROSOFT_2016_10K`) |
| `<p style="page-break-after:always">` | 1 (`3M_2018_10K`, the file the parser was developed against) |

`before` and `after` mark the same boundary, so splitting on either yields the same pages.

So 78 of 79 filings silently took the character-chunking fallback. That made every page citation a 3500-character slice ordinal rather than a page, put `+1` for location permanently out of reach, and cut tables mid-row so a balance-sheet line item could land in a different chunk from its header. Widening the tag set, and then accepting `break-before`, brought filings on the fallback path down from 78 to 3 — all short 8-Ks that genuinely carry no page-break markers. Each of those 3 still has one practice question whose citation is therefore a chunk ordinal rather than a page.

`tests/test_parsing.py` guards both the tag set and the corpus-wide ratio.

## Index invalidation

`PARSER_VERSION` in `html_filing_parser.py` is recorded in every persisted index. `BM25IndexStore.exists()` and `VectorIndexStore.exists()` report a stale index as **absent**, so a parser change forces a rebuild instead of silently searching old page boundaries. The vector store also invalidates when `EMBEDDING_MODEL` changes. Bump `PARSER_VERSION` whenever page boundaries or numbering change.

## Demo / test

```bash
PYTHONPATH=src python scripts/examples/parse_filing_example.py
PYTHONPATH=src pytest tests/test_parsing.py
```
