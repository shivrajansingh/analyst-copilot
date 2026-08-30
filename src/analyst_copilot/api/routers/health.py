"""Liveness and configuration readout."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from analyst_copilot.api.config import ApiSettings, get_api_settings
from analyst_copilot.api.dependencies import get_filing_service
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.schemas import HealthResponse
from analyst_copilot.config.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health(
    settings: ApiSettings = Depends(get_api_settings),
    filings: FilingService = Depends(get_filing_service),
) -> HealthResponse:
    """Report which models are configured and how many filings are queryable."""
    pipeline = get_settings()
    return HealthResponse(
        version=settings.version,
        chat_model=pipeline.openai_model or "(unset)",
        embedding_model=pipeline.resolved_embedding_model,
        indexed_filings=len(filings.list_searchable()),
        validator_model=pipeline.resolved_validator_model or "(unset)",
        independent_validator=pipeline.validator_is_separate,
    )
