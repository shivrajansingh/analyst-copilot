# Hybrid retrieval

**Module:** `analyst_copilot.retrieval.hybrid`

Combines BM25 and vector search so exact line items and paraphrased analyst questions both retrieve the right **page**.

## Pipeline (`hybrid/searcher.py`)

1. **Expand** the query (`FinancialQueryExpander`) — e.g. capex → PP&E / purchases of property; cash flow → consolidated statement of cash flows.
2. **Retrieve** top `hybrid_candidate_pool` pages from BM25 and from vectors (same expanded query).
3. **RRF** — reciprocal rank fusion across the two ranked lists (`k=60`).
4. **Weighted fusion** — min-max normalize BM25 and cosine scores (`0.45` / `0.55`).
5. **Blend** RRF (0.6) with weighted scores (0.4).
6. **Boost** pages whose text contains the matching statement title (`StatementTitleBooster`, 1.25×).
7. Return top_k `ScoredPage` hits with `bm25_score` and `vector_score` populated when available.

## Why this exists

On the full 3M 2018 10-K and the official practice capex question:

- BM25-only and early hybrid (pool=30, weighted only) ranked **page 49** first.
- After expansion + pool 80 + RRF + statement boost, **printed page 60** (cash flow statement, value `1,577`) ranks first.

Gold `evidence_page_num` is 59; printed footer on that statement is 60.

## Demos / tests

```bash
PYTHONPATH=src python scripts/examples/hybrid_search_full_filing.py
PYTHONPATH=src pytest tests/test_hybrid.py
```

`hybrid_search_full_filing.py` reuses saved indices when present so fusion changes can be tested without re-embedding.
