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
from analyst_copilot.agent.planner import PlanKind
from analyst_copilot.agent.recall import HistoryTurn, Recollection
from analyst_copilot.config.settings import get_settings
from analyst_copilot.agent.decompose import QuestionDecomposer
from analyst_copilot.agent.conversation import FALLBACK_REPLY, ConversationResponder
from analyst_copilot.agent.pipeline import AnalystAgent
from analyst_copilot.agent.validator import Validation, Verdict
from analyst_copilot.parsing.markdown_store import MarkdownPageStore
from analyst_copilot.parsing.models import FilingDocument, Page
from analyst_copilot.retrieval.models import ScoredPage, SearchResult
from analyst_copilot.services.qa.models import NOT_FOUND_MESSAGE, QAAnswer

from offline_harness import (
    StubCollections,
    StubDeepSearch,
    StubPlanner,
    StubRecaller,
    StubResponder,
    StubValidator,
    build_agent,
)

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


# --- planning, and the escapes that stop a bad plan being final ------------ #
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
    answer = agent.answer("hello", doc_name=DOC, scope_ready=False)
    assert answer.mode is AnswerMode.CONVERSATIONAL
    assert answer.answer != NOT_FOUND_MESSAGE


def test_a_real_question_with_nothing_indexed_abstains_with_a_fixable_reason(markdown):
    agent = build_agent(FakeQA(), ready_documents=[])
    answer = agent.answer("What was capex?", doc_name=DOC, scope_ready=False)
    assert not answer.found
    assert answer.abstention_reason == "no_indexed_documents"


def test_the_planner_researches_the_resolved_question_not_the_message(markdown):
    """
    "and the year before?" cannot be retrieved for. Resolving it once at the top
    means every stage below gets a question that stands on its own -- including
    the checker, which sees no history at all.
    """
    qa = FakeQA()
    agent = build_agent(
        qa,
        planner=StubPlanner(question="What was 3M's capital expenditure in FY2017?"),
        ready_documents=[DOC],
    )
    answer = agent.answer("and the year before?", doc_name=DOC)
    assert qa.questions == ["What was 3M's capital expenditure in FY2017?"]
    # The message the analyst typed is what gets shown back to them.
    assert answer.question == "and the year before?"


class NeedsDocumentResponder:
    """A reply that hands the message back. The first escape."""

    def __init__(self):
        self.calls = 0

    def reply(self, message, collection=None, documents=(), history="", facts=""):
        from analyst_copilot.agent.conversation import ConversationReply

        self.calls += 1
        return ConversationReply(needs_document=True)


def test_a_misclassified_question_is_handed_back_and_searched(markdown):
    """
    The one planner mistake that cannot be recovered from is sending a real
    question down the chat path, where it is answered from nothing. So the reply
    is allowed to refuse, and the question is then researched properly.
    """
    qa = FakeQA()
    responder = NeedsDocumentResponder()
    agent = build_agent(
        qa,
        planner=StubPlanner(kind=PlanKind.SMALLTALK),
        ready_documents=[DOC],
    )
    agent._responder = responder

    answer = agent.answer("What was FY2018 capex?", doc_name=DOC)
    assert responder.calls == 1, "the chat path was tried"
    assert qa.questions == ["What was FY2018 capex?"], "and then the filing was searched"
    assert answer.found
    assert answer.mode is AnswerMode.FAST


def test_a_corpus_question_is_answered_without_searching(markdown):
    """A question about the document set is answered from the manifest."""
    qa = FakeQA()
    deep = StubDeepSearch()
    agent = build_agent(
        qa,
        planner=StubPlanner(kind=PlanKind.CORPUS_META),
        deep=deep,
        ready_documents=[DOC],
    )
    answer = agent.answer("How many documents do you have?", doc_name=DOC)
    assert answer.mode is AnswerMode.CONVERSATIONAL
    assert qa.questions == []
    assert deep.calls == []


