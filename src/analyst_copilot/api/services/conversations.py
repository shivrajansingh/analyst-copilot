"""Chat history: conversations and messages, persisted in Postgres.

Every method is scoped by `user_id`, and an id that exists but belongs to
another user is indistinguishable from one that does not exist — the two errors
must not leak who owns what.

The service is deliberately thin: sessions come from the factory handed to it
in `dependencies.py`, and each call opens its own session, so nothing is shared
across requests and a failed write cannot poison a later one.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from analyst_copilot.api.db.models import Conversation, Message, User, utcnow
from analyst_copilot.api.errors import ConversationNotFound, DatabaseUnavailable

DEFAULT_TITLE = "New conversation"


def _new_id() -> str:
    return uuid.uuid4().hex


def _with_messages(conversation: Conversation) -> Conversation:
    """Eager-load `messages` while the session is still alive, so the caller
    (outside the session) can render the thread without a lazy load."""
    _ = list(conversation.messages)
    return conversation


class ConversationService:
    """Chat history CRUD. Every method answers 503 when no database is configured."""

    def __init__(self, factory: Optional[sessionmaker[Session]] = None) -> None:
        self._factory = factory

    # --- conversations ------------------------------------------------------- #
    def list_for(self, user_id: str) -> list[Conversation]:
        with self._session() as session:
            return list(
                session.scalars(
                    select(Conversation)
                    .where(Conversation.user_id == user_id)
                    .order_by(Conversation.updated_at.desc())
                ).all()
            )

    def create(
        self,
        user_id: str,
        collection: Optional[str],
        title: Optional[str],
    ) -> Conversation:
        with self._session() as session:
            self._ensure_user(session, user_id)
            conversation = Conversation(
                id=_new_id(),
                user_id=user_id,
                collection=collection,
                title=(title or DEFAULT_TITLE)[:200],
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return _with_messages(conversation)

    def get(self, user_id: str, conversation_id: str) -> Conversation:
        with self._session() as session:
            conversation = self._owned(session, user_id, conversation_id)
            # Eager-load messages so the caller can render the thread in one go.
            return _with_messages(conversation)

    def rename(self, user_id: str, conversation_id: str, title: str) -> Conversation:
        with self._session() as session:
            conversation = self._owned(session, user_id, conversation_id)
            conversation.title = title[:200]
            session.commit()
            session.refresh(conversation)
            return _with_messages(conversation)

    def remove(self, user_id: str, conversation_id: str) -> None:
        with self._session() as session:
            conversation = self._owned(session, user_id, conversation_id)
            session.delete(conversation)
            session.commit()

    # --- messages ------------------------------------------------------------ #
    def record_exchange(
        self,
        user_id: str,
        conversation_id: str,
        question: str,
        response: dict,
        latency_ms: int,
        model: Optional[str],
    ) -> tuple[str, str]:
        """
        Persist one question/answer round trip.

        The user message is written before the answer so a crash mid-answer
        never loses the question. Raises `ConversationNotFound` when the
        conversation is not the caller's.
        """
        with self._session() as session:
            conversation = self._owned(session, user_id, conversation_id)
            user_message_id = _new_id()
            session.add(
                Message(
                    id=user_message_id,
                    conversation_id=conversation.id,
                    role="user",
                    content=question,
                )
            )
            message = Message(
                id=_new_id(),
                conversation_id=conversation.id,
                role="assistant",
                content=response["answer"],
                found=response["found"],
                page=response["evidence"]["page"] if response["evidence"] else None,
                abstention_reason=response.get("abstention_reason"),
                latency_ms=latency_ms,
                model=model,
                retrieval=response["retrieval"] if response["retrieval"] else None,
                result=response,
                **_usage_columns(response.get("usage")),
            )
            session.add(message)
            # A thread created without a title takes it from the first question.
            if conversation.title == DEFAULT_TITLE:
                conversation.title = question[:200]
            conversation.updated_at = utcnow()
            session.commit()
            return user_message_id, message.id

    # --- internals ----------------------------------------------------------- #
    def _session(self) -> Session:
        if self._factory is None:
            raise DatabaseUnavailable(
                "No database is configured (set DATABASE_URL), so chat history "
                "cannot be stored."
            )
        return self._factory()

    def _owned(self, session: Session, user_id: str, conversation_id: str) -> Conversation:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ConversationNotFound(
                f"No conversation '{conversation_id}' for this user."
            )
        return conversation

    @staticmethod
    def _ensure_user(session: Session, user_id: str) -> None:
        if session.get(User, user_id) is None:
            session.add(
                User(id=user_id, username=user_id, display_name=user_id)
            )
            session.flush()


def _usage_columns(usage: Optional[dict]) -> dict:
    """
    The queryable slice of a usage report, for the message row.

    `result` already holds the whole thing, so this is not the record -- it is
    the part worth aggregating over ("what has this thread cost?") without
    unwrapping JSON in SQL. An unpriced answer stores a null cost rather than a
    zero, because "nobody configured a rate" and "it was free" are different
    facts and only one of them should sum.
    """
    if not usage:
        return {}
    cost = usage.get("cost_usd")
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cost_micro_usd": round(cost * 1_000_000) if cost is not None else None,
    }
