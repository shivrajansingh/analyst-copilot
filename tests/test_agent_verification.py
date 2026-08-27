"""Verifying an agent's answer, and in particular a computed one.

A derived figure appears nowhere in a filing, which is why the original verifier
could never pass one: 43 of the 136 practice questions are numerical reasoning
and every one of them was an abstention by construction. These tests pin the
four conditions that replace "is the number on the page".
"""

from __future__ import annotations

import pytest

from analyst_copilot.agent.models import EvidenceInput
from analyst_copilot.agent.verification import (
    Support,
    check_derivation,
    figures_agree,
    verify_agent_answer,
)

DOC = "TESTCO_2022_10K"

PAGES = {
    (DOC, 44): (
        "Consolidated Statement of Income (Dollars in millions)\n"
        "| Operating income | 21,410 | 22,309 |\n"
        "| Net sales | 88,187 | 79,474 |"
    ),
    (DOC, 60): (
        "Consolidated Statement of Cash Flows (Millions)\n"
        "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |"
    ),
}


def page_text(doc_name, page_index):
    return PAGES.get((doc_name, page_index))


def locate(quote):
    for (doc_name, page_index), text in PAGES.items():
        compact = "".join(c for c in quote.lower() if c.isalnum())
        if len(compact) >= 24 and compact[:200] in "".join(
            c for c in text.lower() if c.isalnum()
        ):
            return doc_name, page_index
    return None


MARGIN_INPUTS = [
    EvidenceInput("Operating income FY2022", "21,410", DOC, 44),
    EvidenceInput("Net sales FY2022", "88,187", DOC, 44),
]
MARGIN_EXPRESSION = "21410 / 88187 * 100"


# --- the four conditions --------------------------------------------------- #
def test_a_sound_derivation_is_accepted(): 
    check = check_derivation(
        "The FY2022 operating margin was 24.3%.", MARGIN_INPUTS, MARGIN_EXPRESSION, page_text
    )
    assert check.ok
    assert check.computed == pytest.approx(24.2779, abs=1e-3)
    assert check.traced_inputs == 2


def test_an_input_that_is_not_on_its_page_is_refused():
    """The one way to fabricate a derived answer is to fabricate an input."""
    check = check_derivation(
        "Margin was 24.9%.",
        [EvidenceInput("Operating income", "21,999", DOC, 44), MARGIN_INPUTS[1]],
        "21999 / 88187 * 100",
        page_text,
    )
    assert not check.ok
    assert "do not appear on the pages" in check.reason


def test_a_computation_using_figures_that_are_not_inputs_is_refused():
    """Real inputs must not launder an unrelated calculation."""
    check = check_derivation(
        "Margin was 30.0%.", MARGIN_INPUTS, "26456 / 88187 * 100", page_text
    )
    assert not check.ok
    assert "not among its recorded inputs" in check.reason


def test_an_answer_that_does_not_state_the_computed_result_is_refused():
    check = check_derivation(
        "The margin was 41.2%.", MARGIN_INPUTS, MARGIN_EXPRESSION, page_text
    )
    assert not check.ok
    assert "does not state the computed result" in check.reason


def test_arithmetic_that_does_not_evaluate_is_refused():
    check = check_derivation("24.3%", MARGIN_INPUTS, "21410 / / 88187", page_text)
    assert not check.ok
    assert "not valid arithmetic" in check.reason


def test_scale_factors_and_rounding_precision_are_not_treated_as_inputs():
    """*100 and round(x, 2) are structure, not figures read off a page."""
    check = check_derivation(
        "24.28%",
        MARGIN_INPUTS,
        "round(21410 / 88187 * 100, 2)",
        page_text,
    )
    assert check.ok


def test_a_derivation_across_two_pages_traces_to_both():
    inputs = [
        EvidenceInput("FY2022 capex", "1,577", DOC, 60),
        EvidenceInput("FY2022 net sales", "88,187", DOC, 44),
    ]
    check = check_derivation(
        "Capex was 1.8% of sales.", inputs, "1577 / 88187 * 100", page_text
    )
    assert check.ok
    assert check.total_inputs == 2


