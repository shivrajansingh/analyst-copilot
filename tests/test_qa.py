from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.models import ScoredPage
from analyst_copilot.services.qa.models import LLMExtraction
from analyst_copilot.services.qa.parser import parse_llm_extraction
from analyst_copilot.services.qa.verifier import AnswerVerifier, LocationMatch


def _hit(
    page_index: int,
    printed_page: int,
    text: str,
    score: float = 1.0,
    rank: int = 1,
) -> ScoredPage:
    return ScoredPage(
        page=Page(
            doc_name="3M_2018_10K",
            page_index=page_index,
            text=text,
            printed_page=printed_page,
        ),
        score=score,
        rank=rank,
    )


def test_parser_reads_json_object():
    raw = '{"not_found": false, "answer": "$1577 million", "page": 60, "evidence_snippet": "PP&E (1,577)", "confidence": 0.9}'
    extraction = parse_llm_extraction(raw)
    assert extraction.not_found is False
    assert extraction.page == 60
    assert "1577" in extraction.answer


def test_parser_handles_fenced_json_and_abstention():
    raw = "```json\n{\"not_found\": true, \"answer\": \"\", \"page\": null}\n```"
    extraction = parse_llm_extraction(raw)
    assert extraction.not_found is True


def test_parser_abstains_on_invalid_json():
    extraction = parse_llm_extraction("I think capex was high.")
    assert extraction.not_found is True


def test_verifier_accepts_number_on_cited_page():
    # citation_page is the 0-based page_index; the printed footer reads 60.
    hits = [
        _hit(
            59,
            60,
            "Consolidated Statement of Cash Flows Purchases of property, plant and equipment (PP&E) (1,577)",
        )
    ]
    extraction = LLMExtraction(
        not_found=False,
        answer="$1,577 million",
        page=59,
        evidence_snippet="Purchases of property, plant and equipment (PP&E)",
    )
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is True
    assert result.page == 59


def test_verifier_rejects_number_missing_from_page():
    hits = [_hit(0, 1, "This page discusses dividends paid of 3,193.")]
    extraction = LLMExtraction(not_found=False, answer="$1,577 million", page=0)
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is False
    assert result.reason == "number_not_on_page"


def test_verifier_cites_the_index_not_the_printed_page_the_model_named():
    """
    The model quoted the footer number; the evidence is one segment away.

    The citation must land on the page index that actually carries the
    evidence, never on the footer number the model echoed -- and the shift is
    reported rather than hidden.
    """
    hits = [_hit(59, 60, "Purchases of property, plant and equipment (PP&E) (1,577)")]
    extraction = LLMExtraction(not_found=False, answer="$1,577 million", page=60)
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is True
    assert result.page == 59
    assert result.cited_page == 60
    assert result.location_match is LocationMatch.ADJUSTED
    assert result.page_shift == 1
    assert result.relocated is True


def test_verifier_rejects_a_loose_number_match_far_from_the_cited_page():
    """Figures alone, sixty pages from the citation, are coincidence not evidence."""
    hits = [_hit(0, 10, "Purchases of property (1,577)")]
    extraction = LLMExtraction(not_found=False, answer="$1,577", page=60)
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is False
    assert result.reason == "evidence_too_far_from_citation"


def test_verifier_relocates_a_distant_citation_when_the_quote_is_verbatim():
    """Quoted evidence found word for word outweighs a wrong page number."""
    page_text = "Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420)"
    hits = [_hit(59, 60, page_text)]
    extraction = LLMExtraction(
        not_found=False,
        answer="$1,577 million",
        page=12,
        evidence_snippet="Purchases of property, plant and equipment (PP&E) (1,577)",
    )
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is True
    assert result.page == 59
    assert result.location_match is LocationMatch.RELOCATED


def test_verifier_prefers_the_page_that_carries_the_quote_over_one_with_the_bare_figure():
    """Two pages hold the figure; only one holds the evidence. Cite that one."""
    hits = [
        _hit(20, 21, "Segment discussion mentions 1,577 in passing.", rank=1),
        _hit(59, 60, "Purchases of property, plant and equipment (PP&E) (1,577)", rank=2),
    ]
    extraction = LLMExtraction(
        not_found=False,
        answer="$1,577 million",
        page=58,
        evidence_snippet="Purchases of property, plant and equipment (PP&E) (1,577)",
    )
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is True
    assert result.page == 59


def test_verifier_rejects_a_wrong_figure_even_on_the_page_the_model_cited():
    """Correct page number, wrong evidence: still a reject."""
    hits = [_hit(59, 60, "Purchases of property, plant and equipment (PP&E) (1,577)")]
    extraction = LLMExtraction(not_found=False, answer="$9,999 million", page=59)
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is False
    assert result.reason == "number_not_on_page"


def test_qa_service_abstains_when_model_not_found():
    from analyst_copilot.services.qa.service import QuestionAnsweringService

    class FakeChat:
        model_name = "fake"

        def complete(self, messages, temperature=0.0, max_tokens=800):
            return '{"not_found": true, "answer": "", "page": null}'

    class FakeSearcher:
        def search(self, bm25_index, vector_index, query, top_k=5):
            from analyst_copilot.retrieval.models import SearchResult

            return SearchResult(
                query=query,
                doc_name="demo",
                hits=[_hit(1, 2, "unrelated text about offices", score=0.9)],
            )

    class FakeIndexer:
        def indices_exist(self, doc_name):
            return True

        def load_indices(self, doc_name):
            return type("Idx", (), {"bm25_index": None, "vector_index": None})()

    service = QuestionAnsweringService(
        indexer=FakeIndexer(),
        searcher=FakeSearcher(),
        chat_client=FakeChat(),
    )
    result = service.answer("What is FY2018 capex?", "demo")
    assert result.found is False
    assert result.answer == "not found in this filing"
    assert result.abstention_reason == "model_abstain"


def test_verifier_accepts_answer_rescaled_to_the_unit_the_question_asked_for():
    """The filing prints millions; the question asked for billions."""
    hits = [_hit(57, 58, "Property, plant and equipment - net 8,738 8,866")]
    for answer in ("8.738", "$8.7 billion", "8,738 million"):
        extraction = LLMExtraction(not_found=False, answer=answer, page=57)
        result = AnswerVerifier().verify(extraction, hits)
        assert result.ok is True, answer
        assert result.page == 57


def test_verifier_still_rejects_a_figure_that_is_not_on_the_page():
    hits = [_hit(0, 1, "This page discusses dividends paid of 3,193 and 1,204.")]
    extraction = LLMExtraction(not_found=False, answer="$1,577 million", page=0)
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is False
    assert result.reason == "number_not_on_page"


def test_verifier_rejects_a_derived_figure_that_appears_nowhere():
    """A computed ratio has no source figure to trace back to."""
    hits = [_hit(0, 1, "Revenue 6,489 Property, plant and equipment - net 253 282")]
    extraction = LLMExtraction(not_found=False, answer="24.26", page=0)
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is False
    assert result.reason == "number_not_on_page"


def test_verifier_does_not_let_a_two_digit_figure_match_anything():
    hits = [_hit(0, 1, "Segment results 12 34 56 78 91")]
    extraction = LLMExtraction(not_found=False, answer="65 consecutive years", page=0)
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is False
    assert result.reason == "number_not_on_page"


def test_significant_digits_is_scale_free():
    from analyst_copilot.services.qa.verifier import significant_digits

    assert significant_digits("8,738") == "8738"
    assert significant_digits("8.70") == "87"
    assert significant_digits("(1,577)") == "1577"
    assert significant_digits("0.096") == "96"
