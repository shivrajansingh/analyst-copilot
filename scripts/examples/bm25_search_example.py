"""
BM25 search example: index a filing and run a lexical query.

Usage:
  PYTHONPATH=src python scripts/examples/bm25_search_example.py
"""

from __future__ import annotations

from analyst_copilot.config.settings import get_settings
from analyst_copilot.retrieval.bm25.searcher import BM25Searcher
from analyst_copilot.services.indexing import FilingIndexer

CAPEX_QUERY = (
    "What is the FY2018 capital expenditure amount from the cash flow statement? "
    "Purchases of property, plant and equipment PP&E"
)


def main() -> None:
    settings = get_settings()
    filing_path = settings.filings_dir / "3M_2018_10K.htm"
    doc_name = filing_path.stem

    print("=== Analyst Copilot — BM25 search example ===\n")
    print(f"Filing: {filing_path.name}\n")

    indexer = FilingIndexer()
    index = indexer.index_filing(filing_path, doc_name=doc_name, save=True)
    print(f"Indexed pages: {index.metadata.page_count}")
    print(f"Saved to:      storage/bm25_indices/{doc_name}/\n")

    searcher = BM25Searcher()
    result = searcher.search(index, CAPEX_QUERY, top_k=5)

    print(f"Query: {result.query}\n")
    print("Top BM25 matches:")
    for hit in result.hits:
        snippet = hit.page.text[:160].replace("\n", " ")
        print(
            f"  {hit.rank}. score={hit.score:.4f} | "
            f"printed_page={hit.page.printed_page} | page_index={hit.page.page_index} | "
            f"{snippet}..."
        )


if __name__ == "__main__":
    main()
