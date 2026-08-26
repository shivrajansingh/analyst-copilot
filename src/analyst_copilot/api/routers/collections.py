"""Folders: create one, upload documents into it, ask questions of all of them."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, status
from starlette.concurrency import run_in_threadpool

from analyst_copilot.api.dependencies import get_collection_service
from analyst_copilot.api.schemas import (
    CollectionCreateRequest,
    CollectionListResponse,
    CollectionSummary,
    CollectionUploadResponse,
    IndexingJobResponse,
    PageResponse,
)
from analyst_copilot.api.services.collections import CollectionApiService

router = APIRouter(prefix="/collections", tags=["folders"])


@router.get("", response_model=CollectionListResponse, summary="List folders")
async def list_collections(
    service: CollectionApiService = Depends(get_collection_service),
) -> CollectionListResponse:
    return CollectionListResponse(collections=service.list_all())


@router.post(
    "",
    response_model=CollectionSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a folder",
)
async def create_collection(
    request: CollectionCreateRequest,
    service: CollectionApiService = Depends(get_collection_service),
) -> CollectionSummary:
    """
    Create a folder, or return the existing one of that name.

    Idempotent on purpose: the natural client is an upload form, and a second
    file dropped into "Boeing 2022" must land in the folder the first one made.
    """
    return service.create(request.name, request.description)


@router.get(
    "/{name}",
    response_model=CollectionSummary,
    summary="One folder and its documents",
)
async def get_collection(
    name: str,
    service: CollectionApiService = Depends(get_collection_service),
) -> CollectionSummary:
    return service.summary(name)


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a folder",
)
async def delete_collection(
    name: str,
    remove_uploads: bool = False,
    service: CollectionApiService = Depends(get_collection_service),
) -> None:
    """
    Remove a folder's indices, and its uploaded originals only if asked.

    Indices are regenerable and the source files are not, so the destructive
    half is opt-in rather than the default.
    """
    service.delete(name, remove_uploads=remove_uploads)


@router.post(
    "/{name}/documents",
    response_model=CollectionUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add documents to a folder",
)
async def add_documents(
    name: str,
    files: List[UploadFile] = File(..., description="One or more documents."),
    service: CollectionApiService = Depends(get_collection_service),
) -> CollectionUploadResponse:
    """
    Upload any number of documents into one folder, in one request.

    Each file gets its own indexing job, so a folder of twelve filings reports
    twelve progress rows rather than one bar that says nothing about which
    document is slow. A file rejected for its type does not stop the others:
    the response lists what was accepted and what was not, and the caller
    decides what to do about the rejects.
    """
    return await service.add_documents(name, files)


@router.delete(
    "/{name}/documents/{doc_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove one document from a folder",
)
async def remove_document(
    name: str,
    doc_name: str,
    service: CollectionApiService = Depends(get_collection_service),
) -> None:
    await run_in_threadpool(service.remove_document, name, doc_name)


@router.get(
    "/{name}/documents/{doc_name}/pages/{page_index}",
    response_model=PageResponse,
    summary="Read one segment behind a citation",
)
async def read_page(
    name: str,
    doc_name: str,
    page_index: int,
    service: CollectionApiService = Depends(get_collection_service),
) -> PageResponse:
    """The text and Markdown of one segment, so a citation can be checked."""
    return await run_in_threadpool(service.page, name, doc_name, page_index)


@router.get(
    "/{name}/jobs",
    response_model=List[IndexingJobResponse],
    summary="Indexing progress for a folder",
)
async def collection_jobs(
    name: str,
    service: CollectionApiService = Depends(get_collection_service),
) -> List[IndexingJobResponse]:
    """Every job for this folder's documents, newest first."""
    return service.jobs(name)
