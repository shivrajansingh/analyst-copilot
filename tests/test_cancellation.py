"""Stopping a run, and proving it stopped.

The interesting assertions here are not about the UI or the event: they are
about *spend*. A stop that hides the answer while 31 readers keep calling a
provider is not a stop, and the only way to tell the difference is to count the
calls that happen after the token is set.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from typing import List, Optional

import httpx
import pytest
import uvicorn

from analyst_copilot.agent.cancellation import NEVER, CancelToken, Cancelled
from analyst_copilot.agent.corpus import DocumentCorpus
from analyst_copilot.agent.models import Stage, StageEvent
from analyst_copilot import usage
from analyst_copilot.agent.orchestrator import DeepSearchOrchestrator
from analyst_copilot.agent.runtime import AgentRuntime
from analyst_copilot.agent.tools import (
    REPORT_FINDING,
    CalculateTool,
    DocumentToolset,
    ReportFindingTool,
    ToolRegistry,
    document_tools,
)
from analyst_copilot.api.config import ApiSettings, get_api_settings
from analyst_copilot.api.dependencies import (
    current_user_id,
    get_analyst_agent,
    get_collection_indexer,
    get_conversation_service,
    get_filing_service,
    get_run_registry,
)
from analyst_copilot.api.main import create_app
from analyst_copilot.api.services.runs import RunRegistry
from analyst_copilot.llm.base import ChatClient, ChatTurn, ToolCall
from analyst_copilot.parsing.markdown_store import MarkdownPageStore
from analyst_copilot.parsing.models import FilingDocument, Page

API = "/api/v1"
DOC = "TESTCO_2022_10K"
FILING = "testco"
PAGES = 12


# --------------------------------------------------------------------------- #
# the token itself
# --------------------------------------------------------------------------- #
def test_a_token_raises_only_once_it_is_set():
    token = CancelToken()
    token.raise_if_cancelled()  # not cancelled: a no-op
    token.cancel()
    assert token.cancelled
    with pytest.raises(Cancelled):
        token.raise_if_cancelled()


def test_the_never_token_cannot_be_cancelled():
    """`POST /chat` and every script share one immutable token."""
    NEVER.cancel()
    assert NEVER.cancelled is False
    NEVER.raise_if_cancelled()


# --------------------------------------------------------------------------- #
# the fan-out
# --------------------------------------------------------------------------- #
@pytest.fixture
def corpus(tmp_path):
    """A document with one page per shard, so the fan-out is wide."""
    pages = [
        Page(doc_name=DOC, page_index=index, text=f"# Page {index}\n\nNothing here.")
        for index in range(PAGES)
    ]
    store = MarkdownPageStore(base_dir=tmp_path / "md")
    store.save(FilingDocument(doc_name=DOC, source_path="", pages=pages))
    return DocumentCorpus(store=store, doc_names=[DOC])


class CountingChat(ChatClient):
    """
    Answers every reader, and stops the run partway through.

    Counts calls rather than asserting on them directly: what a stop has to be
    worth is measured in provider calls that never happened.
    """

    def __init__(self, token: CancelToken, cancel_after: int = 3) -> None:
        self.token = token
        self.cancel_after = cancel_after
        self.calls = 0
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return "counting"

    @property
    def supports_tools(self) -> bool:
        return True

    def complete(self, messages, temperature=0.0, max_tokens=800):
        return ""

    def complete_with_tools(
        self, messages, tools, temperature=0.0, max_tokens=4096, tool_choice="auto"
    ) -> ChatTurn:
        with self._lock:
            self.calls += 1
            calls = self.calls
        # The analyst presses stop while this call is in flight.
        if calls == self.cancel_after:
            self.token.cancel()
        time.sleep(0.01)
        call = ToolCall(id=f"c{calls}", name=REPORT_FINDING, arguments='{"found": false}')
        return ChatTurn(
            content="",
            tool_calls=[call],
            finish_reason="tool_calls",
            message={
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                ],
            },
        )


def test_cancelling_stops_the_fan_out_before_the_queued_shards_run(corpus):
    """
    The cheap half of a stop.

    With 12 shards and 2 readers, ten shards are queued at any moment. None of
    them should call anything once the run has been stopped — the whole point of
    a cooperative token is that the cost of a stop is bounded by what is already
    in flight, not by what was left to do.
    """
    token = CancelToken()
    chat = CountingChat(token, cancel_after=3)
    orchestrator = DeepSearchOrchestrator(chat, pages_per_shard=1, max_concurrency=2)

    with pytest.raises(Cancelled):
        orchestrator.search("What is capex?", corpus, cancel=token)

    # Three calls before the stop, plus at most one already in flight beside it.
    assert chat.calls <= 4, f"{chat.calls} provider calls survived the stop"
    assert chat.calls < PAGES


def test_an_uncancelled_fan_out_still_reads_every_shard(corpus):
    """The checkpoints must not cost anything when nothing is stopping."""
    chat = CountingChat(CancelToken(), cancel_after=0)
    orchestrator = DeepSearchOrchestrator(chat, pages_per_shard=1, max_concurrency=4)

    result = orchestrator.search("What is capex?", corpus)

    assert chat.calls == PAGES
    assert result.shards_run == PAGES


def test_a_stopped_agent_run_raises_rather_than_reporting_nothing(corpus):
    """
    An empty `AgentRun` would be indistinguishable from an agent that looked and
    found nothing, and a fan-out would happily adjudicate over it.
    """
    token = CancelToken()
    token.cancel()
    toolset = DocumentToolset(corpus)
    registry = ToolRegistry(
        document_tools(toolset) + [CalculateTool(), ReportFindingTool()]
    )
    chat = CountingChat(token, cancel_after=0)

    with pytest.raises(Cancelled):
        AgentRuntime(chat).run(
            "sys", "user", registry, terminal_tools=(REPORT_FINDING,), cancel=token
        )
    assert chat.calls == 0, "a stopped run must not make the first call either"


# --------------------------------------------------------------------------- #
# the HTTP contract
# --------------------------------------------------------------------------- #
class BlockingAgent:
    """
    An agent that reports one milestone and then waits to be stopped.

    Stands in for the sixty-second deep path without spending sixty seconds: it
    is a run that will never finish on its own, which is exactly the state a
    stop button exists for.
    """

    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def answer(
        self,
        message,
        collection=None,
        doc_name=None,
        history=None,
        on_stage=None,
        scope_ready=None,
        on_trace=None,
        cancel: Optional[CancelToken] = None,
        meter=None,
    ):
        if on_stage is not None:
            on_stage(
                StageEvent(Stage.DEEP_SEARCH, "reading every page", done=12, total=31)
            )
        if meter is not None:
            # Tokens genuinely spent before the stop. A run that is stopped has
            # still been paid for, and the point of reporting it is that the
            # analyst can see what stopping saved.
            meter.record(
                usage.Usage(model="stub-model", input_tokens=14760, output_tokens=842),
                "deep_search",
                "Read 118 pages · 12 of 31 done",
            )
        self.started.set()
        # A deadline, so a test that fails to stop it fails loudly rather than
        # leaving a thread the interpreter cannot exit past.
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                (cancel or NEVER).raise_if_cancelled()
                time.sleep(0.01)
            raise AssertionError("the run was never stopped")
        finally:
            self.stopped.set()


class SpyConversations:
    """Records what would have been persisted."""

    def __init__(self) -> None:
        self.recorded: List[tuple] = []

    def get(self, user_id, conversation_id):
        return SimpleNamespace(messages=[])

    def record_exchange(self, *args):
        self.recorded.append(args)
        return ("um_1", "m_1")


class SpyRegistry(RunRegistry):
    """A registry that hands out tokens the test can also see."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens: List[CancelToken] = []

    def start(self, user_id: str):
        run_id, token = super().start(user_id)
        self.tokens.append(token)
        return run_id, token


