"""The tier boundaries: what escalates, what does not, and what is served.

These are the decisions that decide the rubric score, so they are pinned here
rather than left to the prompts. Every model call is stubbed.
"""

from __future__ import annotations

import pytest

from analyst_copilot.agent.models import (
    AnswerMode,
    EvidenceInput,
    Finding,
    Intent,
    Stage,
)
from analyst_copilot.agent.orchestrator import DeepResult, format_findings
from analyst_copilot.agent.router import IntentRouter, normalize_message
from analyst_copilot.agent.decompose import QuestionDecomposer
from analyst_copilot.agent.conversation import FALLBACK_REPLY, ConversationResponder
from analyst_copilot.agent.pipeline import AnalystAgent
from analyst_copilot.agent.validator import Validation, Verdict
from analyst_copilot.parsing.markdown_store import MarkdownPageStore
from analyst_copilot.parsing.models import FilingDocument, Page
from analyst_copilot.retrieval.models import ScoredPage, SearchResult
from analyst_copilot.services.qa.models import NOT_FOUND_MESSAGE, QAAnswer

from offline_harness import StubCollections, StubDeepSearch, StubValidator, build_agent

DOC = "TESTCO_2022_10K"


class FakeQA:
    """Tier 1. Answers unless the question mentions 'unknown'."""

    def __init__(self, page=59, text="$1,577 million"):
        self.page = page
        self.text = text
        self.questions = []

    def answer_collection(self, question, collection, top_k=None):
        return self._respond(question)

    def answer(self, question, doc_name, filing_path=None):  # noqa: A003
        return self._respond(question)

    def _respond(self, question):
        self.questions.append(question)
        hits = [
            ScoredPage(
                page=Page(doc_name=DOC, page_index=self.page, text="(1,577)"),
                score=0.9,
                rank=1,
            )
        ]
        search = SearchResult(query=question, doc_name=DOC, hits=hits)
        if "unknown" in question.lower():
            return QAAnswer(
                question=question,
                doc_name=DOC,
                answer=NOT_FOUND_MESSAGE,
                found=False,
                retrieval=search,
                abstention_reason="model_abstain",
            )
        return QAAnswer(
            question=question,
            doc_name=DOC,
            answer=self.text,
            found=True,
            page=self.page,
            evidence_snippet="Purchases of property, plant and equipment",
            retrieval=search,
            location_label=f"page {self.page + 1}",
        )


class ExplodingQA:
    def answer(self, question, doc_name, filing_path=None):  # noqa: A003
        raise RuntimeError("retrieval is broken")

    def answer_collection(self, question, collection, top_k=None):
        raise RuntimeError("retrieval is broken")


@pytest.fixture
def markdown(tmp_path, monkeypatch):
    """A real Markdown store the deep path and validator can read."""
    pages = [
        Page(doc_name=DOC, page_index=index, text=text)
        for index, text in {
            0: "# Cover\n\nTESTCO 2022",
            59: (
                "# Consolidated Statement of Cash Flows\n\n"
                "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |"
            ),
        }.items()
    ]
    store = MarkdownPageStore(base_dir=tmp_path / "markdown")
    store.save(FilingDocument(doc_name=DOC, source_path="", pages=pages))
    monkeypatch.setattr(
        "analyst_copilot.agent.pipeline.DocumentCorpus.for_document",
        classmethod(
            lambda cls, doc_name: cls(store=store, doc_names=[doc_name])
        ),
    )
    return store


def _stages(agent, message, **kwargs):
    seen = []
    agent.answer(message, on_stage=seen.append, **kwargs)
    return [event.stage for event in seen]


# --- routing --------------------------------------------------------------- #
def test_a_greeting_never_reaches_retrieval(markdown):
    qa = FakeQA()
    deep = StubDeepSearch()
    agent = build_agent(qa, deep=deep, ready_documents=[DOC])
    answer = agent.answer("Hi", doc_name=DOC)
    assert answer.mode is AnswerMode.CONVERSATIONAL
    assert answer.intent is Intent.SMALLTALK
    assert answer.citation is None
    assert qa.questions == [], "a greeting must not search the filing"
    assert deep.calls == []


