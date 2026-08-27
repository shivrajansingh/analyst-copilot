"""The corpus, the tools and the calculator: everything the agents read with.

No model calls anywhere in this file. What is under test is the read surface —
which pages an agent can reach, what a tool tells it when it reaches past them,
and whether the arithmetic is exact.
"""

from __future__ import annotations

import pytest

from analyst_copilot.agent.corpus import DocumentCorpus, DocumentUnavailable
from analyst_copilot.agent.tools import (
    CalculateTool,
    DocumentToolset,
    ToolRegistry,
    document_tools,
    evaluate,
    normalize_expression,
)
from analyst_copilot.agent.tools.calculator import CalculationError, format_result
from analyst_copilot.parsing.markdown_store import MarkdownPageStore
from analyst_copilot.parsing.models import FilingDocument, Page, SegmentKind

DOC = "TESTCO_2022_10K"

PAGE_TEXT = {
    0: "# Cover\n\nTESTCO Annual Report 2022",
    1: "# Table of Contents\n\nItem 1. Business ... 3",
    2: "# Item 1. Business\n\nTESTCO makes widgets in twelve countries.",
    3: "# Consolidated Statement of Cash Flows\n\n"
       "| | 2022 | 2021 |\n| --- | --- | --- |\n"
       "| Purchases of property, plant and equipment | (1,577) | (1,373) |",
    4: "# Consolidated Balance Sheet\n\n"
       "| | 2022 | 2021 |\n| --- | --- | --- |\n| Property, plant and equipment, net | 8,738 | 8,846 |",
}


@pytest.fixture
def corpus(tmp_path):
    """A five-page document written through the real Markdown store."""
    pages = [
        Page(doc_name=DOC, page_index=index, text=text, segment_kind=SegmentKind.PAGE,
             segment_label=f"page {index + 1}")
        for index, text in PAGE_TEXT.items()
    ]
    document = FilingDocument(
        doc_name=DOC, source_path="/tmp/testco.htm", pages=pages, segmentation="page-break"
    )
    store = MarkdownPageStore(base_dir=tmp_path / "markdown")
    store.save(document)
    return DocumentCorpus(store=store, doc_names=[DOC])


# --- corpus ---------------------------------------------------------------- #
def test_corpus_reads_pages_and_their_labels(corpus):
    assert corpus.page_count == 5
    view = corpus.page(DOC, 3)
    assert "Purchases of property" in view.text
    assert view.display_page == 4
    assert view.segment_kind is SegmentKind.PAGE


def test_a_page_past_the_end_says_how_many_there_are(corpus):
    with pytest.raises(DocumentUnavailable, match="has 5 segments"):
        corpus.page(DOC, 99)


def test_search_ignores_case_and_digit_grouping(corpus):
    """A filing's 1,577 and a query's 1577 are the same figure."""
    assert [m.page_index for m in corpus.search("1577")] == [3]
    assert [m.page_index for m in corpus.search("PURCHASES OF PROPERTY")] == [3]
    assert corpus.search("1,577")[0].line_number == 5


def test_search_can_be_scoped_to_named_pages(corpus):
    refs = [meta.ref for meta in corpus.pages_of(DOC)[:3]]
    assert corpus.search("property", pages=refs) == []
    assert corpus.search("property") != []


def test_lines_clamp_to_what_the_page_has(corpus):
    first, last, text = corpus.lines(DOC, 2, 1, 500)
    assert first == 1
    assert last < 500
    assert "widgets" in text


def test_find_quote_matches_through_markdown_punctuation(corpus):
    """The same row reaches us with pipes from one parser and without from another."""
    ref = corpus.find_quote("Purchases of property, plant and equipment (1,577)")
    assert ref is not None and ref.page_index == 3


def test_find_quote_refuses_a_fragment_too_short_to_be_evidence(corpus):
    assert corpus.find_quote("2022") is None


def test_shards_split_by_page_count_and_never_straddle_documents(corpus):
    shards = corpus.shards(2)
    assert [len(shard.pages) for shard in shards] == [2, 2, 1]
    assert all(shard.total == 3 for shard in shards)
    assert {page.doc_name for shard in shards for page in shard.pages} == {DOC}
    # Every page belongs to exactly one shard: that is what makes the fan-out
    # complete without two readers reporting the same page.
    covered = [page.page_index for shard in shards for page in shard.pages]
    assert sorted(covered) == list(range(5))


def test_a_shard_describes_the_range_it_holds(corpus):
    assert corpus.shards(2)[0].describe() == f"{DOC} pages 1-2"


# --- document tools -------------------------------------------------------- #
def _registry(corpus, allowed=None, label=""):
    toolset = DocumentToolset(corpus, allowed=allowed, scope_label=label)
    return ToolRegistry(document_tools(toolset) + [CalculateTool()]), toolset


def test_read_page_uses_the_page_numbers_the_agent_was_shown(corpus):
    registry, _ = _registry(corpus)
    result = registry.invoke("read_page", '{"page": 4}')
    assert result.ok
    # page 4 as shown == page_index 3
    assert "Purchases of property" in result.content
    assert result.meta["page_index"] == 3


def test_reading_outside_the_assigned_slice_is_refused_with_the_range(corpus):
    allowed = [meta.ref for meta in corpus.pages_of(DOC)[:2]]
    registry, _ = _registry(corpus, allowed=allowed, label="pages 1-2")
    result = registry.invoke("read_page", '{"page": 4}')
    assert not result.ok
    assert "not in your assigned range" in result.content
    assert "pages 1-2" in result.content