class StubCollections:
    def ready_documents(self, collection):
        return [DOC]


def _token(authorization: str):
    """The demo bearer token `current_user_id` parses."""
    import base64

    return "demo." + base64.b64encode(authorization.encode()).decode() + ".0"


@pytest.fixture
def stopping(tmp_path, monkeypatch):
    """
    An app whose only question blocks until it is stopped, over a real socket.

    A real server rather than `TestClient`, and the reason is the feature: the
    test client reads an ASGI response to completion before handing it back, so
    there is no such thing as a stream in progress to stop, and no way to hang up
    on one halfway through. Both are the whole subject here.
    """
    settings = ApiSettings(cors_origins=[])
    monkeypatch.setattr(
        ApiSettings, "upload_dir", property(lambda self: tmp_path), raising=False
    )
    agent = BlockingAgent()
    registry = SpyRegistry()
    conversations = SpyConversations()

    app = create_app(settings)
    app.dependency_overrides[get_api_settings] = lambda: settings
    app.dependency_overrides[get_analyst_agent] = lambda: agent
    app.dependency_overrides[get_run_registry] = lambda: registry
    app.dependency_overrides[get_collection_indexer] = lambda: StubCollections()
    app.dependency_overrides[get_conversation_service] = lambda: conversations
    app.dependency_overrides[get_filing_service] = lambda: SimpleNamespace(
        is_indexed=lambda name: True
    )

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "the test server never came up"
    port = server.servers[0].sockets[0].getsockname()[1]

    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15) as client:
        yield SimpleNamespace(
            http=client,
            agent=agent,
            registry=registry,
            conversations=conversations,
            post=client.post,
        )

    server.should_exit = True
    thread.join(timeout=10)


