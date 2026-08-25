# Vector retrieval

**Module:** `analyst_copilot.retrieval.vector`

Dense retrieval: one embedding per page, cosine similarity at query time.

## Pieces

| File | Role |
|------|------|
| `text.py` | Truncate page text (`retrieval_max_chars_per_page`) |
| `similarity.py` | Cosine similarity |
| `index.py` | `VectorIndex`: pages + vectors + metadata |
| `builder.py` | Embed all pages via `get_embedding_client()` |
| `searcher.py` | Embed query, rank pages |
| `storage.py` | `vectors.npz` + `pages.json` + `metadata.json` under `storage/vector_indices/{doc_name}/` |

Metadata records embedding model name and dimensions so a later reload can detect mismatch.

Indexing a full ~130-page 10-K against `qwen3-embedding:8b-fp16` takes on the order of 1–2 minutes over the configured remote server, which is inside the 10-minute “Add filing” budget.

## The truncation limit

Only the first `retrieval_max_chars_per_page` (2,500) characters of each page
are embedded. BM25 indexes the whole page, so on a long page the two retrievers
are working from different amounts of text.

Measured across 20 filings / 2,252 pages, **73% of pages exceed the cap**. The
worst case in the corpus is `3M_2023Q2_10Q` page 1: 47,221 characters, 2,500
embedded, with the gold evidence at character 45,234 — unreachable by semantic
search.

`GET /filings/{doc}/pages/{n}` reports `embedded_chars` and `truncated` so this
boundary is visible in the UI rather than silent. Within-page chunking is the
fix; raising the cap is not, because real pages exceed any safe cap.

Full analysis: [Document retrieval](07-hybrid-retrieval.md).
