"""SQLAlchemy 2.0 models for product state.

Mirrors the schema in ui/PLAN.md §8 with one deliberate change: a conversation
is pinned to a *collection* (the product's word for a filing) rather than a
`doc_name`, because the UI threads are collection-scoped and a question asked
of a folder answers from whichever member carries the evidence.

A message stores the full `result` JSON so the UI can re-render the evidence
panel and retrieval trace exactly as it was served, plus the queryable
columns (found, page, latency) the product will want later.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from analyst_copilot.api.db.database import database_url

JsonType = JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


NOW = func.now()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="analyst")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The filing this thread is pinned to. Nullable for future doc-scoped
    # threads; the UI always sets it.
    collection: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW
    )

    # Answer outcome, queryable without unwrapping `result`.
    found: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    abstention_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retrieval: Mapped[list | None] = mapped_column(JsonType, nullable=True)

    # What the answer cost, queryable without unwrapping `result`.
    #
    # Money is stored in integer micro-dollars rather than a float: a thread's
    # cost is a sum over dozens of rows whose interesting digits sit at the
    # fifth decimal place, and that is precisely where a float drifts. Null
    # means no rate was configured for the model, which is not the same fact as
    # zero -- a locally hosted model genuinely costs nothing.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micro_usd: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The full ChatResponse as served, so the UI re-renders history verbatim.
    result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


__all__ = ["Base", "User", "Conversation", "Message", "database_url", "JsonType"]
