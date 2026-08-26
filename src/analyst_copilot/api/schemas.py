"""Request and response bodies.

These are the API's contract and are intentionally decoupled from the pipeline's
internal dataclasses, so a change to `QAAnswer` cannot silently reshape the
wire format.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from analyst_copilot.api.jobs import IndexingJob, JobStatus
from analyst_copilot.services.qa.models import QAAnswer

if TYPE_CHECKING:  # pragma: no cover
    from analyst_copilot.retrieval.models import ScoredPage


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    chat_model: str
    embedding_model: str
    indexed_filings: int


class IndexState(str, Enum):
    """
    State of one retrieval index for one filing.

    BM25 and embeddings are separate artefacts that fail independently -- the
    lexical index is local and instant, embedding is a network call that can die
    halfway -- so each reports its own state rather than sharing one flag.
    """

    READY = "ready"
    BUILDING = "building"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"


class IndexInfo(BaseModel):
    """One index's state and the provenance of what is on disk."""

    state: IndexState
    page_count: Optional[int] = None
    parser_version: Optional[str] = None
    model: Optional[str] = Field(
        default=None,
        description="Embedding model for the vector index; tokenizer version for BM25.",
    )
    dimensions: Optional[int] = None
    built_at: Optional[float] = Field(default=None, description="Unix seconds.")
    size_bytes: Optional[int] = None


class FilingSummary(BaseModel):
    """A filing and the state of each of its indices."""

    doc_name: str
    page_count: Optional[int] = None
    status: IndexState = Field(
        description="Worst-first roll-up of the individual index states.",
    )
    bm25: IndexInfo
    vector: IndexInfo

    @property
    def searchable(self) -> bool:
        """Both indices must be usable before a question can be answered."""
        return self.bm25.state == IndexState.READY and self.vector.state == IndexState.READY


class FilingListResponse(BaseModel):
    filings: List[FilingSummary]


class IndexingJobResponse(BaseModel):
    """Progress of one "Add filing" request."""

    model_config = ConfigDict(use_enum_values=True)

    job_id: str
    doc_name: str
    status: JobStatus
    elapsed_seconds: float
    budget_seconds: int = Field(
        description="Seconds allowed for one filing; the spec's limit is 600.",
    )
    over_budget: bool
    page_count: Optional[int] = None
    error: Optional[str] = None
    collection: Optional[str] = Field(
        default=None, description="The folder this document is being indexed into."
    )
    source_format: Optional[str] = None

    @classmethod
    def from_job(cls, job: IndexingJob) -> "IndexingJobResponse":
        return cls(
            job_id=job.job_id,
            doc_name=job.doc_name,
            status=job.status,
            elapsed_seconds=job.elapsed_seconds,
            budget_seconds=job.budget_seconds,
            over_budget=job.over_budget,
            page_count=job.page_count,
            error=job.error,
            collection=job.collection,
            source_format=job.source_format,
        )


class Evidence(BaseModel):
    """Where an answer came from. Present only when the system answered."""

    doc_name: str
    page: int = Field(description="0-based segment index within the document.")
    display_page: int = Field(description="1-based page number for humans.")
    snippet: str
    label: str = Field(
        default="",
        description="How the source names this location: 'page 61', \"sheet 'Q4 Revenue'\".",
    )
    segment_kind: str = Field(
        default="page",
        description="page | sheet | table | section. Non-page kinds have no page number.",
    )
    location_match: str = Field(
        default="exact",
        description=(
            "How this citation relates to the page the model named. `exact`: the "
            "same page. `adjusted`/`relocated`: verification found the evidence on "
            "this page instead and moved the citation here. `inferred`: the model "
            "named no page."
        ),
    )
    model_cited_page: Optional[int] = Field(
        default=None,
        description="The page the model named, when the citation was moved off it.",
    )
    page_shift: int = Field(
        default=0,
        description="Segments between the model's page and the one carrying the evidence.",
    )


class PageResponse(BaseModel):
    """
    One page of a filing, as the retrievers see it.

    `embedded_chars` is the part of the page the vector index actually embedded.
    BM25 indexes the whole page, so on a long page the two retrievers are
    working from different amounts of text -- which is exactly why some pages
    are findable lexically and invisible semantically.
    """

    doc_name: str
    page: int
    display_page: int
    page_count: int
    text: str
    char_count: int
    embedded_chars: int
    truncated: bool
    label: str = Field(default="", description="How the source names this location.")
    segment_kind: str = Field(default="page")
    source_format: Optional[str] = Field(
        default=None, description="pdf | html | docx | xlsx | csv | markdown | text"
    )
    markdown: Optional[str] = Field(
        default=None,
        description="The stored Markdown for this segment, when it is on disk.",
    )


class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="Folder name.")
    description: str = Field(default="", max_length=500)


