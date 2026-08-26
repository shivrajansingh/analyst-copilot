"""The "Add filing" control and the status it reports."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, status

from analyst_copilot.api.dependencies import get_filing_service, get_job_manager
from analyst_copilot.api.errors import FilingNotFound, JobNotFound
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.jobs import IndexingJobManager, JobStatus
from analyst_copilot.api.schemas import (
    FilingListResponse,
    FilingSummary,
    IndexingJobResponse,
    PageResponse,
)

router = APIRouter(prefix="/filings", tags=["filings"])
jobs_router = APIRouter(prefix="/jobs", tags=["filings"])


@router.post(
    "",
    response_model=IndexingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add a filing",
)
async def add_filing(
    file: UploadFile = File(description="An SEC filing in HTML (.htm or .html)."),
    filings: FilingService = Depends(get_filing_service),
) -> IndexingJobResponse:
    """
    Upload a filing and start indexing it.

    Returns 202 immediately with a job whose status can be polled; indexing a
    filing takes minutes, so it deliberately does not block the request.
    Uploading a filing that is already being indexed joins the job in flight
    rather than embedding it twice.
    """
    doc_name, suffix = filings.validate_upload(file)
    source_path = await filings.store_upload(file, doc_name, suffix)
    job = filings.submit(doc_name, source_path)
    return IndexingJobResponse.from_job(job)


@router.get("", response_model=FilingListResponse, summary="List queryable filings")
def list_filings(
    filings: FilingService = Depends(get_filing_service),
) -> FilingListResponse:
    """
    Every filing the service knows about, with each index's state.

    Filings only half-indexed are included on purpose: the library is where a
    failed embedding pass becomes visible.
    """
    summaries: List[FilingSummary] = [
        filings.summary(doc_name) for doc_name in filings.list_known()
    ]
    return FilingListResponse(filings=summaries)


@router.get(
    "/{doc_name}/pages/{page}",
    response_model=PageResponse,
    summary="Read one page of a filing",
)
def filing_page(
    doc_name: str,
    page: int,
    filings: FilingService = Depends(get_filing_service),
) -> PageResponse:
    """
    The page text behind a citation.

    Showing the cited snippet inside its whole page is the difference between a
    citation and a proof -- a figure read out of context is exactly what an
    analyst cannot act on.
    """
    return filings.page(doc_name, page)


@router.get(
    "/{doc_name}/status",
    response_model=IndexingJobResponse,
    summary="Processing status for one filing",
)
def filing_status(
    doc_name: str,
    filings: FilingService = Depends(get_filing_service),
    jobs: IndexingJobManager = Depends(get_job_manager),
) -> IndexingJobResponse:
    """
    Progress for a filing, whether it is mid-index or already on disk.

    Falls back to the on-disk index when no job is in memory, so a filing that
    was indexed before the last restart still reports `ready`.
    """
    job = jobs.active_job_for(doc_name) or next(
        (item for item in jobs.list_jobs() if item.doc_name == doc_name), None
    )
    if job is not None:
        return IndexingJobResponse.from_job(job)

    if not filings.is_indexed(doc_name):
        raise FilingNotFound(f"No filing named {doc_name!r} has been added.")

    summary = filings.summary(doc_name)
    return IndexingJobResponse(
        job_id="",
        doc_name=doc_name,
        status=JobStatus.READY,
        elapsed_seconds=0.0,
        budget_seconds=0,
        over_budget=False,
        page_count=summary.page_count,
    )


@jobs_router.get(
    "/{job_id}",
    response_model=IndexingJobResponse,
    summary="Processing status by job id",
)
def job_status(
    job_id: str,
    jobs: IndexingJobManager = Depends(get_job_manager),
) -> IndexingJobResponse:
    job = jobs.get(job_id)
    if job is None:
        raise JobNotFound(f"No indexing job with id {job_id!r}.")
    return IndexingJobResponse.from_job(job)