def test_a_greeting_is_answered_with_nothing_indexed(markdown):
    agent = build_agent(FakeQA(), ready_documents=[])
    answer = agent.answer("hello there", doc_name=DOC, scope_ready=False)
    assert answer.mode is AnswerMode.CONVERSATIONAL
    assert answer.answer != NOT_FOUND_MESSAGE


def test_a_real_question_with_nothing_indexed_abstains_with_a_fixable_reason(markdown):
    agent = build_agent(FakeQA(), ready_documents=[])
    answer = agent.answer("What was capex?", doc_name=DOC, scope_ready=False)
    assert not answer.found
    assert answer.abstention_reason == "no_indexed_documents"


@pytest.mark.parametrize(
    "message,intent",
    [
        ("Hi", Intent.SMALLTALK),
        ("thanks!", Intent.SMALLTALK),
        ("  HELLO  ", Intent.SMALLTALK),
        ("what can you do?", Intent.CAPABILITY),
        ("who are you", Intent.CAPABILITY),
    ],
)
def test_common_messages_are_classified_without_a_model_call(message, intent):
    routing = IntentRouter(None).route(message)
    assert routing.intent is intent
    assert routing.matched_literally


@pytest.mark.parametrize(
    "message",
    ["hi, what was capex in 2022?", "and the year before?", "capex 2022"],
)
def test_anything_that_might_be_a_question_goes_to_the_document(message):
    """Answering a real question from nothing is the worse error."""
    assert IntentRouter(None).route(message).intent is Intent.DOCUMENT_QUESTION


def test_punctuation_and_case_do_not_defeat_the_literal_match():
    assert normalize_message("  Hello!!  ") == "hello"


def test_a_conversational_reply_still_happens_without_a_model():
    assert ConversationResponder(None).reply("hi") == FALLBACK_REPLY


# --- tier 1 and the validator gate ----------------------------------------- #
def test_a_validated_fast_answer_is_served_without_the_deep_path(markdown):
    deep = StubDeepSearch()
    agent = build_agent(FakeQA(), deep=deep, ready_documents=[DOC])
    answer = agent.answer("What was FY2022 capex?", doc_name=DOC)
    assert answer.found
    assert answer.mode is AnswerMode.FAST
    assert answer.citation.page == 59
    assert deep.calls == [], "tier 3 costs ~50x tier 1; it must not run needlessly"


@pytest.mark.parametrize("verdict", [Verdict.INCORRECT, Verdict.INSUFFICIENT])
def test_an_answer_the_validator_doubts_escalates(markdown, verdict):
    deep = StubDeepSearch()
    agent = build_agent(
        FakeQA(),
        validator=StubValidator(verdict, "wrong fiscal year"),
        deep=deep,
        ready_documents=[DOC],
    )
    answer = agent.answer("What was FY2022 capex?", doc_name=DOC)
    assert deep.calls == ["What was FY2022 capex?"]
    assert answer.mode is AnswerMode.DEEP


def test_an_unchecked_verdict_serves_the_fast_answer(markdown):
    """A broken validator must not escalate every question to a full read."""
    deep = StubDeepSearch()
    agent = build_agent(
        FakeQA(),
        validator=StubValidator(Verdict.UNCHECKED, "provider down"),
        deep=deep,
        ready_documents=[DOC],
    )
    answer = agent.answer("What was FY2022 capex?", doc_name=DOC)
    assert answer.found
    assert answer.mode is AnswerMode.FAST
    assert deep.calls == []


def test_a_fast_abstention_escalates(markdown):
    deep = StubDeepSearch()
    agent = build_agent(FakeQA(), deep=deep, ready_documents=[DOC])
    answer = agent.answer("What is the unknown figure?", doc_name=DOC)
    assert deep.calls == ["What is the unknown figure?"]
    assert answer.abstention_reason == "deep_search_found_nothing"


def test_a_broken_fast_path_escalates_rather_than_failing(markdown):
    deep = StubDeepSearch()
    agent = build_agent(ExplodingQA(), deep=deep, ready_documents=[DOC])
    answer = agent.answer("What was FY2022 capex?", doc_name=DOC)
    assert deep.calls, "a crashed tier 1 is a reason to escalate, not to error"
    assert answer.mode is AnswerMode.DEEP


# --- tier 3 and its verifier ----------------------------------------------- #
def _deep_answer(**overrides):
    base = dict(
        found=True,
        answer="$1,577 million",
        doc_name=DOC,
        page=59,
        quote="| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |",
        reason="the cash flow statement",
        shards_run=7,
        pages_read=61,
    )
    base.update(overrides)
    return DeepResult(**base)


