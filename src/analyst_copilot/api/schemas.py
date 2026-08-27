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
    from analyst_copilot.agent.models import AgentAnswer
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
    index_model: Optional[str] = Field(
        default=None,
        description="The embedding model this folder's indices were built with. "
        "Compare against the configured model: they differ after a model change, "
        "and every index has to be rebuilt before it can be searched again.",
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


class DocumentFetchRequest(BaseModel):
    """Add a document by URL instead of uploading its bytes."""

    url: str = Field(
        min_length=8,
        max_length=2048,
        description="http(s) URL of the document. Private and loopback addresses are refused.",
    )
    doc_name: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Name to store it under. Defaults to the filename in the URL.",
    )


class ChatRequest(BaseModel):
    """
    One question, scoped to either a folder or a single document.

    Exactly one of `collection` and `doc_name` is required. A folder searches
    every indexed document inside it; the answer still cites exactly one.
    """

    # One character, because "hi" is a message the assistant answers rather
    # than a malformed request. The harness routes it to a conversational reply
    # instead of searching a filing for it.
    question: str = Field(min_length=1, max_length=2000)
    doc_name: Optional[str] = Field(
        default=None, min_length=1, description="Single document to answer from."
    )
    collection: Optional[str] = Field(
        default=None, min_length=1, description="Folder to answer from."
    )
    conversation_id: Optional[str] = Field(
        default=None,
        min_length=1,
        description=(
            "Thread to record this exchange in. When provided, the question and "
            "the answer are persisted and the response carries their message ids."
        ),
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


class EvidenceInputResponse(BaseModel):
    """One figure a computed answer was derived from, and where it was read."""

    label: str
    value: str
    doc_name: str = ""
    page: Optional[int] = None
    display_page: Optional[int] = None


class AnswerPartResponse(BaseModel):
    """
    One sub-question of a compound question, answered and cited on its own.

    Present only when the question was actually split. A question asking two
    things gets two citations, because one citation cannot prove two claims.
    """

    question: str
    answer: str
    found: bool
    mode: str
    evidence: Optional[Evidence] = None
    abstention_reason: Optional[str] = None
    computation: str = ""
    inputs: List[EvidenceInputResponse] = Field(default_factory=list)


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

    # Threading. Present only when the exchange was persisted to Postgres.
    conversation_id: Optional[str] = Field(
        default=None, description="The thread this exchange was recorded in."
    )
    user_message_id: Optional[str] = Field(
        default=None, description="The stored row for the question."
    )
    message_id: Optional[str] = Field(
        default=None, description="The stored row for this answer."
    )
    latency_ms: Optional[int] = Field(
        default=None, description="Wall time of the QA pipeline, not the HTTP call."
    )

    # -- how the answer was reached ---------------------------------------- #
    mode: str = Field(
        default="fast",
        description=(
            "Which tier answered. `conversational` = not a document question, so "
            "there is nothing to cite; `fast` = hybrid retrieval; `deep` = every "
            "page of the filing was read. Branch on this before `found`: a "
            "conversational reply is neither an evidenced answer nor a decline."
        ),
    )
    intent: str = Field(
        default="document_question",
        description="How the message was classified: smalltalk, capability or document_question.",
    )
    citations: List[Evidence] = Field(
        default_factory=list,
        description="Every place this answer can be checked. One entry per answered part.",
    )
    parts: List[AnswerPartResponse] = Field(
        default_factory=list,
        description="Set only when the question was split into several questions.",
    )
    computation: str = Field(
        default="",
        description=(
            "The arithmetic behind a derived figure, re-evaluated during "
            "verification. A margin appears on no page; its inputs do."
        ),
    )
    inputs: List[EvidenceInputResponse] = Field(
        default_factory=list,
        description="The figures a derived answer was computed from, each with its page.",
    )
    validation: Optional[str] = Field(
        default=None,
        description="What the checking step concluded, and why.",
    )
    pages_read: int = Field(
        default=0, description="Pages read by the deep path. 0 when it did not run."
    )
    shards_run: int = Field(
        default=0, description="Reader agents used by the deep path. 0 when it did not run."
    )

    @classmethod
    def from_agent(cls, answer: "AgentAnswer") -> "ChatResponse":
        """
        Build the response from a harness answer.

        The primary citation is repeated in `evidence` as well as appearing in
        `citations`, so a caller written against the single-answer shape keeps
        working and a caller that understands parts sees all of them.
        """
        return cls(
            doc_name=answer.doc_name,
            collection=answer.collection,
            searched_documents=answer.searched_documents,
            question=answer.question,
            found=answer.found,
            answer=answer.answer,
            evidence=_evidence_from_citation(answer.citation),
            citations=[
                evidence
                for evidence in (_evidence_from_citation(c) for c in answer.citations)
                if evidence is not None
            ],
            parts=[_part_from(part) for part in answer.parts],
            retrieval=_retrieval_from_search(answer.retrieval, answer.citation),
            abstention_reason=answer.abstention_reason,
            mode=answer.mode.value,
            intent=answer.intent.value,
            computation=answer.computation,
            inputs=[_input_from(item) for item in answer.inputs],
            validation=answer.validation,
            pages_read=answer.pages_read,
            shards_run=answer.shards_run,
        )

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


def _evidence_from_citation(citation) -> Optional[Evidence]:
    if citation is None:
        return None
    return Evidence(
        doc_name=citation.doc_name,
        page=citation.page,
        display_page=citation.page + 1,
        snippet=citation.snippet,
        label=citation.label or f"page {citation.page + 1}",
        segment_kind=(
            citation.segment_kind.value
            if hasattr(citation.segment_kind, "value")
            else str(citation.segment_kind)
        ),
        location_match=citation.location_match or "exact",
        model_cited_page=citation.model_cited_page,
        page_shift=citation.page_shift,
    )


def _input_from(item) -> EvidenceInputResponse:
    return EvidenceInputResponse(
        label=item.label,
        value=item.value,
        doc_name=item.doc_name,
        page=item.page,
        display_page=None if item.page is None else item.page + 1,
    )


def _part_from(part) -> AnswerPartResponse:
    return AnswerPartResponse(
        question=part.question,
        answer=part.answer,
        found=part.found,
        mode=part.mode.value,
        evidence=_evidence_from_citation(part.citation),
        abstention_reason=part.abstention_reason,
        computation=part.computation,
        inputs=[_input_from(item) for item in part.inputs],
    )


def _retrieval_from_search(search, citation) -> List[RetrievedPage]:
    """
    The retrieval trace, kept even when the deep path produced the answer.

    It is the record of what the cheap tier looked at before escalating, which
    is exactly the diagnostic worth showing when an answer took 60 seconds.
    """
    if search is None:
        return []
    cited_page = citation.page if citation is not None else None
    cited_doc = citation.doc_name if citation is not None else None
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
                hit.page.citation_page == cited_page
                and hit.page.doc_name == cited_doc
            ),
        )
        for hit in search.hits
    ]


class ConversationCreateRequest(BaseModel):
    """Start a thread. A thread is pinned to the filing it was started in."""

    collection: Optional[str] = Field(
        default=None, min_length=1, max_length=120, description="Filing the thread is pinned to."
    )
    title: Optional[str] = Field(
        default=None, max_length=200, description="Defaults to 'New conversation'."
    )


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageResponse(BaseModel):
    """One stored exchange row, shaped for the UI's history rendering."""

    id: str
    role: str  # user | assistant
    content: str
    created_at: str = Field(description="ISO-8601, UTC.")
    found: Optional[bool] = None
    page: Optional[int] = None
    abstention_reason: Optional[str] = None
    latency_ms: Optional[int] = None
    retrieval: Optional[List[RetrievedPage]] = None
    result: Optional[dict] = Field(
        default=None,
        description="The full ChatResponse as served, so history re-renders verbatim.",
    )


class ConversationSummary(BaseModel):
    """A thread as it appears in the sidebar: no message bodies."""

    id: str
    collection: Optional[str] = None
    title: str
    created_at: str
    updated_at: str


class ConversationDetail(ConversationSummary):
    messages: List[MessageResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary] = Field(default_factory=list)
