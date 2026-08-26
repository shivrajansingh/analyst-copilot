"""The chat box: one analyst question, answered from one folder or one document."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from analyst_copilot.api.dependencies import (
    current_user_id,
    get_collection_indexer,
    get_conversation_service,
    get_filing_service,
    get_qa_service,
)
from analyst_copilot.api.errors import (
    DatabaseUnavailable,
    FilingNotIndexed,
    UpstreamUnavailable,
)
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.schemas import ChatRequest, ChatResponse
from analyst_copilot.api.services.conversations import ConversationService
from analyst_copilot.collections.indexer import CollectionIndexer
from analyst_copilot.config.settings import get_settings
from analyst_copilot.services.qa import QuestionAnsweringService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="Ask a question")
async def chat(
    request: ChatRequest,
    filings: FilingService = Depends(get_filing_service),
    collections: CollectionIndexer = Depends(get_collection_indexer),
    qa: QuestionAnsweringService = Depends(get_qa_service),
    conversations: ConversationService = Depends(get_conversation_service),
    user_id: str = Depends(current_user_id),
) -> ChatResponse:
    """
    Answer a question from one folder or one document, with the place it came from.

    Declining is a normal 200 response, not an error: `found` is false, `answer`
    is "not found in this filing" and `evidence` is null. A caller should never
    have to distinguish "no evidence" from "the service broke".

    Scoping a question to a folder widens **where the system may look**, not
    what it may claim. Retrieval ranks pages from every indexed document in the
    folder against each other, and the answer still cites exactly one document
    and one page — a citation is only checkable against the document it names.
    """
    if request.collection:
        ready = await run_in_threadpool(collections.ready_documents, request.collection)
        if not ready:
            raise FilingNotIndexed(
                f"Folder {request.collection!r} has no indexed documents yet. "
                "Add documents to it, then poll their jobs until they are ready."
            )
        answer_call = (
            qa.answer_collection,
            {"question": request.question, "collection": request.collection},
        )
    else:
        if not filings.is_indexed(request.doc_name):
            raise FilingNotIndexed(
                f"Filing {request.doc_name!r} is not indexed yet. "
                "Add it first, then poll its status until it is ready."
            )
        answer_call = (
            qa.answer,
            {"question": request.question, "doc_name": request.doc_name},
        )

    started = time.perf_counter()
    try:
        # The pipeline is synchronous and spends its time on network calls, so
        # it runs off the event loop to keep the service responsive.
        function, kwargs = answer_call
        answer = await run_in_threadpool(function, **kwargs)
    except ValueError as exc:
        raise UpstreamUnavailable(f"The language model could not be reached: {exc}") from exc

    latency_ms = round((time.perf_counter() - started) * 1000)
    response = ChatResponse.from_answer(answer)

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