class EscalateThenAccept:
    """Doubts the fast answer, then accepts the deep one. Two different calls."""

    def __init__(self):
        self.calls = []

    def check(self, question, answer, doc_name, page, corpus, computation="", inputs=(), **_extra):
        self.calls.append({"answer": answer, "computation": computation, "inputs": list(inputs)})
        first = len(self.calls) == 1
        return Validation(
            Verdict.INCORRECT if first else Verdict.CORRECT,
            "escalate" if first else "checks out",
        )


def test_a_verified_deep_answer_is_served_with_its_citation(markdown):
    agent = build_agent(
        FakeQA(),
        validator=EscalateThenAccept(),
        deep=StubDeepSearch(_deep_answer()),
        ready_documents=[DOC],
    )
    answer = agent.answer("What was FY2022 capex?", doc_name=DOC)
    assert answer.found
    assert answer.mode is AnswerMode.DEEP
    assert answer.citation.page == 59
    assert answer.pages_read == 61
    assert answer.shards_run == 7


def test_a_deep_answer_the_document_does_not_support_is_refused(markdown):
    """The deterministic verifier is the last word, whatever the agents voted."""
    agent = build_agent(
        FakeQA(),
        validator=StubValidator(Verdict.INCORRECT, "escalate"),
        deep=StubDeepSearch(_deep_answer(answer="$9,999 million")),
        ready_documents=[DOC],
    )
    answer = agent.answer("What was FY2022 capex?", doc_name=DOC)
    assert not answer.found
    assert answer.abstention_reason.startswith("deep_unverified:")


def test_a_derived_deep_answer_verifies_through_its_inputs(markdown):
    validator = EscalateThenAccept()
    agent = build_agent(
        FakeQA(),
        validator=validator,
        deep=StubDeepSearch(
            _deep_answer(
                answer="Capex fell 14.9% year on year.",
                computation="(1577 - 1373) / 1373 * 100",
                inputs=[
                    EvidenceInput("FY2022 capex", "1,577", DOC, 59),
                    EvidenceInput("FY2021 capex", "1,373", DOC, 59),
                ],
            )
        ),
        ready_documents=[DOC],
    )
    answer = agent.answer("How did capex change?", doc_name=DOC)
    assert answer.found, "a computed figure appears on no page; its inputs do"
    assert answer.computation == "(1577 - 1373) / 1373 * 100"
    assert [item.value for item in answer.inputs] == ["1,577", "1,373"]
    # The derivation reaches the validator, so it judges the reasoning instead
    # of hunting for a figure that was never printed.
    assert validator.calls[-1]["computation"] == "(1577 - 1373) / 1373 * 100"
    assert len(validator.calls[-1]["inputs"]) == 2


def test_a_deep_answer_the_validator_doubts_is_withheld(markdown):
    """
    There is no tier after the deep path, so a doubt abstains.

    Measured on the practice key this is the right trade: every deep answer this
    catches was a -1 (a conclusion contradicting its own figures, or the wrong
    period's column), and it becomes a 0 instead.
    """
    agent = build_agent(
        FakeQA(),
        validator=StubValidator(Verdict.INCORRECT, "the figures argue the opposite"),
        deep=StubDeepSearch(_deep_answer()),
        ready_documents=[DOC],
    )
    answer = agent.answer("What was FY2022 capex?", doc_name=DOC)
    assert not answer.found
    assert answer.abstention_reason == "deep_rejected:incorrect"
    assert "the figures argue the opposite" in answer.validation


# --- decomposition --------------------------------------------------------- #
def test_a_single_question_is_never_split():
    result = QuestionDecomposer(None).split("What was FY2022 capex?")
    assert not result.split
    assert result.parts == ["What was FY2022 capex?"]


def test_a_compound_question_gets_one_citation_per_part(markdown):
    class SplittingDecomposer:
        def split(self, question, context=""):
            from analyst_copilot.agent.decompose import Decomposition

            return Decomposition(
                parts=["What was FY2022 capex?", "What was FY2021 capex?"],
                reason="two figures",
                split=True,
            )

    agent = build_agent(FakeQA(), ready_documents=[DOC])
    agent._decomposer = SplittingDecomposer()
    answer = agent.answer("What was capex in FY2022 and FY2021?", doc_name=DOC)
    assert len(answer.parts) == 2
    assert len(answer.citations) == 2
    # The composed text carries both, and is assembled in code rather than by a
    # model, so no figure is rewritten after it was verified.
    assert answer.answer.count("$1,577 million") == 2


