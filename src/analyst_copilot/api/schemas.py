"""Request and response bodies.

These are the API's contract and are intentionally decoupled from the pipeline's
internal dataclasses, so a change to `QAAnswer` cannot silently reshape the
wire format.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from pydantic import BaseModel, ConfigDict, Field

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
        )


class Evidence(BaseModel):
    """Where an answer came from. Present only when the system answered."""

    doc_name: str
    page: int = Field(description="0-based page index within the filing.")
    display_page: int = Field(description="1-based page number for humans.")
    snippet: str


class ChatRequest(BaseModel):
    doc_name: str = Field(min_length=1, description="Filing to answer from.")
    question: str = Field(min_length=3, max_length=2000)


class RetrievedPage(BaseModel):
    """
    One page the retriever considered, and how it scored.

    Exposed so the UI can show *why* a page was cited rather than asking the
    analyst to trust the ranking. `ScoredPage` already carries all of this.
    """

    page: int
    display_page: int
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

    doc_name: str
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
            )
        return cls(
            doc_name=answer.doc_name,
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
            page=hit.page.citation_page,
            display_page=hit.page.citation_page + 1,
            rank=hit.rank,
            fused_score=round(hit.score, 4),
            bm25_score=round(hit.bm25_score, 4) if hit.bm25_score is not None else None,
            vector_score=round(hit.vector_score, 4) if hit.vector_score is not None else None,
            cited=answer.found and hit.page.citation_page == answer.page,
        )
        for hit in hits
    ]