def test_a_planner_that_fails_sends_the_question_to_the_document(markdown):
    """
    The safe direction. Searching a filing for a greeting wastes seconds;
    answering a real question without reading the filing invents something.
    """
    from analyst_copilot.agent.planner import Planner

    class DeadChat:
        @property
        def model_name(self):
            return "dead"

        def complete(self, *a, **k):
            raise RuntimeError("provider down")

    plan = Planner(DeadChat()).plan("anything at all")
    assert plan.kind is PlanKind.DOCUMENT
    assert plan.documents == [], "and over every document"
    assert plan.assumed


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
    assert stages[0] is Stage.PLANNING
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


# --- scoping, and the widen escape ---------------------------------------- #
OTHER = "TESTCO_2019_10K"


@pytest.fixture
def markdown_pair(tmp_path, monkeypatch):
    """
    Two documents in one filing set.

    Scoping cannot be tested with one document: `scoped_documents` ignores a
    scope that matches nothing, so a single-document corpus always searches
    itself whatever the planner asked for.
    """
    store = MarkdownPageStore(base_dir=tmp_path / "markdown")
    store.save(
        FilingDocument(
            doc_name=DOC,
            source_path="",
            pages=[
                Page(doc_name=DOC, page_index=59, text=(
                    "# Consolidated Statement of Cash Flows\n\n"
                    "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |"
                ))
            ],
        )
    )
    store.save(
        FilingDocument(
            doc_name=OTHER,
            source_path="",
            pages=[Page(doc_name=OTHER, page_index=0, text="# Cover\n\nTESTCO 2019")],
        )
    )
    monkeypatch.setattr(
        "analyst_copilot.agent.pipeline.DocumentCorpus.for_collection",
        classmethod(lambda cls, name, docs: cls(store=store, doc_names=list(docs), collection=name)),
    )
    return store

class ScopedDeepSearch:
    """Finds the answer only when the search is *not* scoped to FY2022."""

    def __init__(self, answer_in="3M_2018_10K"):
        self.answer_in = answer_in
        self.scopes = []

    def search(self, question, corpus, context="", on_stage=None, on_trace=None,
               only=None, excluding=None, **_extra):
        self.scopes.append({"only": list(only or []), "excluding": list(excluding or [])})
        reachable = corpus.scoped_documents(only=only, excluding=excluding)
        if self.answer_in not in reachable:
            return DeepResult(found=False, reason="nothing here", shards_run=2, pages_read=20)
        return DeepResult(
            found=True,
            answer="$1,577 million",
            doc_name=DOC,
            page=59,
            quote="| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |",
            shards_run=3,
            pages_read=30,
        )


def test_a_scoped_search_that_finds_nothing_widens(markdown_pair):
    """
    The escape that makes a wrong scope cost time instead of the answer. The
    planner picks the wrong document of the two; the one it skipped is read
    before the system gives up.
    """
    deep = ScopedDeepSearch(answer_in=DOC)
    agent = build_agent(
        FakeQA(),
        planner=StubPlanner(documents=[OTHER]),
        # Doubts the fast answer so the deep path runs, then accepts what the
        # widened search found.
        validator=EscalateThenAccept(),
        deep=deep,
        ready_documents=[DOC, OTHER],
    )
    answer = agent.answer("What was FY2018 capex?", collection="SET")

    assert len(deep.scopes) == 2, "it tried the scope, then widened past it"
    assert deep.scopes[0]["only"] == [OTHER]
    assert deep.scopes[1]["excluding"] == [OTHER]
    assert answer.found, "the answer was reachable and must not be lost"
    # The cost of both passes is reported, not just the second.
    assert answer.pages_read == 50
    assert answer.shards_run == 5


