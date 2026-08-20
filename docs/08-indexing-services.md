# Indexing services

**Module:** `analyst_copilot.services.indexing`

Orchestration only: parse a filing, build indices, save or load. Retrieval algorithms stay in `retrieval/`.

## Types

- `FilingIndices` (`models.py`): `doc_name`, `bm25_index`, `vector_index`
- `FilingIndexer` (`filing_indexer.py`): parse + BM25 build/save/load
- `HybridFilingIndexer` (`hybrid_indexer.py`): parse + BM25 + vector build/save/load

## Usage

```python
from analyst_copilot.services.indexing import HybridFilingIndexer
from analyst_copilot.retrieval import HybridSearcher

indexer = HybridFilingIndexer()
indices = indexer.index_filing("filings/3M_2018_10K.htm", save=True)
# or indexer.load_indices("3M_2018_10K") if already saved

result = HybridSearcher().search(
    indices.bm25_index,
    indices.vector_index,
    "FY2018 capital expenditure from the cash flow statement",
    top_k=5,
)
print(result.top_hit.page.citation_page, result.top_hit.score)
```

## Storage

| Index | Path |
|-------|------|
| BM25 | `storage/bm25_indices/{doc_name}/` |
| Vectors | `storage/vector_indices/{doc_name}/` |

`storage/` is gitignored.

## Scope

Indexing is **per filing**. Chat must select one `doc_name` and search only that pair of indices. Cross-filing questions are out of scope for the spec.
