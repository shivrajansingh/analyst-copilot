"""
Settings for the HTTP service.

Deliberately separate from `analyst_copilot.config.settings`: that module
configures the QA pipeline (model endpoints, retrieval weights) and is shared by
the CLI scripts and the tests. This one configures the process that serves it —
ports, limits, concurrency — and is read by nothing but the API layer.

All fields are environment-driven with an `API_` prefix, so `API_PORT=9000`
configures the service without any risk of colliding with a pipeline variable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from analyst_copilot.api.fetching import DEFAULT_USER_AGENT
from analyst_copilot.config.settings import PROJECT_ROOT, get_settings
from analyst_copilot.parsing.formats import SUPPORTED_SUFFIXES


class ApiSettings(BaseSettings):
    """Configuration for the FastAPI application."""

    model_config = SettingsConfigDict(
        env_prefix="API_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Aliased fields (DATABASE_URL) stay settable by keyword in tests.
        populate_by_name=True,
    )

    title: str = "Analyst Copilot API"
    version: str = "1.0.0"
    description: str = (
        "Question answering over SEC filings. Every answer carries the document "
        "and page it came from, or declines."
    )

    host: str = "127.0.0.1"
    port: int = 8000
    root_path: str = ""

    # A browser UI is served from a different origin during development.
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])

    # Uploads. The largest filing in the practice corpus is ~16 MB; a filer's
    # own PDF of the same document runs larger, so the ceiling is generous.
    max_upload_bytes: int = 64 * 1024 * 1024
    upload_chunk_bytes: int = 1024 * 1024
    # Every format the parser registry can handle. Sourced from the registry
    # rather than restated, so registering a parser is the only step needed to
    # make its format uploadable.
    allowed_suffixes: Tuple[str, ...] = SUPPORTED_SUFFIXES

    # Fetching a document from a user-supplied URL. Private, loopback and
    # link-local addresses are refused by default: without that, anyone who can
    # reach the chat box can make the server read its own cloud metadata
    # endpoint. Enable only for a deployment whose document store is internal.
    allow_private_network_fetch: bool = False
    fetch_timeout_seconds: int = 30
    # Some archives refuse anonymous clients. SEC's fair-access policy wants a
    # contact address here and answers 403 without one:
    #   API_FETCH_USER_AGENT="Acme Research analyst@acme.com"
    fetch_user_agent: str = DEFAULT_USER_AGENT

    # Indexing. Embedding is network-bound, so more workers mostly means more
    # concurrent load on the embedding provider rather than more throughput.
    max_concurrent_index_jobs: int = 2

    # The challenge requires one filing to finish indexing within 10 minutes.
    # Exposed on the status payload so a UI can show progress against it.
    index_budget_seconds: int = 600

    # Postgres connection for product state (chat history today). Read from
    # DATABASE_URL — the convention Docker and every PAAS speaks — with the
    # API_-prefixed form as the fallback. When unset the API answers questions
    # normally but records nothing: the conversations endpoints return 503.
    database_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "API_DATABASE_URL"),
    )

    @property
    def upload_dir(self) -> Path:
        """Uploads land beside the corpus so an added filing behaves like a bundled one."""
        return get_settings().filings_dir


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()
