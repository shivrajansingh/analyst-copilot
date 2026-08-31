"""Offline stand-ins for the agent harness, shared by the HTTP contract tests.

`QuestionDecomposer` and `ConversationResponder` need no stubbing: each takes an
optional chat client and has a documented behaviour without one — nothing is ever
split, and a greeting still gets a reply. The planner, the checker and the
fan-out all have to call a model, so they are replaced here.

This exists so the API tests exercise the real pipeline rather than a mock of
it. What is under test is the HTTP contract over the actual brain, with the
network removed.
"""

from __future__ import annotations

from typing import Optional, Sequence

from analyst_copilot.agent import AnalystAgent
from analyst_copilot.agent.conversation import (
    FALLBACK_REPLY,
    ConversationReply,
    ConversationResponder,
)
from analyst_copilot.agent.decompose import QuestionDecomposer
from analyst_copilot.agent.models import Stage, StageEvent
from analyst_copilot.agent.orchestrator import DeepResult
from analyst_copilot.agent.planner import Plan, PlanKind
from analyst_copilot.agent.recall import HistoryTurn, Recollection
from analyst_copilot.agent.trace import AgentStatus, agent_status, thought, tool_call
from analyst_copilot.agent.validator import Validation, Verdict


#: Messages a stub may treat as greetings. A test double is allowed to be dumb
#: about this; the real planner asks a model precisely so it need not be.
_STUB_GREETINGS = frozenset({"hi", "hello", "hey", "thanks", "thank you"})


class StubPlanner:
    """
    Plans without a model.

    By default it classifies with a two-line rule and never narrows the search,
    which keeps the HTTP tests exercising the real pipeline. Pass `kind` or
    `documents` to pin a specific decision.
    """

    def __init__(self, kind=None, documents=(), question=None):
        self.kind = kind
        self.documents = list(documents)
        self.question = question
        self.calls = []

    def plan(self, message, cards=(), history="") -> Plan:
        self.calls.append(message)
        kind = self.kind
        if kind is None:
            stripped = message.strip().lower().rstrip("!?.")
            kind = PlanKind.SMALLTALK if stripped in _STUB_GREETINGS else PlanKind.DOCUMENT
        return Plan(
            kind=kind,
            question=self.question or message,
            documents=list(self.documents),
            confidence=1.0,
            reason="stubbed",
        )


class StubResponder:
    """
    Replies without a model.

    Echoes the facts it was handed, so a test can assert that the right ones were
    computed; or asks for the document, so the escape hatch can be exercised.
    """

    def __init__(self, needs_document: bool = False, text: Optional[str] = None) -> None:
        self.needs_document = needs_document
        self.text = text
        self.facts = []

    def reply(self, message, collection=None, documents=(), history="", facts="") -> ConversationReply:
        self.facts.append(facts)
        if self.needs_document:
            return ConversationReply(needs_document=True)
        return ConversationReply(text=self.text if self.text is not None else (facts or FALLBACK_REPLY))


class StubRecaller:
    """
    Recalls without a model.

    Declines by default, which is what makes every existing test behave as it
    did before recall existed: a `history` plan that finds nothing falls through
    to the ordinary search.
    """

    def __init__(self, recollection: Optional[Recollection] = None) -> None:
        self.recollection = recollection or Recollection(reason="stubbed: nothing recalled")
        self.calls = []

    def recall(self, message, history) -> Recollection:
        self.calls.append((message, list(history or [])))
        return self.recollection


class StubValidator:
    """Validates nothing and, by default, lets the fast answer through."""

    def __init__(self, verdict: Verdict = Verdict.CORRECT, reason: str = "stubbed") -> None:
        self.verdict = verdict
        self.reason = reason
        self.calls = []

    # `**_extra` on purpose: these doubles stand in for collaborators whose
    # signatures grow (a derivation, a trace callback), and a test that fails
    # because a new optional argument was added is testing the wrong thing.
    def check(self, question, answer, doc_name, page, corpus, **_extra) -> Validation:
        self.calls.append((question, answer, page))
        return Validation(self.verdict, self.reason)


class StubDeepSearch:
    """Stands in for the fan-out. Reports nothing unless a result is given."""

    def __init__(self, result: Optional[DeepResult] = None) -> None:
        self.result = result
        self.calls = []
        #: What scope each call was given, so a test can assert the planner's
        #: choice actually reached the fan-out.
        self.scopes = []

    def search(
        self, question, corpus, context="", on_stage=None, on_trace=None,
        only=None, excluding=None, **_extra
    ) -> DeepResult:
        self.calls.append(question)
        self.scopes.append({"only": list(only or []), "excluding": list(excluding or [])})
        if on_stage is not None:
            on_stage(StageEvent(Stage.DEEP_SEARCH, "reading", done=1, total=1))
        if on_trace is not None:
            on_trace(agent_status("reader 1", AgentStatus.RUNNING))
            on_trace(thought("reader 1", "Checking the cash flow statement."))
            on_trace(tool_call("reader 1", "search_document"))
            on_trace(agent_status("reader 1", AgentStatus.EMPTY))
        return self.result or DeepResult(
            found=False,
            reason="stubbed deep search found nothing",
            shards_run=1,
            pages_read=3,
        )


class StubCollections:
    """A collection indexer that reports whatever documents it was given."""

    def __init__(self, ready: Sequence[str] = ()) -> None:
        self.ready = list(ready)

    def ready_documents(self, collection):
        return list(self.ready)


def build_agent(
    qa,
    validator: Optional[StubValidator] = None,
    deep: Optional[StubDeepSearch] = None,
    collections: Optional[StubCollections] = None,
    ready_documents: Sequence[str] = (),
    planner: Optional[StubPlanner] = None,
    recaller: Optional[StubRecaller] = None,
    responder=None,
) -> AnalystAgent:
    """The real harness with every model call stubbed out."""
    return AnalystAgent(
        qa_service=qa,
        chat_client=None,
        collection_indexer=collections or StubCollections(ready_documents),
        planner=planner or StubPlanner(),
        decomposer=QuestionDecomposer(None),
        validator=validator or StubValidator(),
        orchestrator=deep or StubDeepSearch(),
        responder=responder or ConversationResponder(None),
        recaller=recaller or StubRecaller(),
    )