def test_the_planners_scope_reaches_the_fan_out(markdown_pair):
    deep = StubDeepSearch()
    agent = build_agent(
        FakeQA(),
        planner=StubPlanner(documents=[DOC]),
        validator=StubValidator(Verdict.INCORRECT, "escalate"),
        deep=deep,
        ready_documents=[DOC, OTHER],
    )
    agent.answer("What was FY2018 capex?", collection="SET")
    assert deep.scopes[0]["only"] == [DOC]


def test_an_unscoped_search_never_widens(markdown):
    """Nothing was skipped, so there is nothing to widen to."""
    deep = StubDeepSearch()
    agent = build_agent(
        FakeQA(),
        validator=StubValidator(Verdict.INCORRECT, "escalate"),
        deep=deep,
        ready_documents=[DOC],
    )
    agent.answer("What was FY2018 capex?", doc_name=DOC)
    assert len(deep.calls) == 1
    assert deep.scopes[0]["only"] == []


# --- the third path: answering from the thread ------------------------------ #
# A `history` plan is the only kind that gets a second opinion before it is
# trusted. These pin both outcomes: a restatement that keeps the original
# citation, and the fall-through that makes a wrong `history` cost one call.
CAPEX_THREAD = [
    {"role": "user", "content": "What was FY2018 capex?"},
    {
        "role": "assistant",
        "content": "FY2018 capital expenditure was $1,577 million.",
        "found": True,
        "page": 59,
        "doc_name": DOC,
    },
]


def test_a_recalled_answer_is_served_without_searching(markdown):
    qa = FakeQA()
    deep = StubDeepSearch()
    agent = build_agent(
        qa,
        deep=deep,
        ready_documents=[DOC],
        planner=StubPlanner(kind=PlanKind.HISTORY),
        recaller=StubRecaller(
            Recollection(
                found=True,
                answer="$1,577 million.",
                source=HistoryTurn(
                    role="assistant",
                    content="FY2018 capital expenditure was $1,577 million.",
                    found=True,
                    page=59,
                    doc_name=DOC,
                ),
                reason="asked again",
            )
        ),
    )
    answer = agent.answer("what was that capex figure again?", doc_name=DOC, history=CAPEX_THREAD)

    assert answer.found
    assert answer.answer == "$1,577 million."
    assert answer.recalled
    assert qa.questions == [], "a restatement must not search the filing"
    assert deep.calls == []


def test_a_recalled_answer_carries_the_original_page(markdown):
    agent = build_agent(
        FakeQA(),
        ready_documents=[DOC],
        planner=StubPlanner(kind=PlanKind.HISTORY),
        recaller=StubRecaller(
            Recollection(
                found=True,
                answer="$1,577 million.",
                source=HistoryTurn("assistant", "…$1,577 million.", True, 59, DOC),
            )
        ),
    )
    answer = agent.answer("say that again", doc_name=DOC, history=CAPEX_THREAD)

    assert answer.citation is not None
    assert answer.citation.page == 59
    assert answer.citation.doc_name == DOC
    assert answer.citations == [answer.citation]


def test_a_failed_recall_falls_through_to_the_search(markdown):
    qa = FakeQA()
    recaller = StubRecaller()  # declines
    agent = build_agent(
        qa,
        ready_documents=[DOC],
        planner=StubPlanner(kind=PlanKind.HISTORY),
        recaller=recaller,
    )
    answer = agent.answer("what was FY2017 capex?", doc_name=DOC, history=CAPEX_THREAD)

    assert recaller.calls, "recall must be consulted before the search"
    assert qa.questions, "a history plan that recalls nothing must still be searched"
    assert not answer.recalled


def test_recall_sees_the_untruncated_thread(markdown):
    recaller = StubRecaller()
    agent = build_agent(
        FakeQA(),
        ready_documents=[DOC],
        planner=StubPlanner(kind=PlanKind.HISTORY),
        recaller=recaller,
    )
    agent.answer("what was that again?", doc_name=DOC, history=CAPEX_THREAD)

    _, seen = recaller.calls[0]
    assert seen == CAPEX_THREAD, "recall needs the stored turns, not the trimmed context"


