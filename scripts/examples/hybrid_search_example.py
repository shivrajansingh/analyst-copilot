"""
Hybrid retrieval example: BM25 + vector embeddings with score fusion.

Usage:
  PYTHONPATH=src python scripts/examples/hybrid_search_example.py
"""

from __future__ import annotations

from analyst_copilot.config.settings import get_settings
from analyst_copilot.retrieval.hybrid.searcher import HybridSearcher
from analyst_copilot.services.indexing import HybridFilingIndexer

CAPEX_QUERY = (
    "What is the FY2018 capital expenditure amount from the cash flow statement? "
    "Purchases of property, plant and equipment PP&E"
)


def main() -> None:
    settings = get_settings()
    filing_path = settings.filings_dir / "3M_2018_10K.htm"
    doc_name = filing_path.stem

    print("=== Analyst Copilot — hybrid search example ===\n")
    print(f"Filing: {filing_path.name}")
    print(
        f"Fusion: RRF + weighted "
        f"(bm25={settings.hybrid_bm25_weight}, vector={settings.hybrid_vector_weight})\n"
    )

    indexer = HybridFilingIndexer()
    indices = indexer.index_filing(filing_path, doc_name=doc_name, save=True)

    print(f"Indexed pages: {indices.bm25_index.metadata.page_count}")
    print(f"BM25 store:    storage/bm25_indices/{doc_name}/")
    print(f"Vector store:  storage/vector_indices/{doc_name}/\n")

    result = HybridSearcher().search(
        indices.bm25_index,
        indices.vector_index,
        CAPEX_QUERY,
        top_k=5,
    )

    print(f"Query: {result.query}\n")
    print("Top hybrid matches:")
    for hit in result.hits:
        snippet = hit.page.text[:140].replace("\n", " ")
        bm25 = f"{hit.bm25_score:.4f}" if hit.bm25_score is not None else "n/a"
        vector = f"{hit.vector_score:.4f}" if hit.vector_score is not None else "n/a"
        print(
            f"  {hit.rank}. fused={hit.score:.4f} | "
            f"bm25={bm25} | vector={vector} | "
            f"printed_page={hit.page.printed_page} | page_index={hit.page.page_index} | "
            f"{snippet}..."
        )


if __name__ == "__main__":
    main()
