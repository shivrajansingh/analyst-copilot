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
    FilingNotFound,
    InvalidFilingName,
    UnsupportedFileType,
)
from analyst_copilot.api.jobs import IndexingJob, IndexingJobManager, JobStatus
from analyst_copilot.api.schemas import (
    FilingSummary,
    IndexInfo,
    IndexState,
    PageResponse,
)
from analyst_copilot.retrieval.bm25.storage import BM25IndexStore
from analyst_copilot.retrieval.vector.storage import VectorIndexStore
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
        bm25_store: Optional[BM25IndexStore] = None,
        vector_store: Optional[VectorIndexStore] = None,
    ) -> None:
        self._settings = settings
        self._indexer = indexer
        self._jobs = jobs
        # Read straight from the stores: the library needs metadata for every
        # filing at once, and going through the indexer would load each index.
        self._bm25_store = bm25_store or BM25IndexStore()
        self._vector_store = vector_store or VectorIndexStore()

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

    def job_status_of(self, doc_name: str) -> Optional[JobStatus]:
        """
        The status of this filing's job, or None when it has never had one.

        None matters: a filing that was indexed by the bulk CLI has no job in
        this process, and reporting a default of `queued` for it would render as
        "building" forever.
        """
        active = self._jobs.active_job_for(doc_name)
        if active is not None:
            return active.status
        last = next(
            (job for job in self._jobs.list_jobs() if job.doc_name == doc_name),
            None,
        )
        return last.status if last is not None else None

    def summary(self, doc_name: str) -> FilingSummary:
        """The filing's page count plus the state of each index independently."""
        job_status = self.job_status_of(doc_name)
        bm25 = self._bm25_info(doc_name, job_status)
        vector = self._vector_info(doc_name, job_status)
        return FilingSummary(
            doc_name=doc_name,
            page_count=bm25.page_count or vector.page_count,
            status=_roll_up(bm25.state, vector.state),
            bm25=bm25,
            vector=vector,
        )

    def _bm25_info(self, doc_name: str, job_status: Optional[JobStatus]) -> IndexInfo:
        metadata = self._bm25_store.load_metadata(doc_name)
        state = self._state_for(
            usable=self._bm25_store.exists(doc_name),
            stale=self._bm25_store.is_stale(doc_name),
            job_status=job_status,
        )
        return IndexInfo(
            state=state,
            page_count=metadata.page_count if metadata else None,
            parser_version=metadata.parser_version if metadata else None,
            model=metadata.tokenizer_version if metadata else None,
            built_at=_built_at(self._bm25_store.index_dir(doc_name)),
            size_bytes=_dir_size(self._bm25_store.index_dir(doc_name)),
        )

    def _vector_info(self, doc_name: str, job_status: Optional[JobStatus]) -> IndexInfo:
        metadata = self._vector_store.load_metadata(doc_name)
        state = self._state_for(
            usable=self._vector_store.exists(doc_name),
            stale=self._vector_store.is_stale(doc_name),
            job_status=job_status,
        )
        return IndexInfo(
            state=state,
            page_count=metadata.page_count if metadata else None,
            parser_version=metadata.parser_version if metadata else None,
            model=metadata.embedding_model if metadata else None,
            dimensions=metadata.dimensions if metadata else None,
            built_at=_built_at(self._vector_store.index_dir(doc_name)),
            size_bytes=_dir_size(self._vector_store.index_dir(doc_name)),
        )

    @staticmethod
    def _state_for(
        usable: bool,
        stale: bool,
        job_status: Optional[JobStatus],
    ) -> IndexState:
        """
        A usable index on disk wins over any job state.

        Otherwise a live job decides: a filing being re-indexed reads as
        `building`, and one whose last attempt died reads as `failed` rather
        than merely `missing` -- the difference between "add it" and "retry it".
        """
        if usable:
            return IndexState.READY
        if job_status is not None and not job_status.is_terminal:
            return IndexState.BUILDING
        if stale:
            return IndexState.STALE
        if job_status == JobStatus.FAILED:
            return IndexState.FAILED
        return IndexState.MISSING

    def page(self, doc_name: str, page_index: int) -> PageResponse:
        """
        One page's full text, plus how much of it was embedded.

        Reads the stored page text rather than re-parsing the filing: the
        indexed text is what retrieval and the verifier actually worked from,
        so it is the only text a reader should be shown as evidence.
        """
        pages = self._vector_store.load_pages(doc_name)
        if pages is None:
            raise FilingNotFound(f"No indexed pages for {doc_name!r}.")

        match = next((page for page in pages if page.page_index == page_index), None)
        if match is None:
            raise FilingNotFound(
                f"{doc_name} has {len(pages)} pages; page {page_index} is not one of them."
            )

        metadata = self._vector_store.load_metadata(doc_name)
        cap = metadata.max_chars_per_page if metadata else len(match.text)
        return PageResponse(
            doc_name=doc_name,
            page=match.page_index,
            display_page=match.page_index + 1,
            page_count=len(pages),
            text=match.text,
            char_count=len(match.text),
            embedded_chars=min(cap, len(match.text)),
            truncated=len(match.text) > cap,
        )

    def list_known(self) -> List[str]:
        """
        Every filing with an index directory, alphabetically.

        Includes filings that only one retriever managed to index. A filing with
        BM25 but no embeddings is precisely what the library exists to surface --
        hiding it until both succeed would hide the failure.
        """
        names = set()
        for store in (self._bm25_store, self._vector_store):
            root = store.index_dir("_").parent
            if root.is_dir():
                names.update(path.name for path in root.iterdir() if path.is_dir())
        names.update(job.doc_name for job in self._jobs.list_jobs())
        return sorted(names)

    def list_searchable(self) -> List[str]:
        """Filings both retrievers can serve, i.e. what /chat will accept."""
        return [name for name in self.list_known() if self.is_indexed(name)]


def _built_at(index_dir: Path) -> Optional[float]:
    metadata = index_dir / "metadata.json"
    try:
        return metadata.stat().st_mtime
    except OSError:
        return None


def _dir_size(index_dir: Path) -> Optional[int]:
    try:
        return sum(item.stat().st_size for item in index_dir.iterdir() if item.is_file())
    except OSError:
        return None


_ROLL_UP_ORDER = (
    IndexState.FAILED,
    IndexState.BUILDING,
    IndexState.STALE,
    IndexState.MISSING,
)


def _roll_up(*states: IndexState) -> IndexState:
    """
    One headline state for a filing, worst-first.

    A filing is only `ready` when every index is; anything else surfaces the
    most actionable problem rather than averaging it away.
    """
    for candidate in _ROLL_UP_ORDER:
        if candidate in states:
            return candidate
    return IndexState.READY
