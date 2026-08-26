"""FastAPI application factory.

The service is a thin HTTP shell over the existing pipeline: it imports
`QuestionAnsweringService` and `HybridFilingIndexer` and adds no retrieval,
prompting or verification logic of its own. Everything that decides an answer
still lives in `analyst_copilot.services`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from analyst_copilot.api.config import ApiSettings, get_api_settings
from analyst_copilot.api.dependencies import get_job_manager
from analyst_copilot.api.errors import register_exception_handlers
from analyst_copilot.api.routers import chat, collections, filings, health

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: ApiSettings = app.state.settings
    logger.info("%s %s listening", settings.title, settings.version)
    try:
        yield
    finally:
        # Let an in-flight index finish writing rather than leaving a half-saved
        # index on disk for the next process to load.
        get_job_manager().shutdown(wait=True)
        logger.info("indexing workers stopped")


def create_app(settings: Optional[ApiSettings] = None) -> FastAPI:
    settings = settings or get_api_settings()

    app = FastAPI(
        title=settings.title,
        version=settings.version,
        description=settings.description,
        root_path=settings.root_path,
        lifespan=_lifespan,
    )
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(filings.router, prefix=API_PREFIX)
    app.include_router(filings.jobs_router, prefix=API_PREFIX)
    app.include_router(collections.router, prefix=API_PREFIX)
    app.include_router(chat.router, prefix=API_PREFIX)

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()
