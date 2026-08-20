# BM25 retrieval

**Module:** `analyst_copilot.retrieval.bm25`  
**Tokenizer:** `analyst_copilot.retrieval.tokenization`

Lexical search over page text using `rank-bm25` (`BM25Okapi`).

## Pieces

| File | Role |
|------|------|
| `tokenization.py` | Lowercase, strip commas inside numbers (`1,577` → `1577`), alphanumeric tokens |
| `bm25/index.py` | `BM25Index`: pages + tokenized corpus + model |
| `bm25/builder.py` | `BM25IndexBuilder.build(FilingDocument)` |
| `bm25/searcher.py` | `BM25Searcher.search(index, query, top_k)` |
| `bm25/storage.py` | Save/load under `storage/bm25_indices/{doc_name}/` |

Hits are `ScoredPage` objects (`retrieval/models.py`) with `page`, `score`, `rank`.

Zero-score pages are dropped. Empty token queries return no hits.

## Demo / test

```bash
PYTHONPATH=src python scripts/examples/bm25_search_example.py
PYTHONPATH=src pytest tests/test_bm25.py
```

BM25 alone can rank narrative “cash flow” pages above the actual statement. Hybrid retrieval is required for citation quality.
