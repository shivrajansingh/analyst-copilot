"""The planner: cards, facts, and the guard that stops it narrowing too far.

No model calls. `PlanningChat` returns a fixed JSON reply, so the reconciliation
logic — the part that can lose an answer — is tested exactly.
"""

from __future__ import annotations

import json

import pytest

from analyst_copilot.agent.cards import (
    card_for,
    cards_for,
    describe_cards,
    documents_covering,
    years_mentioned,
)
from analyst_copilot.agent.facts import corpus_facts
from analyst_copilot.agent.planner import Plan, PlanKind, Planner
from analyst_copilot.llm.base import ChatClient

THREE_YEARS = ["3M_2018_10K", "3M_2022_10K", "3M_2023Q2_10Q"]


class PlanningChat(ChatClient):
    """Returns one fixed plan, and records what it was asked."""

    def __init__(self, payload, raw=None):
        self.payload = payload
        self.raw = raw
        self.prompts = []

    @property
    def model_name(self) -> str:
        return "planning"

    def complete(self, messages, temperature=0.0, max_tokens=800):
        self.prompts.append(messages[-1]["content"])
        return self.raw if self.raw is not None else json.dumps(self.payload)


class BrokenChat(ChatClient):
    @property
    def model_name(self) -> str:
        return "broken"

    def complete(self, messages, temperature=0.0, max_tokens=800):
        raise RuntimeError("provider down")


def _plan(payload, message="What was FY2018 revenue?", documents=THREE_YEARS, **kwargs):
    chat = PlanningChat(payload)
    planner = Planner(chat, **kwargs)
    return planner.plan(message, cards_for(documents)), chat


# --- document cards -------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,company,year,quarter,kind,covers",
    [
        ("3M_2018_10K", "3M", 2018, None, "10-K", [2018, 2017, 2016]),
        ("3M_2023Q2_10Q", "3M", 2023, 2, "10-Q", [2023, 2022]),
        ("FOOTLOCKER_2022_8K_dated-2022-05-20", "FOOTLOCKER", 2022, None, "8-K", [2022]),
        ("JOHNSON_JOHNSON_2022_10K", "JOHNSON JOHNSON", 2022, None, "10-K", [2022, 2021, 2020]),
    ],
)
def test_a_card_is_read_from_the_filename(name, company, year, quarter, kind, covers):
    card = card_for(name)
    assert card.company == company
    assert card.fiscal_year == year
    assert card.quarter == quarter
    assert card.doc_type == kind
    assert card.covers == covers


def test_a_ten_k_reports_three_years_not_one():
    """
    The field that earns its keep. A 2019 10-K answers a 2017 question, and a
    planner reasoning only from "this is the 2019 filing" would send that
    question to the wrong document or to none.
    """
    assert 2017 in card_for("ACTIVISIONBLIZZARD_2019_10K").covers


def test_an_unreadable_filename_yields_a_card_that_excludes_nothing():
    card = card_for("document1.pdf")
    assert not card.described
    assert "cannot be ruled out" in card.describe()
    # And it is offered for every year, so it can never be scoped away.
    assert "document1.pdf" in documents_covering([card], 1999)


def test_documents_covering_includes_the_undescribed():
    cards = cards_for(["3M_2018_10K", "mystery"])
    assert documents_covering(cards, 2018) == ["3M_2018_10K", "mystery"]
    assert documents_covering(cards, 2022) == ["mystery"]


def test_years_are_read_from_a_question():
    assert years_mentioned("What was FY2018 revenue?") == [2018]
    assert years_mentioned("compare 2018 with 2022") == [2018, 2022]
    assert years_mentioned("what was revenue") == []


# --- corpus facts ---------------------------------------------------------- #
def test_facts_are_computed_not_left_to_the_model():
    facts = corpus_facts(cards_for(THREE_YEARS, {"3M_2018_10K": 131}), "3M multi-year")
    assert "Number of documents loaded: 3" in facts
    assert "Companies: 3M" in facts
    # The years the documents are named for, and the years they report, are
    # different lists -- and the second is the one an analyst actually asks about.
    assert "Fiscal years of the documents themselves: 2023, 2022, 2018" in facts
    assert "2016" in facts


def test_facts_on_an_empty_set_say_so():
    assert "0" in corpus_facts([])