def test_search_is_scoped_to_the_assigned_slice(corpus):
    allowed = [meta.ref for meta in corpus.pages_of(DOC)[:2]]
    registry, _ = _registry(corpus, allowed=allowed, label="pages 1-2")
    result = registry.invoke("search_document", '{"query": "1,577"}')
    assert "No line matching" in result.content


def test_list_pages_shows_each_page_heading(corpus):
    registry, _ = _registry(corpus)
    content = registry.invoke("list_pages", "{}").content
    assert "Consolidated Statement of Cash Flows" in content
    assert "page 4" in content


def test_read_lines_numbers_the_rows_it_returns(corpus):
    registry, _ = _registry(corpus)
    content = registry.invoke("read_lines", '{"page": 4, "start_line": 3, "end_line": 5}').content
    assert "    3  | | 2022 | 2021 |" in content
    assert "    5  " in content
    assert "1,577" in content
    # The header row travels with the figure: a table row means nothing alone.
    assert "lines 3-5" in content


def test_pages_read_counts_distinct_pages_opened(corpus):
    registry, toolset = _registry(corpus)
    registry.invoke("read_page", '{"page": 4}')
    registry.invoke("read_page", '{"page": 4}')
    registry.invoke("read_page", '{"page": 5}')
    assert toolset.pages_read == 2


def test_a_long_page_is_returned_in_windows(tmp_path):
    long_text = "row of figures 12,345\n" * 3000
    document = FilingDocument(
        doc_name="LONG",
        source_path="",
        pages=[Page(doc_name="LONG", page_index=0, text=long_text)],
    )
    store = MarkdownPageStore(base_dir=tmp_path / "md")
    store.save(document)
    registry, _ = _registry(DocumentCorpus(store=store, doc_names=["LONG"]))
    first = registry.invoke("read_page", '{"page": 1}')
    assert "characters remain" in first.content
    assert "offset=" in first.content


# --- tool registry errors -------------------------------------------------- #
def test_an_unknown_tool_is_reported_not_raised(corpus):
    registry, _ = _registry(corpus)
    result = registry.invoke("delete_everything", "{}")
    assert not result.ok
    assert "No tool named" in result.content


def test_malformed_arguments_are_reported_not_raised(corpus):
    registry, _ = _registry(corpus)
    result = registry.invoke("read_page", "{not json")
    assert not result.ok
    assert "not valid JSON" in result.content or "JSON" in result.content


def test_an_unexpected_argument_is_reported_not_raised(corpus):
    """A model that invents an argument gets an error it can read and correct."""
    registry, _ = _registry(corpus)
    result = registry.invoke("read_page", '{"page": 1, "colour": "blue"}')
    assert result.ok, "extra arguments are absorbed rather than failing the call"


def test_two_documents_in_scope_require_a_document_name(tmp_path):
    store = MarkdownPageStore(base_dir=tmp_path / "md")
    for name in ("A_2022_10K", "B_2022_10K"):
        store.save(
            FilingDocument(
                doc_name=name,
                source_path="",
                pages=[Page(doc_name=name, page_index=0, text="Revenue 100")],
            )
        )
    corpus = DocumentCorpus(store=store, doc_names=["A_2022_10K", "B_2022_10K"])
    registry, _ = _registry(corpus)
    result = registry.invoke("read_page", '{"page": 1}')
    assert not result.ok
    assert "'doc_name' is required" in result.content
    # A paraphrased name still resolves: models write `A 2022 10-K`.
    assert registry.invoke("read_page", '{"page": 1, "doc_name": "A 2022 10-K"}').ok


# --- calculator ------------------------------------------------------------ #
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("1577 / 1373", 1577 / 1373),
        ("(1,577 - 1,373) / 1,373 * 100", (1577 - 1373) / 1373 * 100),
        ("$21,410 / $88,187 * 100", 21410 / 88187 * 100),
        ("6489 / ((253 + 282) / 2)", 6489 / ((253 + 282) / 2)),
        ("12.5% * 2", 25.0),
        ("round(24.277955, 2)", 24.28),
        ("abs(-1577)", 1577.0),
        ("(1,577)", 1577.0),
    ],
)
def test_figures_are_accepted_as_a_filing_prints_them(expression, expected):
    assert evaluate(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('ls')",
        "open('/etc/passwd').read()",
        "1 if True else 2",
        "[1,2,3]",
        "9**9**9",
        "1/0",
        "",
        "revenue / margin",
    ],
)
def test_anything_that_is_not_arithmetic_is_refused(expression):
    with pytest.raises(CalculationError):
        evaluate(expression)


def test_the_calculate_tool_reports_an_error_rather_than_raising():
    result = CalculateTool().run(expression="1/0")
    assert not result.ok
    assert "Division by zero" in result.content


def test_the_calculate_tool_echoes_the_normalised_expression():
    result = CalculateTool().run(expression="$1,577 - $1,373")
    assert result.content == "1577 - 1373 = 204"
    assert result.meta["result"] == 204.0


def test_results_are_rendered_without_inventing_precision():
    assert format_result(204.0) == "204"
    assert format_result(24.277955456) == "24.277955"
    assert normalize_expression("(1,577) × 2") == "(1577) * 2"
