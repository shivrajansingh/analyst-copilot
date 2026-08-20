# HTML parsing

**Module:** `analyst_copilot.parsing`

SEC filings in `filings/` are HTML (often wrapped in EDGAR `<DOCUMENT>` / `<TEXT>`). Citations must include a **page number**, so parsing is page-aligned.

## Models (`parsing/models.py`)

- `Page`: `doc_name`, `page_index` (0-based split index), `text`, `printed_page` (footer number when detected)
- `Page.citation_page`: `printed_page` if present, else `page_index + 1`
- `FilingDocument`: `doc_name`, `source_path`, `pages`

## Parser (`parsing/html_filing_parser.py`)

`parse_filing_html(path)`:

1. Read UTF-8 (ignore errors).
2. Unwrap `<TEXT>...</TEXT>` when present.
3. Split on `page-break-after: always` (most 10-K/10-Q files).
4. Convert each fragment to text with BeautifulSoup (`lxml`); drop script/style.
5. Detect a trailing integer footer as `printed_page` (range 1–2000).
6. If there are **no** page-break markers (~5 filings), fall back to ~3500-character chunks.

## Known offset

On `3M_2018_10K.htm`, the cash-flow statement is **printed page 60**. Practice gold `evidence_page_num` is **59**. Evaluation should treat adjacent pages as a possible off-by-one until QA maps citations consistently.

## Demo / test

```bash
PYTHONPATH=src python scripts/examples/parse_filing_example.py
PYTHONPATH=src pytest tests/test_parsing.py
```
