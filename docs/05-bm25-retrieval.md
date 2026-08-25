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

## What BM25 is worth here

Measured over all 136 practice questions, BM25 alone reaches **16.2%**
gold-page recall@5 against **58.1%** for dense retrieval, and it adds roughly
one question to the fused result. It is kept at `hybrid_bm25_weight = 0.1`.

That is not a verdict on lexical retrieval — it is a verdict on lexical
retrieval *over whole pages*. BM25 normalises by document length and these
pages run from 200 to 47,000 characters, so its natural strength (exact strings
like `1.500% Notes due 2026`) is diluted away. Re-measure after within-page
chunking, not before.

Full analysis: [Document retrieval](07-hybrid-retrieval.md).
