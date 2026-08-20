"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


def _strip_api_suffix(url: str) -> str:
    url = url.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/embeddings"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url


def _openai_v1_base(url: str) -> str:
    """Normalize a host or API URL to an OpenAI-compatible /v1 base URL."""
    base = _strip_api_suffix(url.rstrip("/"))
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Paths
    project_root: Path = PROJECT_ROOT
    filings_dir: Path = PROJECT_ROOT / "filings"
    storage_dir: Path = PROJECT_ROOT / "storage"
    data_dir: Path = PROJECT_ROOT / "data"

    # Chat LLM (OpenAI-compatible)
    openai_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""

    # Embedding server (OpenAI-compatible /v1/embeddings — Ollama, remote APIs, etc.)
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""

    # Legacy aliases (used when EMBEDDING_* vars are not set)
    ollama_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "bge-m3"
    openai_embedding_model: str = "text-embedding-3-small"

    # Retrieval
    retrieval_max_chars_per_page: int = 2500
    hybrid_bm25_weight: float = 0.45
    hybrid_vector_weight: float = 0.55
    hybrid_candidate_pool: int = 80
    hybrid_rrf_k: int = 60
    hybrid_rrf_weight: float = 0.6
    hybrid_weighted_weight: float = 0.4
    hybrid_statement_boost: float = 1.25

    # QA / abstention
    qa_top_k: int = 5
    qa_min_retrieval_score: float = 0.25
    qa_max_evidence_chars: int = 2200
    qa_temperature: float = 0.0
    qa_max_tokens: int = 4096
    not_found_message: str = "not found in this filing"

    @property
    def chat_base_url(self) -> str:
        """OpenAI-compatible base URL for chat (/v1/chat/completions)."""
        if not self.openai_url:
            return ""
        return _strip_api_suffix(self.openai_url)

    @property
    def resolved_embedding_base_url(self) -> str:
        """
        Base URL for POST /v1/embeddings.

        Priority: EMBEDDING_BASE_URL → OLLAMA_URL/v1 → OPENAI_URL (stripped to /v1).
        """
        if self.embedding_base_url:
            return _openai_v1_base(self.embedding_base_url)
        if self.ollama_url:
            return _openai_v1_base(self.ollama_url)
        if self.openai_url:
            return _openai_v1_base(self.openai_url)
        return _openai_v1_base("http://localhost:11434")

    @property
    def resolved_embedding_api_key(self) -> str:
        if self.embedding_api_key:
            return self.embedding_api_key
        if self.openai_api_key:
            return self.openai_api_key
        return "ollama"

    @property
    def resolved_embedding_model(self) -> str:
        if self.embedding_model:
            return self.embedding_model
        if self.ollama_embedding_model:
            return self.ollama_embedding_model
        return self.openai_embedding_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
