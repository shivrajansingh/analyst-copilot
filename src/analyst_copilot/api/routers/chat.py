"""The chat box: one analyst question, answered from one filing."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from analyst_copilot.api.dependencies import get_filing_service, get_qa_service
from analyst_copilot.api.errors import FilingNotIndexed, UpstreamUnavailable
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.schemas import ChatRequest, ChatResponse
from analyst_copilot.services.qa import QuestionAnsweringService

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="Ask a question")
async def chat(
    request: ChatRequest,
    filings: FilingService = Depends(get_filing_service),
    qa: QuestionAnsweringService = Depends(get_qa_service),
) -> ChatResponse:
    """
    Answer a question from a single filing, with the page it came from.

    Declining is a normal 200 response, not an error: `found` is false, `answer`
    is "not found in this filing" and `evidence` is null. A caller should never
    have to distinguish "no evidence" from "the service broke".

    Questions are scoped to one filing on purpose — a citation is only checkable
    against the document it names.
    """
    if not filings.is_indexed(request.doc_name):
        raise FilingNotIndexed(
            f"Filing {request.doc_name!r} is not indexed yet. "
            "Add it first, then poll its status until it is ready."
        )

    try:
        # The pipeline is synchronous and spends its time on network calls, so
        # it runs off the event loop to keep the service responsive.
        answer = await run_in_threadpool(
            qa.answer,
            question=request.question,
            doc_name=request.doc_name,
        )
    except ValueError as exc:
        raise UpstreamUnavailable(f"The language model could not be reached: {exc}") from exc

    return ChatResponse.from_answer(answer)
