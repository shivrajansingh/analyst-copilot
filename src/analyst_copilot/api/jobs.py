"""
Background indexing jobs.

"Add filing" has to return immediately and then report progress, because
embedding a 200-page 10-K takes minutes. Indexing is synchronous, network-bound
work, so it runs on a small thread pool and the caller polls a job record.

The registry is in-process: a job's history does not survive a restart, which is
the right trade for a single-node service whose real state — the index itself —
is already durable on disk. `FilingService` reads that on-disk state, so a
restart loses the progress log, never a finished index.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

from analyst_copilot.services.indexing import HybridFilingIndexer

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    PARSING = "parsing"
    EMBEDDING = "embedding"
    SAVING = "saving"
    READY = "ready"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.READY, JobStatus.FAILED)


@dataclass(frozen=True)
class IndexingJob:
    """An immutable snapshot of one filing's indexing progress."""

    job_id: str
    doc_name: str
    source_path: str
    status: JobStatus
    created_at: float
    budget_seconds: int
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    page_count: Optional[int] = None
    error: Optional[str] = None

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.time()
        return round(end - self.created_at, 2)

    @property
    def over_budget(self) -> bool:
        """Whether this job has breached the spec's per-filing time budget."""
        return self.elapsed_seconds > self.budget_seconds


@dataclass
class _Registry:
    """Jobs by id, plus the active job per document, behind one lock."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    by_id: Dict[str, IndexingJob] = field(default_factory=dict)
    active_by_doc: Dict[str, str] = field(default_factory=dict)


class IndexingJobManager:
    """Submit filings for indexing and report their progress."""

    def __init__(
        self,
        indexer: Optional[HybridFilingIndexer] = None,
        max_workers: int = 2,
        budget_seconds: int = 600,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._indexer = indexer or HybridFilingIndexer()
        self._budget_seconds = budget_seconds
        self._clock = clock
        self._registry = _Registry()
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="indexing",
        )

    # -- queries ---------------------------------------------------------- #
    def get(self, job_id: str) -> Optional[IndexingJob]:
        with self._registry.lock:
            return self._registry.by_id.get(job_id)

    def active_job_for(self, doc_name: str) -> Optional[IndexingJob]:
        with self._registry.lock:
            job_id = self._registry.active_by_doc.get(doc_name)
            return self._registry.by_id.get(job_id) if job_id else None

    def list_jobs(self) -> List[IndexingJob]:
        with self._registry.lock:
            jobs = list(self._registry.by_id.values())
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    # -- submission ------------------------------------------------------- #
    def submit(self, doc_name: str, source_path: Path) -> IndexingJob:
        """
        Queue a filing for indexing.

        Re-submitting a document that is already being indexed returns the job
        in flight rather than embedding the same filing twice.
        """
        with self._registry.lock:
            existing_id = self._registry.active_by_doc.get(doc_name)
            if existing_id:
                return self._registry.by_id[existing_id]

            job = IndexingJob(
                job_id=uuid.uuid4().hex,
                doc_name=doc_name,
                source_path=str(source_path),
                status=JobStatus.QUEUED,
                created_at=self._clock(),
                budget_seconds=self._budget_seconds,
            )
            self._registry.by_id[job.job_id] = job
            self._registry.active_by_doc[doc_name] = job.job_id

        self._pool.submit(self._run, job.job_id)
        return job

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait)

    # -- worker ----------------------------------------------------------- #
    def _update(self, job_id: str, **changes: object) -> None:
        with self._registry.lock:
            job = self._registry.by_id.get(job_id)
            if job is None:
                return
            updated = replace(job, **changes)
            self._registry.by_id[job_id] = updated
            if updated.status.is_terminal:
                self._registry.active_by_doc.pop(updated.doc_name, None)

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None:  # pragma: no cover - only reachable if the registry is cleared
            return

        try:
            self._update(job_id, status=JobStatus.PARSING, started_at=self._clock())
            document = self._indexer.parse(job.source_path, doc_name=job.doc_name)

            self._update(
                job_id,
                status=JobStatus.EMBEDDING,
                page_count=document.page_count,
            )
            indices = self._indexer.build_indices(document)

            self._update(job_id, status=JobStatus.SAVING)
            self._indexer.save_indices(indices)

            self._update(job_id, status=JobStatus.READY, finished_at=self._clock())
            logger.info("indexed %s (%d pages)", job.doc_name, document.page_count)
        except Exception as exc:  # noqa: BLE001 - a failed job must be reportable, not fatal
            logger.exception("indexing failed for %s", job.doc_name)
            self._update(
                job_id,
                status=JobStatus.FAILED,
                finished_at=self._clock(),
                error=f"{type(exc).__name__}: {exc}",
            )
