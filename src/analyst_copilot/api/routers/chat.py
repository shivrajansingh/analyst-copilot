"""The chat box: one message, answered at the cheapest tier that can prove itself.

Two endpoints over the same brain. `POST /chat` blocks and returns the finished
answer; `POST /chat/stream` returns the same answer, preceded by the progress
milestones that produced it.

The streaming endpoint exists because of what the deep path costs in wall-clock
time. Reading every page of a 10-K takes a minute, and a minute of silence reads
as a hang. What is streamed is deliberately *progress and not tokens*: the
answer still arrives in one piece, already verified, because a figure that
renders before the verifier has finished with it is an unproven figure on
screen — which is the one thing this product exists to prevent.

A streaming answer can also be stopped, and stopping it stops the *work* rather
than just the reporting of it. The pipeline runs in a worker thread that spawns
a pool of its own, and no amount of `asyncio` cancellation reaches either — so
every run carries a `CancelToken`, announced to the client as a `run` event
before anything starts. Two things set it: the client dropping the connection,
and `POST /chat/runs/{run_id}/cancel`. A stopped run ends with a `cancelled`
event and is not persisted: half a fan-out proves nothing, and a turn nobody
finished has no business in a thread's history.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from analyst_copilot.agent import AnalystAgent, StageEvent
from analyst_copilot.agent.cancellation import CancelToken, Cancelled
from analyst_copilot.agent.trace import TraceEvent
from analyst_copilot.api.dependencies import (
    current_user_id,
    get_analyst_agent,
    get_collection_indexer,
    get_conversation_service,
    get_filing_service,
    get_run_registry,
)
from analyst_copilot.api.errors import (
    ApiError,
    DatabaseUnavailable,
    FilingNotIndexed,
    RunNotFound,
    UpstreamUnavailable,
)
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.schemas import ChatRequest, ChatResponse
from analyst_copilot.api.services.conversations import ConversationService
from analyst_copilot.api.services.runs import RunRegistry
from analyst_copilot.collections.indexer import CollectionIndexer
from analyst_copilot.config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Emitted every 15 seconds while the deep path is reading, so a proxy that
# closes idle connections does not kill a legitimate long answer.
_KEEPALIVE_SECONDS = 15.0


@router.post("/chat", response_model=ChatResponse, summary="Ask a question")
async def chat(
    request: ChatRequest,
    filings: FilingService = Depends(get_filing_service),
    collections: CollectionIndexer = Depends(get_collection_indexer),
    agent: AnalystAgent = Depends(get_analyst_agent),
    conversations: ConversationService = Depends(get_conversation_service),
    user_id: str = Depends(current_user_id),
) -> ChatResponse:
    """
    Answer a message from one folder or one document, with the place it came from.

    Declining is a normal 200 response, not an error: `found` is false, `answer`
    is "not found in this filing" and `evidence` is null. A caller should never
    have to distinguish "no evidence" from "the service broke".

    Not every message is a question about a document. A greeting is answered as
    a greeting, with `mode` set to `conversational` and nothing cited — branch on
    `mode` before `found`, because a conversational reply is neither an
    evidenced answer nor a decline.

    Scoping a question to a folder widens **where the system may look**, not
    what it may claim. The answer still cites exactly one document and one page
    per question asked — a citation is only checkable against the document it
    names.

    This endpoint cannot be stopped: there is no channel to carry a stop and no
    run id to name one by. A caller that needs to stop uses `/chat/stream`.
    """
    return await _answer(
        request, filings, collections, agent, conversations, user_id, on_stage=None
    )


@router.post(
    "/chat/stream",
    summary="Ask a question, streaming progress",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": (
                "Server-sent events. A single `run` event comes first and names "
                "the run, so it can be stopped. `stage` events report milestones "
                "and `trace` events the activity underneath them — which agent is "
                "running, what it said it was about to look for, which tool it "
                "called. A single `answer` event carries the finished "
                "ChatResponse; `error` carries a failure; `cancelled` says the "
                "run was stopped and reports how far it had got. The stream ends "
                "after `answer`, `error` or `cancelled`."
            ),
        }
    },
)
async def chat_stream(
    request: ChatRequest,
    filings: FilingService = Depends(get_filing_service),
    collections: CollectionIndexer = Depends(get_collection_indexer),
    agent: AnalystAgent = Depends(get_analyst_agent),
    conversations: ConversationService = Depends(get_conversation_service),
    runs: RunRegistry = Depends(get_run_registry),
    user_id: str = Depends(current_user_id),
) -> StreamingResponse:
    """
    The same answer as `POST /chat`, with the progress that produced it.

    This is a POST, so it is read with `fetch` and a stream reader rather than
    with `EventSource` — the request carries a body, and EventSource cannot
    send one.

    Stopping it: drop the connection, or call `/chat/runs/{run_id}/cancel` with
    the id from the `run` event. Both set the same token, and the token is what
    the reader threads actually check — cancelling the task that awaits them
    would abandon the answer while the fan-out kept running.
    """
    queue: "asyncio.Queue[Optional[Tuple[str, Dict[str, Any]]]]" = asyncio.Queue()
    loop = asyncio.get_running_loop()
    run_id, cancel = runs.start(user_id)
    started = time.perf_counter()
    #: The last milestone reported, so a stop can say where it stopped.
    reached: Dict[str, Any] = {}

    def on_stage(event: StageEvent) -> None:
        # Called from the pipeline's worker threads, so the hop back onto the
        # event loop has to be explicit.
        payload = event.to_dict()
        reached.clear()
        reached.update(payload)
        loop.call_soon_threadsafe(queue.put_nowait, ("stage", payload))

    def on_trace(event: TraceEvent) -> None:
        # Same hop, and the same reason. Traces arrive from every reader thread
        # at once, which is exactly why they are a separate event type: a client
        # can render the milestones and ignore the firehose.
        loop.call_soon_threadsafe(queue.put_nowait, ("trace", event.to_dict()))

    async def produce() -> None:
        try:
            response = await _answer(
                request, filings, collections, agent, conversations, user_id,
                on_stage, on_trace, cancel,
            )
            await queue.put(("answer", response.model_dump(mode="json")))
        except Cancelled:
            # Not an error, and deliberately not an `error` event: a client that
            # renders failures in red would show the analyst their own decision
            # as a bug. Nothing was persisted -- `_answer` raises out before it
            # records anything -- so the thread has no half-finished turn in it.
            await queue.put(("cancelled", _stopped_at(reached, started)))
        except ApiError as exc:
            # Any handled failure -- not indexed, provider down, someone else's
            # conversation -- reaches the reader as an `error` event. The HTTP
            # status is already 200: the stream had begun before this was known.
            await queue.put(("error", {"code": exc.code, "message": exc.message}))
        except Exception as exc:  # noqa: BLE001 - the stream must report, not hang
            logger.exception("streaming chat failed")
            await queue.put(
                ("error", {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"})
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(produce())

    async def events():
        try:
            # First, before any work is reported: a run that cannot be named
            # cannot be stopped, and the id is known before anything has begun.
            yield f"event: run\ndata: {json.dumps({'run_id': run_id})}\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    return
                name, payload = item
                yield f"event: {name}\ndata: {json.dumps(payload)}\n\n"
        finally:
            # The reader went away — a closed tab, a navigation, an abort. Stop
            # the work rather than leaving a fan-out of readers running for
            # nobody. The token is the half that matters: cancelling the task
            # only abandons the result, because the pipeline is in a worker
            # thread and its readers are in a pool of their own.
            cancel.cancel()
            if not task.done():
                task.cancel()
            runs.finish(run_id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # nginx buffers proxied responses by default, which would hold every
            # progress event until the answer arrived and defeat the endpoint.
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/chat/runs/{run_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Stop an answer that is still running",
)
async def cancel_run(
    run_id: str,
    runs: RunRegistry = Depends(get_run_registry),
    user_id: str = Depends(current_user_id),
) -> Dict[str, str]:
    """
    Stop the run named by the `run` event of `/chat/stream`.

    Accepted, not completed: this sets a flag that the reader threads check at
    their next checkpoint, so the last model call already in flight still
    finishes. The stream itself reports the actual stop, as a `cancelled` event.

    A run that has already ended is a 404 rather than a success, so a client can
    tell "stopped it" from "it was over before you asked". A run belonging to
    another user is the same 404: a run id is a capability, and confirming that
    one exists would leak that somebody is asking a question.
    """
    if not runs.cancel(user_id, run_id):
        raise RunNotFound(f"No answer with id {run_id!r} is running.")
    return {"run_id": run_id, "status": "cancelling"}


# --------------------------------------------------------------------------- #
# shared path
# --------------------------------------------------------------------------- #
def _stopped_at(reached: Dict[str, Any], started: float) -> Dict[str, Any]:
    """
    Where a stopped run had got to, for the `cancelled` event.

    Only what the last milestone already carried: the stage, and the reader
    counts when the deep path was running. There is no partial answer to report
    and there never will be — the answer is withheld until it is verified, which
    is the same rule that keeps tokens from streaming.
    """
    payload: Dict[str, Any] = {
        "stage": reached.get("stage"),
        "detail": reached.get("detail"),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }
    for field in ("done", "total"):
        if reached.get(field) is not None:
            payload[field] = reached[field]
    return payload


async def _answer(
    request: ChatRequest,
    filings: FilingService,
    collections: CollectionIndexer,
    agent: AnalystAgent,
    conversations: ConversationService,
    user_id: str,
    on_stage,
    on_trace=None,
    cancel: Optional[CancelToken] = None,
) -> ChatResponse:
    """
    Answer, then record the exchange. Used by both endpoints.

    A `Cancelled` from the pipeline propagates: it must reach the caller before
    the recording below, because a stopped turn is not a turn — persisting one
    would put a question with no answer into a thread's history.
    """
    ready = await run_in_threadpool(_scope_is_ready, request, filings, collections)
    history = await _history(conversations, user_id, request.conversation_id)

    started = time.perf_counter()
    try:
        # The pipeline is synchronous and spends its time on network calls, so
        # it runs off the event loop to keep the service responsive.
        answer = await run_in_threadpool(
            agent.answer,
            message=request.question,
            collection=request.collection,
            doc_name=request.doc_name,
            history=history,
            on_stage=on_stage,
            scope_ready=ready,
            on_trace=on_trace,
            cancel=cancel,
        )
    except ValueError as exc:
        raise UpstreamUnavailable(f"The language model could not be reached: {exc}") from exc

    if answer.abstention_reason == "no_indexed_documents":
        # A real question about a filing that has nothing to search is a state
        # the caller can fix, so it stays a 409 rather than a bare decline. A
        # greeting never reaches here: it was answered before this was checked.
        target = request.collection or request.doc_name
        raise FilingNotIndexed(
            f"{target!r} has no indexed documents yet. Add documents to it, then "
            "poll their jobs until they are ready."
        )

    latency_ms = round((time.perf_counter() - started) * 1000)
    response = ChatResponse.from_agent(answer)

    if request.conversation_id:
        try:
            # Persistence is best-effort from the caller's point of view: the
            # answer is complete without it. A conversation that is not the
            # caller's is a real error and propagates as a 404.
            response.conversation_id = request.conversation_id
            response.latency_ms = latency_ms
            user_message_id, message_id = await run_in_threadpool(
                conversations.record_exchange,
                user_id,
                request.conversation_id,
                request.question,
                response.model_dump(mode="json"),
                latency_ms,
                get_settings().openai_model,
            )
            response.user_message_id = user_message_id
            response.message_id = message_id
        except DatabaseUnavailable:
            logger.warning(
                "chat exchange not persisted for conversation %s: no database configured",
                request.conversation_id,
            )

    return response


def _scope_is_ready(
    request: ChatRequest,
    filings: FilingService,
    collections: CollectionIndexer,
) -> bool:
    """Whether there is anything indexed for this question to search."""
    if request.collection:
        return bool(collections.ready_documents(request.collection))
    return filings.is_indexed(request.doc_name or "")


async def _history(
    conversations: ConversationService,
    user_id: str,
    conversation_id: Optional[str],
) -> List[dict]:
    """
    Earlier turns of this thread, so a follow-up resolves against them.

    Absent history is not an error: a thread with no database behind it still
    answers questions, it just cannot resolve "and the year before?".
    """
    if not conversation_id:
        return []
    try:
        conversation = await run_in_threadpool(conversations.get, user_id, conversation_id)
    except DatabaseUnavailable:
        return []
    return [
        {"role": message.role, "content": message.content}
        for message in conversation.messages
    ]
