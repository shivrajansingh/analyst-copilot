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
    # Measured on all 136 practice questions (gold-page recall@5): BM25 16%,
    # vector 58%, shipped RRF+weighted hybrid 36%, weighted-only 59%. RRF's
    # rank compression let consensus outvote confident retrievers; end-to-end
    # rubric went +1 -> +7 when it was disabled. Re-measure after chunking.
    hybrid_bm25_weight: float = 0.1
    hybrid_vector_weight: float = 0.9
    hybrid_candidate_pool: int = 80
    hybrid_rrf_k: int = 60
    hybrid_rrf_weight: float = 0.0
    hybrid_weighted_weight: float = 1.0
    hybrid_statement_boost: float = 1.25

    # QA / abstention
    qa_top_k: int = 5
    qa_max_evidence_chars: int = 2200
    qa_temperature: float = 0.0
    qa_max_tokens: int = 4096
    not_found_message: str = "not found in this filing"

    # Agent harness. The fast path above answers from the five pages retrieval
    # chose; measured on the practice key it contains the gold page 58% of the
    # time, so the rest is unanswerable without reading more of the document.
    # The deep path removes that ceiling by reading every page -- expensive, so
    # it runs only when the fast path could not produce an answer that survived
    # validation.
    agent_enabled: bool = True
    # Second opinion on a fast-path answer, from a reader that did not write it.
    agent_validate_answers: bool = True
    agent_deep_search: bool = True
    # Pages one reader agent is responsible for. Every page belongs to exactly
    # one reader, so the readers together have read the whole document.
    agent_pages_per_shard: int = 10
    # Readers in flight at once. The bound is the provider's rate limit, not
    # local CPU: readers spend all their time waiting on network calls.
    agent_max_concurrency: int = 8
    # Hard cap on readers for one question. 0 means no cap -- a 306-segment
    # filing runs 31 readers. Set it only to bound cost, and note that a cap
    # means the document was not fully read.
    agent_max_shards: int = 0
    agent_reader_max_iterations: int = 8
    agent_synthesis_max_iterations: int = 10
    agent_max_tokens: int = 4096
    # Split a question that asks several things into parts, each researched and
    # cited on its own.
    agent_decompose: bool = True
    agent_max_parts: int = 4
    # Prior turns shown to the harness, so "and the year before?" resolves.
    agent_history_turns: int = 6

    # How far a citation may be moved to land on the page that actually carries
    # the evidence. Two readings of the same document -- filed HTML vs the
    # filer's own PDF -- disagree by one or two pages on 15 of the 62 documents
    # in the practice corpus, so a shift of that size is a pagination artifact
    # rather than a wrong answer. Beyond it, the evidence must be verbatim.
    evidence_page_tolerance: int = 2

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