def test_recall_can_be_switched_off(markdown):
    qa = FakeQA()
    recaller = StubRecaller()
    settings = get_settings()
    agent = AnalystAgent(
        qa_service=qa,
        chat_client=None,
        collection_indexer=StubCollections([DOC]),
        settings=settings.model_copy(update={"planner_recall_history": False}),
        planner=StubPlanner(kind=PlanKind.HISTORY),
        decomposer=QuestionDecomposer(None),
        validator=StubValidator(),
        orchestrator=StubDeepSearch(),
        responder=ConversationResponder(None),
        recaller=recaller,
    )
    agent.answer("what was that again?", doc_name=DOC, history=CAPEX_THREAD)

    assert recaller.calls == [], "the thread must not be consulted when recall is off"
    assert qa.questions, "the message is searched like any other question"


def test_an_ordinary_question_never_consults_the_thread(markdown):
    recaller = StubRecaller()
    agent = build_agent(FakeQA(), ready_documents=[DOC], recaller=recaller)
    agent.answer("What was capex?", doc_name=DOC, history=CAPEX_THREAD)
    assert recaller.calls == []


# --- questions about the conversation itself -------------------------------- #
# "what was the first question?" cannot be answered by any filing. Reading every
# page to fail is the worst outcome the planner can produce, so this path is the
# one place the NEEDS_DOCUMENT escape is deliberately not honoured.
def test_a_question_about_the_thread_never_searches(markdown):
    qa = FakeQA()
    deep = StubDeepSearch()
    agent = build_agent(
        qa, deep=deep, ready_documents=[DOC], planner=StubPlanner(kind=PlanKind.THREAD_META)
    )
    answer = agent.answer("what was the 1st question?", doc_name=DOC, history=CAPEX_THREAD)

    assert qa.questions == [], "the filing must not be searched for what was typed"
    assert deep.calls == []
    assert answer.mode is AnswerMode.CONVERSATIONAL
    assert answer.intent is Intent.CAPABILITY


def test_an_empty_thread_says_nothing_was_asked(markdown):
    responder = StubResponder()  # echoes the facts it is given
    agent = build_agent(
        FakeQA(),
        ready_documents=[DOC],
        planner=StubPlanner(kind=PlanKind.THREAD_META),
        responder=responder,
    )
    answer = agent.answer("what was the last question?", doc_name=DOC, history=[])
    assert "No question has been asked yet" in answer.answer


def test_the_thread_facts_name_the_first_question(markdown):
    responder = StubResponder()
    agent = build_agent(
        FakeQA(),
        ready_documents=[DOC],
        planner=StubPlanner(kind=PlanKind.THREAD_META),
        responder=responder,
    )
    agent.answer("what was the 1st question?", doc_name=DOC, history=CAPEX_THREAD)
    assert 'The first question was: "What was FY2018 capex?"' in responder.facts[0]


def test_a_thread_question_that_asks_for_the_document_is_still_not_searched(markdown):
    """The escape hatch is refused here: no filing can hold the transcript."""
    qa = FakeQA()
    agent = build_agent(
        qa,
        ready_documents=[DOC],
        planner=StubPlanner(kind=PlanKind.THREAD_META),
        responder=StubResponder(needs_document=True),
    )
    answer = agent.answer("what did I just ask?", doc_name=DOC, history=CAPEX_THREAD)
    assert qa.questions == []
    assert "What was FY2018 capex?" in answer.answer


def test_a_corpus_question_keeps_its_escape(markdown):
    """Only thread_meta loses the escape — corpus_meta can still hand back."""
    qa = FakeQA()
    agent = build_agent(
        qa,
        ready_documents=[DOC],
        planner=StubPlanner(kind=PlanKind.CORPUS_META),
        responder=StubResponder(needs_document=True),
    )
    agent.answer("how many segments does it report?", doc_name=DOC)
    assert qa.questions, "a corpus_meta message that needs the filing must reach it"