# --- the plan -------------------------------------------------------------- #
def test_a_plan_is_read_back_from_the_model():
    plan, chat = _plan(
        {
            "kind": "document",
            "question": "What was 3M's revenue in FY2018?",
            "documents": ["3M_2018_10K"],
            "confidence": 0.95,
            "reason": "only the 2018 filing reports FY2018",
        }
    )
    assert plan.kind is PlanKind.DOCUMENT
    assert plan.question == "What was 3M's revenue in FY2018?"
    assert plan.documents == ["3M_2018_10K"]
    # The cards reach the prompt, or the planner is choosing blind.
    assert "reports figures for 2018, 2017, 2016" in chat.prompts[0]


@pytest.mark.parametrize("kind", ["smalltalk", "capability", "corpus_meta"])
def test_the_non_document_kinds_are_carried_through(kind):
    plan, _ = _plan({"kind": kind, "question": "hi", "documents": []}, message="hi")
    assert plan.kind is PlanKind(kind)
    assert not plan.kind.needs_documents


# --- the scope guard: what stops it losing an answer ----------------------- #
def test_a_document_that_reports_the_year_is_put_back():
    """
    Cards are filename hints. A hint must not be able to exclude a document that
    demonstrably reports the year the question asks about.
    """
    plan, _ = _plan(
        {
            "kind": "document",
            "question": "What was revenue in FY2022?",
            "documents": ["3M_2022_10K"],
            "confidence": 0.95,
        },
        message="What was revenue in FY2022?",
    )
    # The Q2 2023 filing reports 2022 as its prior-year column, so it stays in.
    assert plan.documents == ["3M_2022_10K", "3M_2023Q2_10Q"]


def test_low_confidence_searches_everything():
    plan, _ = _plan(
        {"kind": "document", "question": "q", "documents": ["3M_2018_10K"], "confidence": 0.4}
    )
    assert plan.documents == [], "an unsure narrowing is no narrowing"


def test_no_named_year_searches_everything_under_the_careful_policy():
    plan, _ = _plan(
        {
            "kind": "document",
            "question": "What was revenue last year?",
            "documents": ["3M_2018_10K"],
            "confidence": 0.99,
        },
        message="What was revenue last year?",
    )
    assert plan.documents == []


def test_the_bolder_policy_narrows_without_a_named_year():
    plan, _ = _plan(
        {
            "kind": "document",
            "question": "What was revenue last year?",
            "documents": ["3M_2022_10K"],
            "confidence": 0.99,
        },
        message="What was revenue last year?",
        require_named_year=False,
    )
    assert plan.documents == ["3M_2022_10K"]


def test_an_invented_document_name_is_dropped():
    plan, _ = _plan(
        {"kind": "document", "question": "q", "documents": ["NOT_A_REAL_FILE"], "confidence": 0.99}
    )
    assert plan.documents == []


def test_scoping_to_every_document_is_no_scope_at_all():
    plan, _ = _plan(
        {"kind": "document", "question": "q", "documents": list(THREE_YEARS), "confidence": 0.99}
    )
    assert plan.documents == []
    assert not plan.scoped


def test_a_single_document_set_is_never_scoped():
    plan, _ = _plan(
        {"kind": "document", "question": "q", "documents": ["3M_2018_10K"], "confidence": 0.99},
        documents=["3M_2018_10K"],
    )
    assert plan.documents == []


def test_scoping_can_be_switched_off_entirely():
    plan, _ = _plan(
        {
            "kind": "document",
            "question": "What was FY2018 revenue?",
            "documents": ["3M_2018_10K"],
            "confidence": 0.99,
        },
        scope_documents=False,
    )
    assert plan.documents == []


# --- failure ---------------------------------------------------------------- #
def test_unparseable_output_becomes_a_document_question():
    chat = PlanningChat({}, raw="I think this is about revenue, probably.")
    plan = Planner(chat).plan("What was revenue?", cards_for(THREE_YEARS))
    assert plan.kind is PlanKind.DOCUMENT
    assert plan.documents == []
    assert plan.assumed


def test_an_unknown_kind_becomes_a_document_question():
    plan, _ = _plan({"kind": "vibes", "question": "q", "documents": []})
    assert plan.kind is PlanKind.DOCUMENT
    assert plan.assumed


def test_a_dead_provider_becomes_a_document_question():
    plan = Planner(BrokenChat()).plan("What was revenue?", cards_for(THREE_YEARS))
    assert plan.kind is PlanKind.DOCUMENT
    assert plan.documents == []
    assert "provider down" in plan.reason


def test_no_model_at_all_becomes_a_document_question():
    plan = Planner(None).plan("hi")
    assert plan.kind is PlanKind.DOCUMENT
    assert plan.assumed
