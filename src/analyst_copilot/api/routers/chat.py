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
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from analyst_copilot.agent import AnalystAgent, StageEvent
from analyst_copilot.api.dependencies import (
    current_user_id,
    get_analyst_agent,
    get_collection_indexer,
    get_conversation_service,
    get_filing_service,
)
from analyst_copilot.api.errors import (
    ApiError,
    DatabaseUnavailable,
    FilingNotIndexed,
    UpstreamUnavailable,
)
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.schemas import ChatRequest, ChatResponse
from analyst_copilot.api.services.conversations import ConversationService
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
                "Server-sent events. `stage` events report progress; a single "
                "`answer` event carries the finished ChatResponse; `error` "
                "carries a failure. The stream ends after `answer` or `error`."
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
    user_id: str = Depends(current_user_id),
) -> StreamingResponse:
    """
    The same answer as `POST /chat`, with the progress that produced it.

    This is a POST, so it is read with `fetch` and a stream reader rather than
    with `EventSource` — the request carries a body, and EventSource cannot
    send one.
    """
    queue: "asyncio.Queue[Optional[Tuple[str, Dict[str, Any]]]]" = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_stage(event: StageEvent) -> None:
        # Called from the pipeline's worker threads, so the hop back onto the
        # event loop has to be explicit.
        loop.call_soon_threadsafe(queue.put_nowait, ("stage", event.to_dict()))

    async def produce() -> None:
        try:
            response = await _answer(
                request, filings, collections, agent, conversations, user_id, on_stage
            )
            await queue.put(("answer", response.model_dump(mode="json")))
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
            # The reader went away — a closed tab, a navigation. Stop the work
            # rather than leaving a fan-out of readers running for nobody.
            if not task.done():
                task.cancel()

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


# --------------------------------------------------------------------------- #
# shared path
# --------------------------------------------------------------------------- #
async def _answer(
    request: ChatRequest,
    filings: FilingService,
    collections: CollectionIndexer,
    agent: AnalystAgent,
    conversations: ConversationService,
    user_id: str,
    on_stage,
) -> ChatResponse:
    """Answer, then record the exchange. Used by both endpoints."""
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