def _sse(response):
    """Yield (event, data) pairs from a live stream as they arrive."""
    name, data = "", ""
    for line in response.iter_lines():
        line = line.rstrip("\r")
        if line.startswith("event:"):
            name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data = line[len("data:") :].strip()
        elif line == "" and name:
            yield name, (json.loads(data) if data else {})
            name, data = "", ""


def _ask(stopping, **kwargs):
    body = {"collection": FILING, "question": "What was capital expenditure?"}
    body.update(kwargs)
    return stopping.http.stream("POST", f"{API}/chat/stream", json=body)


def test_the_run_is_named_before_any_work_is_reported(stopping):
    """A run that cannot be named cannot be stopped."""
    with _ask(stopping) as response:
        events = _sse(response)
        name, payload = next(events)
        assert name == "run"
        assert payload["run_id"].startswith("run_")
        stopping.post(f"{API}/chat/runs/{payload['run_id']}/cancel")


def test_cancelling_ends_the_stream_with_cancelled_and_no_answer(stopping):
    with _ask(stopping) as response:
        events = _sse(response)
        _, run = next(events)
        assert stopping.agent.started.wait(2), "the run never started"

        accepted = stopping.post(f"{API}/chat/runs/{run['run_id']}/cancel")
        assert accepted.status_code == 202
        assert accepted.json()["status"] == "cancelling"

        seen = [(name, payload) for name, payload in events]

    names = [name for name, _ in seen]
    assert names[-1] == "cancelled", names
    assert "answer" not in names, "a stopped run must not also produce an answer"

    stopped = seen[-1][1]
    # Where it stopped, from the last milestone -- and nothing else. There is no
    # partial answer to report, because the answer is withheld until verified.
    assert stopped["stage"] == "deep_search"
    assert (stopped["done"], stopped["total"]) == (12, 31)
    assert stopped["elapsed_ms"] >= 0
    assert "answer" not in stopped


def test_a_stopped_run_still_reports_what_it_spent(stopping):
    """
    The one number a stop does carry, and the exception that proves the rule.

    A partial answer is withheld because it was never verified. Tokens are not
    an answer: they were genuinely spent whatever the run proved, and reporting
    them is the difference between an analyst who knows what stopping saved and
    one who is guessing.
    """
    with _ask(stopping) as response:
        events = _sse(response)
        _, run = next(events)
        assert stopping.agent.started.wait(2), "the run never started"
        stopping.post(f"{API}/chat/runs/{run['run_id']}/cancel")
        seen = [(name, payload) for name, payload in events]

    stopped = seen[-1][1]
    spend = stopped["usage"]
    assert spend["input_tokens"] == 14_760
    assert spend["output_tokens"] == 842
    assert spend["total_tokens"] == 15_602
    assert spend["calls"] == 1
    assert [entry["stage"] for entry in spend["stages"]] == ["deep_search"]
    assert spend["stages"][0]["label"] == "Read 118 pages · 12 of 31 done"
    # No rate is configured for the stub model, so there is no dollar figure --
    # and deliberately not a zero, which would read as "this was free".
    assert spend["priced"] is False
    assert spend["cost_usd"] is None


