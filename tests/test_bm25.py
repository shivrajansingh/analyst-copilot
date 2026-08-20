from analyst_copilot.config.settings import get_settings
from analyst_copilot.retrieval.bm25.searcher import BM25Searcher
from analyst_copilot.services.indexing import FilingIndexer


def test_bm25_ranks_cash_flow_page_for_capex_query():
    settings = get_settings()
    filing_path = settings.filings_dir / "3M_2018_10K.htm"

    indexer = FilingIndexer()
    index = indexer.index_filing(filing_path, save=False)

    query = (
        "FY2018 capital expenditure cash flow statement "
        "Purchases of property plant and equipment PP&E"
    )
    result = BM25Searcher().search(index, query, top_k=5)

    assert result.top_hit is not None
    top_page = result.top_hit.page
    assert top_page.printed_page == 60
    assert "Purchases of property, plant and equipment" in top_page.text
    assert "1,577" in top_page.text


def test_tokenizer_normalizes_comma_separated_numbers():
    from analyst_copilot.retrieval.tokenization import TextTokenizer

    tokens = TextTokenizer().tokenize("Purchases of PP&E (1,577) in 2018")
    assert "1577" in tokens
    assert "2018" in tokens
