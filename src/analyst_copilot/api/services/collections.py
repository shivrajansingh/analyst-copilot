"""Folder intake: create a folder, accept many files into it, report its state."""

from __future__ import annotations

import logging
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
from analyst_copilot.api.fetching import FetchError, RemoteDocumentFetcher
from analyst_copilot.api.filings import sanitize_doc_name
from analyst_copilot.api.jobs import IndexingJobManager, JobStatus
from analyst_copilot.api.schemas import (
    CollectionDocumentInfo,
    CollectionSummary,
    CollectionUploadResponse,
    IndexingJobResponse,
    IndexState,
    PageResponse,
    RejectedUpload,
)
from analyst_copilot.config.settings import get_settings
from analyst_copilot.collections.indexer import CollectionIndexer
from analyst_copilot.collections.models import CollectionDocument, InvalidCollectionName
from analyst_copilot.collections.store import CollectionNotFound, CollectionStore

logger = logging.getLogger(__name__)


class CollectionApiService:
    """The HTTP-facing half of collections; the domain logic lives in `collections/`."""

    def __init__(
        self,
        settings: ApiSettings,
        indexer: CollectionIndexer,
        jobs: IndexingJobManager,
        fetcher: Optional[RemoteDocumentFetcher] = None,
    ) -> None:
        self._settings = settings
        self._indexer = indexer
        self._store: CollectionStore = indexer.store
        self._jobs = jobs
        self._fetcher = fetcher or RemoteDocumentFetcher(
            max_bytes=settings.max_upload_bytes,
            allowed_suffixes=settings.allowed_suffixes,
            timeout_seconds=settings.fetch_timeout_seconds,
            allow_private_network=settings.allow_private_network_fetch,
            user_agent=settings.fetch_user_agent,
        )

    # -- lifecycle ---------------------------------------------------------- #
    def create(self, name: str, description: str = "") -> CollectionSummary:
        try:
            collection = self._store.create(name, description=description)
        except InvalidCollectionName as exc:
            raise InvalidFilingName(str(exc)) from exc
        return self._summarize(collection.name)

    def list_all(self) -> List[CollectionSummary]:
        return [self._summarize(item.name) for item in self._store.list_all()]

    def summary(self, name: str) -> CollectionSummary:
        return self._summarize(self._require(name).name)

    def delete(self, name: str, remove_uploads: bool = False) -> None:
        self._require(name)
        self._store.delete(name, remove_uploads=remove_uploads)

    def remove_document(self, name: str, doc_name: str) -> None:
        self._require(name)
        self._store.remove_document(name, doc_name)

    # -- intake ------------------------------------------------------------- #
    async def add_documents(
        self,
        name: str,
        files: List[UploadFile],
    ) -> CollectionUploadResponse:
        """
        Store every acceptable file and queue one indexing job per document.

        One job per document, not one per request: a folder of twelve filings
        should report which of them is slow and which has failed, and a single
        job covering all of them can report neither.

        A rejected file does not fail the request. Dropping twelve files and
        losing all of them because one was a PNG is the wrong behaviour; the
        response says what was accepted and what was not.
        """
        try:
            collection = self._store.create(name)
        except InvalidCollectionName as exc:
            raise InvalidFilingName(str(exc)) from exc

        accepted: List[IndexingJobResponse] = []
        rejected: List[RejectedUpload] = []

        for upload in files:
            filename = upload.filename or "(unnamed)"
            try:
                doc_name, suffix = self._validate(upload)
                stored = await self._store_upload(collection.name, upload, doc_name, suffix)
            except (UnsupportedFileType, FileTooLarge, InvalidFilingName) as exc:
                rejected.append(
                    RejectedUpload(filename=filename, code=exc.code, message=exc.message)
                )
                continue

            # Record membership now, before indexing starts. Waiting until the
            # job finishes would leave a folder reporting zero documents while
            # twelve of them are being embedded, which reads as a lost upload.
            # The indexer fills in the format and segment count when it knows.
            self._store.add_document(
                collection.name,
                CollectionDocument(doc_name=doc_name, source_file=stored.name),
            )
            job = self._jobs.submit(
                doc_name=doc_name,
                source_path=stored,
                collection=collection.name,
                source_format=suffix.lstrip("."),
            )
            accepted.append(IndexingJobResponse.from_job(job))

        return CollectionUploadResponse(
            collection=collection.name,
            accepted=accepted,
            rejected=rejected,
        )

    def page(self, name: str, doc_name: str, page_index: int) -> PageResponse:
        """
        One segment of one document in this folder, as the retrievers saw it.

        Read from the stored index rather than re-parsing: the indexed text is
        what retrieval and the verifier actually worked from, so it is the only
        text a reader should be shown as evidence.
        """
        self._require(name)
        pages = self._store.vector_store(name).load_pages(doc_name)
        if pages is None:
            raise FilingNotFound(f"No indexed pages for {doc_name!r} in folder {name!r}.")

        match = next((page for page in pages if page.page_index == page_index), None)
        if match is None:
            raise FilingNotFound(
                f"{doc_name} has {len(pages)} segments; {page_index} is not one of them."
            )

        metadata = self._store.vector_store(name).load_metadata(doc_name)
        cap = metadata.max_chars_per_page if metadata else len(match.text)
        manifest = self._store.markdown_store(name).load_manifest(doc_name)
        return PageResponse(
            doc_name=doc_name,
            page=match.page_index,
            display_page=match.page_index + 1,
            page_count=len(pages),
            text=match.text,
            char_count=len(match.text),
            embedded_chars=min(cap, len(match.text)),
            truncated=len(match.text) > cap,
            label=match.citation_label,
            segment_kind=match.segment_kind.value,
            source_format=manifest.source_format.value if manifest else None,
            markdown=self._store.markdown_store(name).load_markdown(doc_name, page_index),
        )

    def fetch_document(
        self,
        name: str,
        url: str,
        doc_name: Optional[str] = None,
    ) -> CollectionUploadResponse:
        """
        Download one document from a URL and queue it for indexing.

        Reported through the same accepted/rejected shape as an upload, so the
        UI has one code path for "a document joined this folder" regardless of
        how it arrived. A fetch that fails is a rejection, not a 500: a URL that
        404s or points at a JPEG is the user's input being wrong, not the
        service breaking.
        """
        try:
            collection = self._store.create(name)
        except InvalidCollectionName as exc:
            raise InvalidFilingName(str(exc)) from exc

        requested = sanitize_doc_name(doc_name) if doc_name else None
        try:
            fetched = self._fetcher.fetch(
                url,
                destination_dir=self._store.uploads_dir(collection.name),
                doc_name=requested,
            )
        except FetchError as exc:
            return CollectionUploadResponse(
                collection=collection.name,
                accepted=[],
                rejected=[RejectedUpload(filename=url, code="fetch_failed", message=str(exc))],
            )

        # The fetcher already refused anything the registry cannot parse, so a
        # name is guaranteed to be derivable here.
        final_name = requested or sanitize_doc_name(fetched.filename)
        stored = fetched.path
        if final_name != Path(fetched.filename).stem:
            stored = fetched.path.with_name(f"{final_name}{fetched.suffix}")
            fetched.path.replace(stored)

        self._store.add_document(
            collection.name,
            CollectionDocument(doc_name=final_name, source_file=stored.name),
        )
        job = self._jobs.submit(
            doc_name=final_name,
            source_path=stored,
            collection=collection.name,
            source_format=fetched.suffix.lstrip("."),
        )
        logger.info(
            "fetched %s (%d bytes) into folder %s as %s",
            fetched.final_url,
            fetched.bytes_written,
            collection.name,
            final_name,
        )
        return CollectionUploadResponse(
            collection=collection.name,
            accepted=[IndexingJobResponse.from_job(job)],
            rejected=[],
        )

    def jobs(self, name: str) -> List[IndexingJobResponse]:
        self._require(name)
        return [
            IndexingJobResponse.from_job(job)
            for job in self._jobs.jobs_for_collection(name)
        ]

    # -- internals ---------------------------------------------------------- #
    def _require(self, name: str):
        try:
            return self._store.require(name)
        except CollectionNotFound as exc:
            raise FilingNotFound(str(exc)) from exc

    def _validate(self, upload: UploadFile) -> tuple:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in self._settings.allowed_suffixes:
            allowed = ", ".join(self._settings.allowed_suffixes)
            raise UnsupportedFileType(
                f"Unsupported file type {suffix or '(none)'}. Allowed: {allowed}."
            )
        return sanitize_doc_name(upload.filename), suffix

    async def _store_upload(
        self,
        collection: str,
        upload: UploadFile,
        doc_name: str,
        suffix: str,
    ) -> Path:
        """Stream one file into the folder's upload directory, size-checked as it arrives."""
        target_dir = self._store.uploads_dir(collection)
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / f"{doc_name}{suffix}"
        partial = destination.with_name(f"{destination.name}.part")

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
                            f"{upload.filename!r} exceeds the "
                            f"{self._settings.max_upload_bytes} byte limit."
                        )
                    handle.write(chunk)
            if written == 0:
                raise InvalidFilingName(f"{upload.filename!r} is empty.")
            partial.replace(destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

        return destination

    def _summarize(self, name: str) -> CollectionSummary:
        collection = self._store.require(name)
        documents: List[CollectionDocumentInfo] = []
        ready = 0

        for member in collection.documents:
            state = self._document_state(name, member.doc_name)
            if state is IndexState.READY:
                ready += 1
            documents.append(
                CollectionDocumentInfo(
                    doc_name=member.doc_name,
                    source_file=member.source_file,
                    source_format=(
                        member.source_format.value if member.source_format else None
                    ),
                    segment_count=member.segment_count,
                    added_at=member.added_at,
                    state=state,
                )
            )

        return CollectionSummary(
            name=collection.name,
            description=collection.description,
            index_model=self._index_model(name, documents),
            created_at=collection.created_at,
            updated_at=collection.updated_at,
            document_count=len(documents),
            ready_count=ready,
            # A folder is searchable the moment one document in it is ready.
            # Waiting for all of them would block a twelve-filing folder on its
            # slowest member for no benefit -- the others can already answer.
            searchable=ready > 0,
            documents=documents,
        )

    def _index_model(
        self,
        collection: str,
        documents: List[CollectionDocumentInfo],
    ) -> Optional[str]:
        """
        The embedding model this folder's indices were built with.

        Read from the first indexed document rather than every one: they are all
        built by the same process with the same configuration, and the reason
        this is surfaced at all is to be compared against the *configured*
        model, where any one of them answers the question.
        """
        store = self._store.vector_store(collection)
        for document in documents:
            if document.state is not IndexState.READY:
                continue
            metadata = store.load_metadata(document.doc_name)
            if metadata is not None:
                return metadata.embedding_model
        return None

    def _document_state(self, collection: str, doc_name: str) -> IndexState:
        if self._indexer.document_is_indexed(collection, doc_name):
            return IndexState.READY

        job = self._jobs.active_job_for(doc_name, collection=collection)
        if job is not None and not job.status.is_terminal:
            return IndexState.BUILDING

        last = next(
            (
                item
                for item in self._jobs.jobs_for_collection(collection)
                if item.doc_name == doc_name
            ),
            None,
        )
        if last is not None and last.status == JobStatus.FAILED:
            return IndexState.FAILED

        bm25 = self._store.bm25_store(collection)
        vector = self._store.vector_store(collection)
        if bm25.is_stale(doc_name) or vector.is_stale(doc_name):
            return IndexState.STALE
        return IndexState.MISSING