# --- progress -------------------------------------------------------------- #
def test_progress_is_reported_in_order(markdown):
    agent = build_agent(FakeQA(), ready_documents=[DOC])
    stages = _stages(agent, "What was FY2022 capex?", doc_name=DOC)
    assert stages[0] is Stage.ROUTING
    assert Stage.RETRIEVING in stages
    assert Stage.VALIDATING in stages
    assert stages[-1] is Stage.DONE


def test_a_failing_progress_callback_never_breaks_an_answer(markdown):
    agent = build_agent(FakeQA(), ready_documents=[DOC])

    def hostile(_event):
        raise RuntimeError("the UI went away")

    answer = agent.answer("What was FY2022 capex?", doc_name=DOC, on_stage=hostile)
    assert answer.found


# --- synthesis input ------------------------------------------------------- #
def test_findings_are_rendered_with_their_provenance():
    findings = [
        Finding(
            found=True,
            answer="$1,577 million",
            doc_name=DOC,
            page=59,
            quote="Purchases of PP&E (1,577)",
            why_authoritative="the cash flow statement",
            confidence=0.9,
        ),
        Finding(
            found=True,
            answer="14.9%",
            doc_name=DOC,
            page=44,
            computation="(1577-1373)/1373*100",
            inputs=[EvidenceInput("FY2022 capex", "1,577", DOC, 59)],
            partial=True,
            confidence=0.6,
        ),
    ]
    rendered = format_findings(findings)
    assert "page 60" in rendered and "page 45" in rendered
    assert "PARTIAL" in rendered
    assert "computed: (1577-1373)/1373*100" in rendered
    assert "FY2022 capex=1,577 (page 60)" in rendered


# --- partials reach the adjudicator ---------------------------------------- #
def test_partials_alone_are_enough_to_run_synthesis():
    """
    A question spanning two statements produces no complete answer from anybody.
    Adjudicating only on complete findings made those questions unanswerable no
    matter how much of the document was read.
    """
    from analyst_copilot.agent.orchestrator import DeepSearchOrchestrator

    findings = [
        Finding(found=False, partial=True, doc_name=DOC,
                inputs=[EvidenceInput("FY2019 revenue", "6,489", DOC, 69)]),
        Finding(found=False, partial=True, doc_name=DOC,
                inputs=[EvidenceInput("FY2019 capex", "116", DOC, 72)]),
        Finding(found=False),
    ]
    result = DeepResult(findings=findings)
    assert result.candidates == [], "neither reader could answer"
    assert len(result.contributions) == 2, "but both hold figures the answer needs"


def test_a_lone_partial_is_never_served_as_a_complete_answer():
    """
    Synthesis is what completes a partial. If it is unavailable, the fallback
    must not promote a fragment -- an incomplete answer served as complete is
    exactly the -1 the pipeline exists to avoid.
    """
    from analyst_copilot.agent.orchestrator import DeepSearchOrchestrator

    class DeadChat:
        @property
        def model_name(self):
            return "dead"

        def complete(self, *a, **k):
            raise RuntimeError("down")

        def complete_with_tools(self, *a, **k):
            raise RuntimeError("down")

    orchestrator = DeepSearchOrchestrator(DeadChat())
    result = DeepResult(
        findings=[
            Finding(found=False, partial=True, answer="6,489", doc_name=DOC,
                    inputs=[EvidenceInput("FY2019 revenue", "6,489", DOC, 69)]),
            Finding(found=False, partial=True, answer="116", doc_name=DOC,
                    inputs=[EvidenceInput("FY2019 capex", "116", DOC, 72)]),
        ]
    )
    orchestrator._synthesize("Capex as a % of revenue?", _StubCorpus(), result, "")
    assert not result.found
    assert "adjudicator" in result.reason


class _StubCorpus:
    """Just enough corpus for synthesis to build its toolset."""

    def available_documents(self):
        return [DOC]

    def all_pages(self):
        return []

    def doc_names(self):
        return [DOC]
