"""
Wiring.

Every collaborator is built exactly once per process and handed to routers via
`Depends`, which keeps the routers free of construction logic and lets tests
swap any of them through `app.dependency_overrides` without touching the network.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Optional

from fastapi import Depends, Header
from sqlalchemy.orm import Session, sessionmaker

from analyst_copilot.api.config import ApiSettings, get_api_settings
from analyst_copilot.api.db.database import make_session_factory
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.jobs import IndexingJobManager
from analyst_copilot.api.services.collections import CollectionApiService
from analyst_copilot.api.services.conversations import ConversationService
from analyst_copilot.collections.indexer import CollectionIndexer
from analyst_copilot.collections.searcher import CollectionSearcher
from analyst_copilot.services.indexing import HybridFilingIndexer
from analyst_copilot.services.qa import QuestionAnsweringService


@lru_cache
def get_indexer() -> HybridFilingIndexer:
    return HybridFilingIndexer()


@lru_cache
def get_collection_indexer() -> CollectionIndexer:
    """
    One collection indexer per process, so its index cache is shared.

    Answering a folder question loads every member's indices; a per-request
    indexer would decompress the same vectors on every question.
    """
    return CollectionIndexer()


@lru_cache
def get_collection_searcher() -> CollectionSearcher:
    return CollectionSearcher()


@lru_cache
def get_job_manager() -> IndexingJobManager:
    settings = get_api_settings()
    return IndexingJobManager(
        indexer=get_indexer(),
        max_workers=settings.max_concurrent_index_jobs,
        budget_seconds=settings.index_budget_seconds,
        collection_indexer=get_collection_indexer(),
    )


@lru_cache
def get_qa_service() -> QuestionAnsweringService:
    """
    The QA pipeline, unchanged.

    Its chat client is created on first use, so building this at startup costs
    nothing and never fails because a provider is briefly unreachable.
    """
    return QuestionAnsweringService(
        indexer=get_indexer(),
        collection_indexer=get_collection_indexer(),
        collection_searcher=get_collection_searcher(),
    )


def get_filing_service(
    settings: ApiSettings = Depends(get_api_settings),
    indexer: HybridFilingIndexer = Depends(get_indexer),
    jobs: IndexingJobManager = Depends(get_job_manager),
) -> FilingService:
    return FilingService(settings=settings, indexer=indexer, jobs=jobs)


def get_collection_service(
    settings: ApiSettings = Depends(get_api_settings),
    indexer: CollectionIndexer = Depends(get_collection_indexer),
    jobs: IndexingJobManager = Depends(get_job_manager),
) -> CollectionApiService:
    return CollectionApiService(settings=settings, indexer=indexer, jobs=jobs)


@lru_cache
def get_session_factory() -> Optional[sessionmaker[Session]]:
    """
    One session factory per configured database URL.

    Returns None when no DATABASE_URL is set: the API then answers questions
    normally but records nothing, and the conversations endpoints answer 503.
    """
    url = get_api_settings().database_url
    if not url:
        return None
    return make_session_factory(url)


@lru_cache
def get_conversation_service(
    factory: Optional[sessionmaker[Session]] = Depends(get_session_factory),
) -> ConversationService:
    """
    Chat history, or a service whose every method answers 503.

    Never raises at construction: chat must keep answering questions even when
    no database is configured, so callers that treat persistence as best-effort
    (the chat endpoint) can construct this freely and catch DatabaseUnavailable.
    """
    return ConversationService(factory)


def current_user_id(authorization: str | None = Header(default=None)) -> str:
    """
    The caller's user id, from the demo bearer token.

    Format: `demo.<base64(user_id)>.<timestamp>`, issued by the frontend's
    auth.store.ts. A missing or malformed header resolves to the demo user
    rather than failing, so a bare curl works. This is a demo auth boundary
    (labelled as such in the UI) until real auth lands; nothing else changes.
    """
    if not authorization:
        return "u_demo"
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.startswith("demo."):
        return "u_demo"
    try:
        _, payload, _ = token.split(".", 2)
        user_id = base64.b64decode(payload).decode()
    except Exception:
        return "u_demo"
    return user_id if user_id else "u_demo"


def reset_dependencies() -> None:
    """Drop cached singletons. Used by tests and by `create_app` in reload mode."""
    get_indexer.cache_clear()
    get_collection_indexer.cache_clear()
    get_collection_searcher.cache_clear()
    get_job_manager.cache_clear()
    get_qa_service.cache_clear()
    get_session_factory.cache_clear()
    get_conversation_service.cache_clear()
