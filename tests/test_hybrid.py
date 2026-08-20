from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.hybrid.boosting import StatementTitleBooster
from analyst_copilot.retrieval.hybrid.fusion import (
    min_max_normalize,
    ranks_from_scores,
    reciprocal_rank_fusion,
    weighted_fusion,
)
from analyst_copilot.retrieval.hybrid.query_expansion import FinancialQueryExpander


def test_weighted_fusion_prefers_page_with_both_signals():
    bm25_scores = {1: 10.0, 2: 30.0, 3: 5.0}
    vector_scores = {2: 0.2, 3: 0.9, 4: 0.4}

    fused = weighted_fusion(
        bm25_scores=bm25_scores,
        vector_scores=vector_scores,
        bm25_weight=0.45,
        vector_weight=0.55,
    )

    assert fused[3] > fused[2]
    assert fused[2] > fused[1]


def test_min_max_normalize_handles_flat_scores():
    normalized = min_max_normalize({1: 4.0, 2: 4.0, 3: 4.0})
    assert normalized == {1: 1.0, 2: 1.0, 3: 1.0}


def test_reciprocal_rank_fusion_rewards_consensus():
    bm25_ranks = {10: 1, 20: 2, 30: 3}
    vector_ranks = {30: 1, 20: 2, 40: 3}

    fused = reciprocal_rank_fusion([bm25_ranks, vector_ranks], rrf_k=60)

    assert fused[20] > fused[10]
    assert fused[20] > fused[40]


def test_ranks_from_scores_are_one_based():
    ranks = ranks_from_scores({5: 0.2, 8: 0.9, 3: 0.5})
    assert ranks == {8: 1, 3: 2, 5: 3}


def test_query_expander_adds_cash_flow_and_capex_terms():
    query = (
        "What is the FY2018 capital expenditure amount (in USD millions) for 3M? "
        "Give a response by relying on the cash flow statement."
    )
    expanded = FinancialQueryExpander().expand(query).lower()
    assert "pp&e" in expanded
    assert "consolidated statement of cash flows" in expanded


def test_statement_title_booster_lifts_cash_flow_page():
    pages = {
        1: Page(doc_name="demo", page_index=1, text="Liquidity discussion and free cash flow"),
        2: Page(
            doc_name="demo",
            page_index=2,
            text="Consolidated Statement of Cash Flows Years ended December 31",
        ),
    }
    scores = {1: 1.0, 2: 1.0}
    boosted = StatementTitleBooster(multiplier=1.25).apply(
        "capital expenditure from the cash flow statement",
        pages,
        scores,
    )
    assert boosted[2] > boosted[1]


def test_hybrid_ranks_cash_flow_page_for_practice_question():
    from analyst_copilot.config.settings import get_settings
    from analyst_copilot.retrieval.hybrid.searcher import HybridSearcher
    from analyst_copilot.services.indexing import HybridFilingIndexer

    settings = get_settings()
    filing_path = settings.filings_dir / "3M_2018_10K.htm"

    indexer = HybridFilingIndexer()
    if indexer.indices_exist("3M_2018_10K"):
        indices = indexer.load_indices("3M_2018_10K")
    else:
        indices = indexer.index_filing(filing_path, save=True)

    query = (
        "What is the FY2018 capital expenditure amount (in USD millions) for 3M? "
        "Give a response to the question by relying on the details shown in the cash flow statement."
    )
    result = HybridSearcher().search(
        indices.bm25_index,
        indices.vector_index,
        query,
        top_k=5,
    )

    assert result.top_hit is not None
    assert result.top_hit.page.printed_page == 60
    assert "Purchases of property, plant and equipment" in result.top_hit.page.text
    assert "1,577" in result.top_hit.page.text
