"""Request and response bodies.

These are the API's contract and are intentionally decoupled from the pipeline's
internal dataclasses, so a change to `QAAnswer` cannot silently reshape the
wire format.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from analyst_copilot.api.jobs import IndexingJob, JobStatus
from analyst_copilot.services.qa.models import QAAnswer


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    chat_model: str
    embedding_model: str
    indexed_filings: int


class FilingSummary(BaseModel):
    """A filing the service can answer questions about."""

    doc_name: str
    indexed: bool
    page_count: Optional[int] = None
    status: JobStatus


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
    retrieved_pages: List[int] = Field(default_factory=list)
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
            retrieved_pages=[hit.page.citation_page for hit in answer.retrieval.hits]
            if answer.retrieval is not None
            else [],
            abstention_reason=answer.abstention_reason,
        )
