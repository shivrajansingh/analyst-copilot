"""Question answering over a single indexed filing."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from analyst_copilot.config.settings import get_settings
from analyst_copilot.llm import ChatClient, get_chat_client
from analyst_copilot.retrieval.hybrid.searcher import HybridSearcher
from analyst_copilot.services.indexing.hybrid_indexer import HybridFilingIndexer
from analyst_copilot.services.indexing.models import FilingIndices
from analyst_copilot.services.qa.models import NOT_FOUND_MESSAGE, QAAnswer
from analyst_copilot.services.qa.parser import parse_llm_extraction
from analyst_copilot.services.qa.prompts import SYSTEM_PROMPT, build_user_prompt
from analyst_copilot.services.qa.verifier import AnswerVerifier

# PDF first: its page boundaries are stored, not inferred, so a citation into it
# is the one an analyst can check against the document the company published.
PREFERRED_SUFFIXES = (".pdf", ".htm", ".html", ".docx", ".xlsx", ".csv", ".md", ".txt")


def find_source_document(doc_name: str) -> Path:
    """
    Locate a document by name, whatever format it was added in.

    A filing may have arrived as HTML, as the filer's own PDF, or as a Word
    original, and the caller knows only the name it was stored under. Extensions
    are tried in the order the parsers handle best, so a document present in two
    formats is read from the one whose page boundaries are explicit.
    """
    settings = get_settings()
    for suffix in PREFERRED_SUFFIXES:
        candidate = settings.filings_dir / f"{doc_name}{suffix}"
        if candidate.is_file():
            return candidate
    matches = sorted(settings.filings_dir.glob(f"{doc_name}.*"))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"No source document named {doc_name!r} under {settings.filings_dir}."
    )


class QuestionAnsweringService:
    """Retrieve evidence, ask the LLM, then verify or abstain."""

    def __init__(
        self,
        indexer: Optional[HybridFilingIndexer] = None,
        searcher: Optional[HybridSearcher] = None,
        chat_client: Optional[ChatClient] = None,
        verifier: Optional[AnswerVerifier] = None,
    ) -> None:
        settings = get_settings()
        self._indexer = indexer or HybridFilingIndexer()
        self._searcher = searcher or HybridSearcher()
        self._chat_client = chat_client
        self._verifier = verifier or AnswerVerifier()
        self._top_k = settings.qa_top_k
        self._max_evidence_chars = settings.qa_max_evidence_chars
        self._temperature = settings.qa_temperature
        self._max_tokens = settings.qa_max_tokens
        self._not_found = settings.not_found_message

    def _chat(self) -> ChatClient:
        if self._chat_client is None:
            self._chat_client = get_chat_client()
        return self._chat_client

    def answer(
        self,
        question: str,
        doc_name: str,
        filing_path: Optional[Union[Path, str]] = None,
    ) -> QAAnswer:
        indices = self._load_or_build(doc_name, filing_path)
        search = self._searcher.search(
            indices.bm25_index,
            indices.vector_index,
            question,
            top_k=self._top_k,
        )

        if not search.hits:
            return self._abstain(question, doc_name, "no_retrieval_hits", search)

        user_prompt = build_user_prompt(question, search.hits, self._max_evidence_chars)
        try:
            raw = self._chat().complete(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except ValueError as exc:
            return self._abstain(question, doc_name, f"llm_error:{exc}", search)
        extraction = parse_llm_extraction(raw)
        verified = self._verifier.verify(extraction, search.hits)

        if not verified.ok:
            return self._abstain(question, doc_name, verified.reason, search, extraction)

        cited_hit = next(
            (hit for hit in search.hits if hit.page.citation_page == verified.page),
            None,
        )
        return QAAnswer(
            question=question,
            doc_name=doc_name,
            answer=extraction.answer,
            found=True,
            page=verified.page,
            evidence_snippet=verified.evidence_snippet,
            retrieval=search,
            llm_extraction=extraction,
            location_match=verified.location_match.value if verified.location_match else None,
            cited_page=verified.cited_page,
            page_shift=verified.page_shift,
            location_label=cited_hit.page.citation_label if cited_hit else None,
            segment_kind=cited_hit.page.segment_kind if cited_hit else None,
        )

    def _load_or_build(
        self,
        doc_name: str,
        filing_path: Optional[Union[Path, str]],
    ) -> FilingIndices:
        if self._indexer.indices_exist(doc_name):
            return self._indexer.load_indices(doc_name)
        if filing_path is None:
            filing_path = find_source_document(doc_name)
        return self._indexer.index_filing(filing_path, doc_name=doc_name, save=True)

    def _abstain(
        self,
        question: str,
        doc_name: str,
        reason: str,
        search,
        extraction=None,
    ) -> QAAnswer:
        return QAAnswer(
            question=question,
            doc_name=doc_name,
            answer=self._not_found,
            found=False,
            retrieval=search,
            abstention_reason=reason,
            llm_extraction=extraction,
        )
