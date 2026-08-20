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

## Note

Truncation at 2500 characters can drop the bottom of a long table. Within-page chunking is listed as optional remaining work in `PLAN.md`.
