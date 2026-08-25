"""Application errors and their HTTP representation.

Routers raise these instead of `HTTPException` so the failure vocabulary lives
in one place and every error response has the same shape:

    {"error": {"code": "filing_not_indexed", "message": "..."}}
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Base class for errors that map onto a specific HTTP response."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FilingNotFound(ApiError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "filing_not_found"


class FilingNotIndexed(ApiError):
    status_code = status.HTTP_409_CONFLICT
    code = "filing_not_indexed"


class JobNotFound(ApiError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "job_not_found"


class UnsupportedFileType(ApiError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_file_type"


class FileTooLarge(ApiError):
    status_code = 413  # name differs across Starlette versions
    code = "file_too_large"


class InvalidFilingName(ApiError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_filing_name"


class UpstreamUnavailable(ApiError):
    """The chat or embedding provider failed."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_unavailable"


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(FileNotFoundError)
    async def _handle_missing_file(_: Request, exc: FileNotFoundError) -> JSONResponse:
        return _error_response(status.HTTP_404_NOT_FOUND, "not_found", str(exc))
