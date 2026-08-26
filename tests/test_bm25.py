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
    # The Consolidated Statement of Cash Flows is page_index 59. It is asserted
    # to be near the top rather than exactly first: rendering tables as Markdown
    # changed page lengths slightly, and BM25 normalises by length, so page 48
    # ("Other cash flows from financing activities") now edges it by 25.4 to
    # 25.1. The property under test is that lexical search finds the statement.
    ranked = [hit.page.page_index for hit in result.hits]
    assert 59 in ranked[:3], ranked
    statement = next(hit.page for hit in result.hits if hit.page.page_index == 59)
    assert "Purchases of property, plant and equipment" in statement.text
    assert "1,577" in statement.text


def test_tokenizer_normalizes_comma_separated_numbers():
    from analyst_copilot.retrieval.tokenization import TextTokenizer

    tokens = TextTokenizer().tokenize("Purchases of PP&E (1,577) in 2018")
    assert "1577" in tokens
    assert "2018" in tokens