class CollectionDocumentInfo(BaseModel):
    """One document inside a folder, and whether it can be searched yet."""

    doc_name: str
    source_file: str = ""
    source_format: Optional[str] = None
    segment_count: Optional[int] = None
    added_at: float = 0.0
    state: IndexState


class CollectionSummary(BaseModel):
    """A folder, its documents, and how much of it is ready to answer questions."""

    name: str
    description: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    document_count: int = 0
    ready_count: int = 0
    searchable: bool = Field(
        default=False,
        description="True once at least one document is indexed. A folder does "
        "not wait for its slowest member before it can answer.",
    )
    documents: List[CollectionDocumentInfo] = Field(default_factory=list)


class CollectionListResponse(BaseModel):
    collections: List[CollectionSummary]


class RejectedUpload(BaseModel):
    """A file that never became a job, and why."""

    filename: str
    code: str
    message: str


class CollectionUploadResponse(BaseModel):
    """
    The outcome of a multi-file upload.

    Partial success is the normal case and is reported as such: one unsupported
    file among twelve must not discard the other eleven.
    """

    collection: str
    accepted: List[IndexingJobResponse] = Field(default_factory=list)
    rejected: List[RejectedUpload] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """
    One question, scoped to either a folder or a single document.

    Exactly one of `collection` and `doc_name` is required. A folder searches
    every indexed document inside it; the answer still cites exactly one.
    """

    question: str = Field(min_length=3, max_length=2000)
    doc_name: Optional[str] = Field(
        default=None, min_length=1, description="Single document to answer from."
    )
    collection: Optional[str] = Field(
        default=None, min_length=1, description="Folder to answer from."
    )

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "ChatRequest":
        if bool(self.doc_name) == bool(self.collection):
            raise ValueError("Provide exactly one of 'collection' or 'doc_name'.")
        return self


class RetrievedPage(BaseModel):
    """
    One page the retriever considered, and how it scored.

    Exposed so the UI can show *why* a page was cited rather than asking the
    analyst to trust the ranking. `ScoredPage` already carries all of this.
    """

    doc_name: str = Field(
        default="",
        description="Which document this page belongs to. Page numbers repeat "
        "across a folder, so a page without a document names nothing.",
    )
    page: int
    display_page: int
    label: str = ""
    rank: int
    fused_score: float
    bm25_score: Optional[float] = None
    vector_score: Optional[float] = None
    cited: bool = False


class ChatResponse(BaseModel):
    """
    An answer with its evidence, or a decline.

    When `found` is false the answer is the plain "not found in this filing"
    message and `evidence` is null — the caller never has to infer a decline
    from a missing field.
    """

    doc_name: str = Field(
        description="The document the answer came from. On a folder question "
        "this is the member document that carried the evidence, not the folder.",
    )
    collection: Optional[str] = Field(
        default=None, description="The folder searched, when the question was folder-scoped."
    )
    searched_documents: int = Field(
        default=1, description="How many documents retrieval actually looked at."
    )
    question: str
    found: bool
    answer: str
    evidence: Optional[Evidence] = None
    retrieval: List[RetrievedPage] = Field(
        default_factory=list,
        description="Pages considered, best first. Present on declines too, so a "
        "decline can show where the system looked.",
    )
    abstention_reason: Optional[str] = None

    @classmethod
    def from_answer(cls, answer: QAAnswer) -> "ChatResponse":
        evidence = None
        if answer.found and answer.page is not None:
            evidence = Evidence(
                doc_name=answer.doc_name,
                page=answer.page,
                display_page=answer.page + 1,
                snippet=answer.evidence_snippet,
                label=answer.location_label or f"page {answer.page + 1}",
                segment_kind=(
                    answer.segment_kind.value if answer.segment_kind else "page"
                ),
                location_match=answer.location_match or "exact",
                model_cited_page=answer.cited_page,
                page_shift=answer.page_shift,
            )
        return cls(
            doc_name=answer.doc_name,
            collection=answer.collection,
            searched_documents=answer.searched_documents,
            question=answer.question,
            found=answer.found,
            answer=answer.answer,
            evidence=evidence,
            retrieval=_retrieval_from(answer),
            abstention_reason=answer.abstention_reason,
        )


def _retrieval_from(answer: QAAnswer) -> List[RetrievedPage]:
    if answer.retrieval is None:
        return []
    hits: List["ScoredPage"] = answer.retrieval.hits
    return [
        RetrievedPage(
            doc_name=hit.page.doc_name,
            page=hit.page.citation_page,
            display_page=hit.page.citation_page + 1,
            label=hit.page.citation_label,
            rank=hit.rank,
            fused_score=round(hit.score, 4),
            bm25_score=round(hit.bm25_score, 4) if hit.bm25_score is not None else None,
            vector_score=round(hit.vector_score, 4) if hit.vector_score is not None else None,
            cited=(
                answer.found
                and hit.page.citation_page == answer.page
                and hit.page.doc_name == answer.doc_name
            ),
        )
        for hit in hits
    ]