def test_the_work_itself_stops_not_just_the_reporting(stopping):
    """
    The bug this feature exists for: cancelling the asyncio task abandons the
    result while the pipeline thread keeps running. The token is what the worker
    threads actually check, so the thread has to come back.
    """
    with _ask(stopping) as response:
        events = _sse(response)
        _, run = next(events)
        assert stopping.agent.started.wait(2)
        stopping.post(f"{API}/chat/runs/{run['run_id']}/cancel")
        list(events)

    assert stopping.agent.stopped.wait(2), "the pipeline thread never unwound"


def test_a_cancelled_run_is_not_persisted(stopping):
    """Half a fan-out proves nothing, so it has no business in a thread."""
    with _ask(stopping, conversation_id="c_1") as response:
        events = _sse(response)
        _, run = next(events)
        assert stopping.agent.started.wait(2)
        stopping.post(f"{API}/chat/runs/{run['run_id']}/cancel")
        list(events)

    assert stopping.conversations.recorded == []


def test_dropping_the_connection_stops_the_work_too(stopping):
    """
    A closed tab is a stop.

    This is the bug the feature opens with: the stream's `finally` cancels the
    task that awaits the pipeline, and the pipeline is not in that task. Hanging
    up has to reach the worker thread, or a navigation leaves a fan-out reading a
    10-K for nobody.
    """
    with _ask(stopping) as response:
        events = _sse(response)
        next(events)
        assert stopping.agent.started.wait(2)
        # Leaving the block closes the response without reading it to the end,
        # which is what a navigation or an AbortController does.

    assert stopping.agent.stopped.wait(5), "the fan-out outlived its reader"
    assert all(token.cancelled for token in stopping.registry.tokens)


def test_another_users_run_cannot_be_cancelled(stopping):
    """A run id is a capability; another user's is indistinguishable from none."""
    with _ask(stopping) as response:
        events = _sse(response)
        _, run = next(events)
        assert stopping.agent.started.wait(2)

        refused = stopping.post(
            f"{API}/chat/runs/{run['run_id']}/cancel",
            headers={"Authorization": f"Bearer {_token('u_someone_else')}"},
        )
        assert refused.status_code == 404
        assert refused.json()["error"]["code"] == "run_not_found"

        stopping.post(f"{API}/chat/runs/{run['run_id']}/cancel")
        list(events)


def test_cancelling_a_finished_run_is_a_404_not_a_success(stopping):
    """A client should be able to tell "stopped it" from "it was already over"."""
    with _ask(stopping) as response:
        events = _sse(response)
        _, run = next(events)
        assert stopping.agent.started.wait(2)
        assert stopping.post(f"{API}/chat/runs/{run['run_id']}/cancel").status_code == 202
        list(events)

    again = stopping.post(f"{API}/chat/runs/{run['run_id']}/cancel")
    assert again.status_code == 404


def test_an_unknown_run_is_a_404(stopping):
    assert stopping.post(f"{API}/chat/runs/run_nope/cancel").status_code == 404


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
def test_a_registry_forgets_runs_that_outlive_their_ttl():
    registry = RunRegistry(ttl_seconds=0)
    run_id, _ = registry.start("u_demo")
    # The sweep runs on the write path, so a second run clears the first.
    registry.start("u_demo")
    assert registry.cancel("u_demo", run_id) is False


def test_finishing_a_run_makes_it_uncancellable():
    registry = RunRegistry()
    run_id, token = registry.start("u_demo")
    registry.finish(run_id)
    assert registry.cancel("u_demo", run_id) is False
    assert token.cancelled is False
