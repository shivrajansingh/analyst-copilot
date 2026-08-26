"""
Chat history endpoints.

A conversation is a thread pinned to one filing; its messages are stored in
Postgres. Every endpoint is scoped to the caller's user id (see
`current_user_id` in dependencies.py). The endpoints are plain `def`, so
FastAPI runs the synchronous DB work in its threadpool rather than blocking
the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from analyst_copilot.api.db.models import Conversation, Message
from analyst_copilot.api.dependencies import current_user_id, get_conversation_service
from analyst_copilot.api.schemas import (
    ConversationCreateRequest,
    ConversationDetail,
    ConversationListResponse,
    ConversationRenameRequest,
    ConversationSummary,
    MessageResponse,
)
from analyst_copilot.api.services.conversations import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListResponse, summary="List conversations")
def list_conversations(
    user_id: str = Depends(current_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationListResponse:
    """The caller's threads, newest first."""
    conversations = service.list_for(user_id)
    return ConversationListResponse(
        conversations=[_summary(c) for c in conversations]
    )


@router.post("", response_model=ConversationDetail, status_code=201, summary="Start a conversation")
def create_conversation(
    request: ConversationCreateRequest,
    user_id: str = Depends(current_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetail:
    """Create a thread, pinned to one filing."""
    conversation = service.create(user_id, request.collection, request.title)
    return _detail(conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail, summary="Get a conversation")
def get_conversation(
    conversation_id: str,
    user_id: str = Depends(current_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetail:
    """A thread with all its messages, for re-rendering history."""
    conversation = service.get(user_id, conversation_id)
    return _detail(conversation)


@router.patch("/{conversation_id}", response_model=ConversationSummary, summary="Rename a conversation")
def rename_conversation(
    conversation_id: str,
    request: ConversationRenameRequest,
    user_id: str = Depends(current_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationSummary:
    conversation = service.rename(user_id, conversation_id, request.title)
    return _summary(conversation)


@router.delete("/{conversation_id}", status_code=204, summary="Delete a conversation")
def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(current_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> None:
    """Delete a thread and its messages."""
    service.remove(user_id, conversation_id)


def _summary(conversation: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        collection=conversation.collection,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
    )


def _message(row: Message) -> MessageResponse:
    return MessageResponse(
        id=row.id,
        role=row.role,
        content=row.content,
        created_at=row.created_at.isoformat(),
        found=row.found,
        page=row.page,
        abstention_reason=row.abstention_reason,
        latency_ms=row.latency_ms,
        retrieval=row.retrieval,
        result=row.result,
    )


def _detail(conversation: Conversation) -> ConversationDetail:
    return ConversationDetail(
        **_summary(conversation).model_dump(),
        messages=[_message(m) for m in conversation.messages],
    )