# --- rounding and rescaling ------------------------------------------------ #
@pytest.mark.parametrize(
    "stated,computed",
    [
        (24.3, 24.277955),   # rounded to one decimal
        (24.28, 24.277955),  # rounded to two
        (8.738, 8738.0),     # answered in billions, computed in millions
        (8738.0, 8.738),     # and the other way round
        (0.0, 0.0),
    ],
)
def test_a_stated_figure_may_be_a_rounding_or_a_rescaling(stated, computed):
    assert figures_agree(stated, computed)


@pytest.mark.parametrize("stated,computed", [(41.2, 24.277955), (17.0, 24.277955)])
def test_a_different_figure_is_not_agreement(stated, computed):
    assert not figures_agree(stated, computed)


# --- the end-to-end verdict ------------------------------------------------ #
def test_a_computed_answer_verifies_although_its_figure_is_on_no_page():
    """This is the case the original verifier rejected by construction."""
    assert "24.3" not in "".join(PAGES.values())
    verdict = verify_agent_answer(
        answer="Operating margin was 24.3% in FY2022.",
        doc_name=DOC,
        page=44,
        quote="| Operating income | 21,410 | 22,309 |",
        inputs=MARGIN_INPUTS,
        computation=MARGIN_EXPRESSION,
        page_text=page_text,
        locate_quote=locate,
    )
    assert verdict.ok
    assert verdict.support is Support.DERIVED
    assert verdict.page == 44


def test_a_figure_read_in_billions_verifies_against_a_page_in_millions():
    verdict = verify_agent_answer(
        answer="Capital expenditure was $1.577 billion.",
        doc_name=DOC,
        page=60,
        quote="| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |",
        inputs=[],
        computation="",
        page_text=page_text,
        locate_quote=locate,
    )
    assert verdict.ok
    assert verdict.support is Support.DIRECT


def test_an_unsupported_figure_is_rejected():
    verdict = verify_agent_answer(
        answer="Capital expenditure was $2.9 billion.",
        doc_name=DOC,
        page=60,
        quote="Purchases of property",
        inputs=[],
        computation="",
        page_text=page_text,
        locate_quote=locate,
    )
    assert not verdict.ok
    assert verdict.reason == "number_not_on_page"


def test_a_broken_derivation_reports_why_rather_than_just_failing():
    verdict = verify_agent_answer(
        answer="Operating margin was 41.2%.",
        doc_name=DOC,
        page=44,
        quote="| Operating income | 21,410 | 22,309 |",
        inputs=MARGIN_INPUTS,
        computation=MARGIN_EXPRESSION,
        page_text=page_text,
        locate_quote=locate,
    )
    assert not verdict.ok
    assert verdict.reason.startswith("derivation_failed")
    assert "does not state the computed result" in verdict.reason


def test_a_citation_moves_onto_the_page_that_carries_the_quote():
    """Re-anchoring changes where an answer lives, never what it says."""
    verdict = verify_agent_answer(
        answer="Capital expenditure was $1,577 million.",
        doc_name=DOC,
        page=44,  # wrong page: the quote is on 60
        quote="| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |",
        inputs=[],
        computation="",
        page_text=page_text,
        locate_quote=locate,
    )
    assert verdict.ok
    assert verdict.page == 60
    assert verdict.location_match == "relocated"


def test_an_empty_answer_is_never_verified():
    verdict = verify_agent_answer("", DOC, 44, "", [], "", page_text)
    assert not verdict.ok
    assert verdict.reason == "empty_answer"


def test_an_answer_with_no_figures_rests_on_its_quote():
    verdict = verify_agent_answer(
        answer="The company reports operating income on the income statement.",
        doc_name=DOC,
        page=44,
        quote="Consolidated Statement of Income (Dollars in millions)",
        inputs=[],
        computation="",
        page_text=page_text,
        locate_quote=locate,
    )
    assert verdict.ok
    assert verdict.support is Support.QUOTED
