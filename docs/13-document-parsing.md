# Document parsing — any format in, Markdown pages out

**Modules:** `analyst_copilot.parsing`
**Entry point:** `parse_document(path)` — [`registry.py`](../src/analyst_copilot/parsing/registry.py)

An analyst has a filing. It might be the EDGAR HTML, the PDF the company
published, a Word draft, or a spreadsheet of segment data pulled out of one of
those. The system should not care. This layer is where it stops caring.

---

## The shape

```text
upload
   │
   ├─ 1. detect      formats.py         extension, checked against magic bytes
   │
   ├─ 2. parse       parsers/*.py       one parser per format
   │
   ├─ 3. normalize   markdown.py        every format converges on Markdown
   │
   ├─ 4. segment                        page / sheet / table / section
   │
   ├─ 5. store       markdown_store.py  one .md file per segment + manifest
   │
   └─ 6. index                          BM25 + embeddings read the Markdown
```

Everything above step 6 knows only `parse_document(path)`. Adding a format is
registering a parser in [`registry.py`](../src/analyst_copilot/parsing/registry.py);
no caller changes.

---

## Formats

| Format | Parser | Unit | Boundary comes from |
|---|---|---|---|
| PDF | `PdfParser` | page | The file. Pages are stored, not inferred |
| HTML | `HtmlParser` | page | `page-break-{after,before}: always` markers |
| Word | `DocxParser` | page *or* section | Author's explicit page breaks; else headings |
| Excel | `ExcelParser` | sheet | One worksheet per segment; row blocks if large |
| CSV/TSV | `CsvParser` | table | The file; row blocks if large |
| Markdown / text | `PlainTextParser` | section | Whole file, chunked only if oversized |

Detection is by extension, checked against the file's first bytes. The
extension is primary because `.docx` and `.xlsx` are both ZIP archives and
nothing but the name distinguishes them; sniffing exists to catch the common
upload mistake — a PDF saved as `.txt` is read as a PDF, and a text file named
`.pdf` is rejected rather than failing deeper in the stack.

---

## The rule about page numbers

**A segment is only called a page when the source really has pages.**

A citation is a promise that a reader can go and look. "Page 4" of a CSV is not
a place; neither is "page 12" of a Word document whose pagination depends on the
reader's font. So the parsers label what they produce:

| Kind | When | Cited as |
|---|---|---|
| `page` | PDF page, HTML page break, Word page break | `page 61` |
| `sheet` | One worksheet | `sheet 'Q4 Revenue'` |
| `table` | A delimited file | `table 'revenue'` |
| `section` | Headings, row blocks, size chunks | `rows 402-601`, `part 3` |

`Page.citation_label` is what the answer prints, and it is what the model is
shown in the prompt — so an excerpt from a worksheet is never presented as a
page of prose.

Where a boundary is ours rather than the document's, it is labelled `section`
and `FilingDocument.segmentation` records how it was found (`pdf-page`,
`page-break`, `word-page-break`, `heading`, `worksheet`, `fallback-chunk`). An
operator reading a manifest can tell a real pagination from a synthesized one
without opening the source.

---

## Why Markdown

Because tables are where the answers are, and plain text destroys them.

A 10-K's answer is usually a line item in a financial statement. Extracted as
prose, the cash flow statement reads:

```
Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420)
```

Three figures, no years. The model has to guess which is FY2018, and the
verifier has to accept any of the three as support. As Markdown:

```markdown
| (Millions) | 2018 | 2017 | 2016 |
| --- | --- | --- | --- |
| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) | (1,420) |
```

The row label stays attached to its columns, which is the association the whole
question depends on.

Two table details that matter in practice:

**Layout tables are unwrapped, not rendered.** SEC filers nest tables for
layout. `HtmlParser` works innermost-outward: a table with real columns becomes
a Markdown table, and the single-column wrappers left behind are unwrapped so
the page is not buried in pipes.

**Empty spacer columns are dropped.** Filers pad statements with narrow spacer
cells — three year columns routinely render as eleven. Columns empty in every
row carry no content and are removed, which cut the 3M cash flow page from
3,389 to 3,137 characters and put the figures back beside their labels.

**Striped PDF tables are stitched back together.** `pdfplumber` detects tables
from their fills, so an alternating-shade statement comes back as ten one-row
tables with identical column geometry and the unshaded rows loose between them.
`PdfParser` groups runs that share column edges and re-extracts the whole band
with the columns pinned and rows detected from text, which recovers the full
statement as one table.

---

## Page-level storage

```text
storage/markdown/{doc_name}/
    manifest.json
    page-001.md      paginated sources
    sheet-001.md     worksheets
    part-001.md      row blocks, headings, chunks
```

The Markdown is written at parse time, before embedding — a run that dies while
embedding still leaves behind what the parser read.

Three reasons it exists at all, when the indices already hold the text:

1. **It is the artifact a human can check.** When a citation looks wrong the
   question is always "what did the system actually read on that page", and the
   answer should be a file you can open.
2. **It decouples parsing from embedding.** Re-chunking or re-embedding can
   replay from the Markdown without re-parsing a 200-page PDF.
3. **It is the contract between formats.** A CSV and a 10-K look identical here.

`manifest.json` records the source path, format, segmentation, parser version
and one entry per segment (file, index, kind, label, printed page, char count).
The directory is cleared on re-save, so a document that re-parses to fewer
segments cannot leave stale pages behind for a reader to mistake for current
ones.

---

## Index invalidation

`PARSER_VERSION` lives in [`version.py`](../src/analyst_copilot/parsing/version.py)
and is stamped into every index. Indices built by a different version are
treated as **absent**, not stale-but-usable, so a parser fix can never be masked
by old embeddings on disk.

It is now **4**. Version 3 indexed plain text; version 4 indexes Markdown, which
changes the text of nearly every segment — so everything indexed under 3 is
treated as absent and rebuilt.

Nothing has to be run to make that happen. Indexing is on demand: the QA
service builds a document's indices the first time a question is asked of it,
and the API builds them per upload.

---

## Known limits

**1. PDF parsing is slow.** ~57s for a 160-page 10-K, against ~2s for the same
document as HTML — `pdfplumber` reads geometry, not just text. Inside the
10-minute budget with room to spare, but it dominates indexing time and scales
with page count. `PdfParser(extract_tables=False)` falls back to `pypdf` plain
text and is roughly ten times faster, at the cost of the tables.

**2. Word pagination is not recoverable.** Word stores no pages; the renderer
makes them from fonts and margins. Only author-inserted breaks are real, so a
document without them yields sections. This is a deliberate refusal, not a gap.

**3. Character caps still bite.** Markdown does not change how long a page is.
The median segment is ~3,800 characters against a 2,500-character embedding cap,
so 74% of pages are still truncated before embedding. Within-page chunking is
the fix and is not done.

**4. Merged cells repeat nothing.** A cell spanning three columns is rendered
once, in its first column. Faithful, but a reader of the Markdown alone may
misread which columns a spanning header covers.
