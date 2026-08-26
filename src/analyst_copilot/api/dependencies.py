"""
Wiring.

Every collaborator is built exactly once per process and handed to routers via
`Depends`, which keeps the routers free of construction logic and lets tests
swap any of them through `app.dependency_overrides` without touching the network.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from analyst_copilot.api.config import ApiSettings, get_api_settings
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.jobs import IndexingJobManager
from analyst_copilot.api.services.collections import CollectionApiService
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


def reset_dependencies() -> None:
    """Drop cached singletons. Used by tests and by `create_app` in reload mode."""
    get_indexer.cache_clear()
    get_collection_indexer.cache_clear()
    get_collection_searcher.cache_clear()
    get_job_manager.cache_clear()
    get_qa_service.cache_clear()
