"""Filing intake: validate an upload, store it, and report what is indexed.

Routers stay thin by delegating here; this module owns the rules about what a
filing may be called and where its bytes go.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from fastapi import UploadFile

from analyst_copilot.api.config import ApiSettings
from analyst_copilot.api.errors import (
    FileTooLarge,
    InvalidFilingName,
    UnsupportedFileType,
)
from analyst_copilot.api.jobs import IndexingJob, IndexingJobManager, JobStatus
from analyst_copilot.api.schemas import FilingSummary
from analyst_copilot.services.indexing import HybridFilingIndexer

# A doc_name becomes a directory under storage/ and is echoed in citations, so
# it is restricted to characters that are safe in both.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME_LENGTH = 120


def sanitize_doc_name(filename: Optional[str]) -> str:
    """
    Derive a storage-safe document name from an uploaded filename.

    Any directory component is discarded rather than sanitised, so a filename of
    `../../etc/passwd` cannot escape the storage root.
    """
    if not filename:
        raise InvalidFilingName("A filename is required.")

    stem = Path(filename).name
    stem = Path(stem).stem
    cleaned = _SAFE_NAME.sub("_", stem).strip("._-")
    if not cleaned:
        raise InvalidFilingName(f"Filename {filename!r} has no usable name.")
    return cleaned[:_MAX_NAME_LENGTH]


class FilingService:
    """Accept filings and describe their indexing state."""

    def __init__(
        self,
        settings: ApiSettings,
        indexer: HybridFilingIndexer,
        jobs: IndexingJobManager,
    ) -> None:
        self._settings = settings
        self._indexer = indexer
        self._jobs = jobs

    # -- intake ----------------------------------------------------------- #
    def validate_upload(self, upload: UploadFile) -> str:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in self._settings.allowed_suffixes:
            allowed = ", ".join(self._settings.allowed_suffixes)
            raise UnsupportedFileType(
                f"Unsupported file type {suffix or '(none)'}. Allowed: {allowed}."
            )
        return sanitize_doc_name(upload.filename)

    async def store_upload(self, upload: UploadFile, doc_name: str) -> Path:
        """
        Stream the upload to disk, enforcing the size limit as it arrives.

        Reading in chunks means an oversized file is rejected without ever being
        held in memory in full.
        """
        target_dir = self._settings.upload_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / f"{doc_name}.htm"
        partial = destination.with_suffix(".htm.part")

        written = 0
        try:
            with partial.open("wb") as handle:
                while True:
                    chunk = await upload.read(self._settings.upload_chunk_bytes)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > self._settings.max_upload_bytes:
                        raise FileTooLarge(
                            f"Filing exceeds the {self._settings.max_upload_bytes} byte limit."
                        )
                    handle.write(chunk)
            if written == 0:
                raise InvalidFilingName("The uploaded file is empty.")
            partial.replace(destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

        return destination

    def submit(self, doc_name: str, source_path: Path) -> IndexingJob:
        return self._jobs.submit(doc_name, source_path)

    # -- state ------------------------------------------------------------ #
    def is_indexed(self, doc_name: str) -> bool:
        return self._indexer.indices_exist(doc_name)

    def status_of(self, doc_name: str) -> JobStatus:
        """
        The filing's current state.

        An in-flight job wins over the on-disk answer, so a filing being
        re-indexed reports its live phase rather than the stale index it is
        about to replace.
        """
        active = self._jobs.active_job_for(doc_name)
        if active is not None:
            return active.status
        if self.is_indexed(doc_name):
            return JobStatus.READY
        last = next(
            (job for job in self._jobs.list_jobs() if job.doc_name == doc_name),
            None,
        )
        return last.status if last is not None else JobStatus.QUEUED

    def summary(self, doc_name: str) -> FilingSummary:
        indexed = self.is_indexed(doc_name)
        page_count = None
        if indexed:
            try:
                page_count = len(self._indexer.load_indices(doc_name).bm25_index.pages)
            except Exception:  # noqa: BLE001 - a corrupt index must not break the listing
                page_count = None
        return FilingSummary(
            doc_name=doc_name,
            indexed=indexed,
            page_count=page_count,
            status=self.status_of(doc_name),
        )

    def list_indexed(self) -> List[str]:
        """Document names with a usable index on disk, alphabetically."""
        from analyst_copilot.config.settings import get_settings

        root = get_settings().storage_dir / "bm25_indices"
        if not root.is_dir():
            return []
        return sorted(
            path.name
            for path in root.iterdir()
            if path.is_dir() and self._indexer.indices_exist(path.name)
        )
