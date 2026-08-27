"""Offline stand-ins for the agent harness, shared by the HTTP contract tests.

The harness's cheap collaborators need no stubbing at all: `IntentRouter`,
`QuestionDecomposer` and `ConversationResponder` each take an optional chat
client and have a documented, deterministic behaviour without one — greetings
still match literally, questions still route to the document, nothing is ever
split, and a greeting still gets a reply. Only the two that must call a model
are replaced here.

This exists so the API tests exercise the real pipeline rather than a mock of
it. What is under test is the HTTP contract over the actual brain, with the
network removed.
"""

from __future__ import annotations

from typing import Optional, Sequence

from analyst_copilot.agent import AnalystAgent
from analyst_copilot.agent.conversation import ConversationResponder
from analyst_copilot.agent.decompose import QuestionDecomposer
from analyst_copilot.agent.models import Stage, StageEvent
from analyst_copilot.agent.orchestrator import DeepResult
from analyst_copilot.agent.router import IntentRouter
from analyst_copilot.agent.validator import Validation, Verdict


class StubValidator:
    """Validates nothing and, by default, lets the fast answer through."""

    def __init__(self, verdict: Verdict = Verdict.CORRECT, reason: str = "stubbed") -> None:
        self.verdict = verdict
        self.reason = reason
        self.calls = []

    def check(
        self,
        question,
        answer,
        doc_name,
        page,
        corpus,
        page_label="",
        evidence_snippet="",
        computation="",
        inputs=(),
    ) -> Validation:
        self.calls.append((question, answer, page))
        return Validation(self.verdict, self.reason)


class StubDeepSearch:
    """Stands in for the fan-out. Reports nothing unless a result is given."""

    def __init__(self, result: Optional[DeepResult] = None) -> None:
        self.result = result
        self.calls = []

    def search(self, question, corpus, context="", on_stage=None) -> DeepResult:
        self.calls.append(question)
        if on_stage is not None:
            on_stage(StageEvent(Stage.DEEP_SEARCH, "reading", done=1, total=1))
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
) -> AnalystAgent:
    """The real harness with every model call stubbed out."""
    return AnalystAgent(
        qa_service=qa,
        chat_client=None,
        collection_indexer=collections or StubCollections(ready_documents),
        router=IntentRouter(None),
        decomposer=QuestionDecomposer(None),
        validator=validator or StubValidator(),
        orchestrator=deep or StubDeepSearch(),
        responder=ConversationResponder(None),
    )
