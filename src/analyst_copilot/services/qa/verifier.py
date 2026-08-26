"""Verify that an LLM answer is supported by retrieved evidence.

The rule this module enforces is **evidence first, coordinates second**.

The earlier version asked one question -- "is the page the model named the page
the evidence is on?" -- and rejected everything else. That is the right instinct
and the wrong test, because the page number is the least reliable thing in the
chain. The same document paginates differently depending on whether it is read
as filed HTML, as the PDF the filer published, or as a Word original: measured
across the practice corpus, 15 of 62 documents shift by one or two pages between
two readings of the *same* filing. Rejecting on that difference throws away
answers whose evidence is demonstrably correct.

So verification now works in the other direction. It finds which retrieved page
actually carries the evidence, and cites that page. What the model named is
treated as a hint, not as the answer:

  correct evidence, page matches            -> accept, `exact`
  correct evidence, page off by a little    -> accept, `adjusted` (cite where the evidence is)
  correct evidence, page far away           -> accept only if the evidence is verbatim, `relocated`
  no page carries the evidence              -> reject

Crucially this does not loosen the guard against a confidently wrong answer. An
answer is still only ever attached to a page whose text supports its figures --
the change is that the system now looks for that page instead of insisting the
model guessed its number correctly. Re-anchoring moves a citation; it never
changes an answer, so it cannot turn an abstention into a wrong figure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Set, Tuple

from analyst_copilot.config.settings import get_settings
from analyst_copilot.retrieval.models import ScoredPage
from analyst_copilot.services.qa.models import LLMExtraction

_NUMBER_PATTERN = re.compile(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?")


class LocationMatch(str, Enum):
    """How the citation on an accepted answer relates to what the model said."""

    EXACT = "exact"          # the model's page carries the evidence
    ADJUSTED = "adjusted"    # a neighbouring page does; the citation moved there
    RELOCATED = "relocated"  # a distant page does, and verbatim; the citation moved there
    INFERRED = "inferred"    # the model named no page; the best supported one was used


class SupportLevel(int, Enum):
    """How strongly one page backs an answer. Ordered, so they compare."""

    NONE = 0
    WEAK = 1      # the answer's figures trace to figures on this page
    STRONG = 2    # figures trace, and the quoted snippet substantially overlaps
    VERBATIM = 3  # the quoted snippet appears on this page as written


@dataclass
class PageSupport:
    """One retrieved page scored for how well it backs the answer."""

    hit: ScoredPage
    level: SupportLevel
    numbers_ok: bool
    snippet_ok: bool

    @property
    def page(self) -> int:
        return self.hit.page.citation_page

    @property
    def doc_name(self) -> str:
        return self.hit.page.doc_name


@dataclass
class VerificationResult:
    ok: bool
    reason: str
    page: Optional[int] = None
    evidence_snippet: str = ""
    location_match: Optional[LocationMatch] = None
    cited_page: Optional[int] = None
    support_level: SupportLevel = SupportLevel.NONE
    page_shift: int = 0
    doc_name: Optional[str] = None
    # Set when the answer was found in a different document from the one the
    # model named. Only possible on a folder-scoped question.
    cited_doc_name: Optional[str] = None

    @property
    def relocated(self) -> bool:
        """Whether the citation was moved off the page the model named."""
        return self.location_match in (LocationMatch.ADJUSTED, LocationMatch.RELOCATED)


class AnswerVerifier:
    """Attach an answer to the retrieved page that actually proves it, or reject it."""

    def __init__(self, page_tolerance: Optional[int] = None) -> None:
        settings = get_settings()
        self._tolerance = (
            page_tolerance if page_tolerance is not None else settings.evidence_page_tolerance
        )

    def verify(
        self,
        extraction: LLMExtraction,
        hits: Sequence[ScoredPage],
    ) -> VerificationResult:
        if extraction.not_found:
            return VerificationResult(ok=False, reason="model_abstain")
        if not extraction.answer:
            return VerificationResult(ok=False, reason="empty_answer")
        if not hits:
            return VerificationResult(ok=False, reason="no_retrieval_hits")

        supports = [self._score(hit, extraction) for hit in hits]
        supported = [s for s in supports if s.level is not SupportLevel.NONE]
        cited = extraction.page

        if not supported:
            # No retrieved page backs the answer, so there is nothing here that
            # could prove it. The reason distinguishes the two ways that
            # happens, because they call for different fixes: a page that was
            # never retrieved is a recall problem, while a retrieved page whose
            # figures do not match is a grounding problem.
            retrieved_pages = {s.page for s in supports}
            if cited is not None and cited not in retrieved_pages:
                reason = "page_not_in_retrieval"
            elif cited is not None:
                reason = "number_not_on_page"
            else:
                reason = "evidence_not_on_any_page"
            return VerificationResult(ok=False, reason=reason, cited_page=cited)

        # The `document` field exists to choose between candidates, so with only
        # one document among them there is nothing for it to choose and it is
        # ignored. This is not a nicety: asked for a document it was not shown,
        # a model paraphrases the company's name, and reading that as a
        # contradiction rejected correct answers out of single-document folders.
        #
        # Where several documents *were* retrieved, the name is honoured and a
        # wrong one is still a mismatch -- that is the case the field is for.
        cited_doc = extraction.document
        if len({support.doc_name for support in supports}) < 2:
            cited_doc = None

        best = _best(supported, prefer_page=cited, prefer_doc=cited_doc)
        quote = extraction.evidence_snippet

        if cited is None:
            return self._accept(best, extraction, LocationMatch.INFERRED, "ok_inferred_page", quote)

        on_cited = next(
            (s for s in supported if s.page == cited and _same_doc(s.doc_name, cited_doc)),
            None,
        )
        if on_cited is not None:
            return self._accept(on_cited, extraction, LocationMatch.EXACT, "ok", quote)

        # A page-number tolerance only means anything inside one document. Page
        # 60 of a different filing is not "near" page 61 of this one -- it is a
        # different document, and only verbatim evidence justifies moving there.
        same_document = _same_doc(best.doc_name, cited_doc)
        shift = abs(best.page - cited)
        if same_document and shift <= self._tolerance:
            # A one- or two-page difference is what two paginations of the same
            # document look like. The evidence decides; the citation follows it.
            return self._accept(
                best, extraction, LocationMatch.ADJUSTED, "ok_page_adjusted", quote
            )

        if best.level is SupportLevel.VERBATIM:
            # Far from what the model said, but the quoted evidence is there
            # word for word. Trust the text over the coordinates.
            return self._accept(
                best, extraction, LocationMatch.RELOCATED, "ok_page_relocated", quote
            )

        # Supported only by loose figure matching, nowhere near the citation:
        # that is the shape of a number coinciding, not of evidence.
        return VerificationResult(
            ok=False,
            reason=(
                "evidence_in_a_different_document"
                if not same_document
                else "evidence_too_far_from_citation"
            ),
            cited_page=cited,
            cited_doc_name=cited_doc,
            support_level=best.level,
            page_shift=shift,
        )

    @staticmethod
    def _accept(
        support: PageSupport,
        extraction: LLMExtraction,
        match: LocationMatch,
        reason: str,
        quote: str,
    ) -> VerificationResult:
        # Quote the model's snippet when the page bears it out; otherwise show
        # the head of the page, so the reader is never shown a "quotation" that
        # verification could not find.
        snippet = quote if (quote and support.snippet_ok) else support.hit.page.text[:280]
        cited = extraction.page
        return VerificationResult(
            ok=True,
            reason=reason,
            page=support.page,
            evidence_snippet=snippet,
            location_match=match,
            cited_page=cited,
            support_level=support.level,
            page_shift=abs(support.page - cited) if cited is not None else 0,
            doc_name=support.doc_name,
            cited_doc_name=extraction.document,
        )

    @staticmethod
    def _score(hit: ScoredPage, extraction: LLMExtraction) -> PageSupport:
        page_text = hit.page.text
        numbers_ok = numbers_supported_by_page(extraction.answer, page_text)
        snippet = extraction.evidence_snippet
        verbatim = bool(snippet) and _snippet_verbatim(snippet, page_text)
        overlapping = bool(snippet) and _snippet_overlaps(snippet, page_text)

        if verbatim and numbers_ok:
            level = SupportLevel.VERBATIM
        elif numbers_ok and overlapping:
            level = SupportLevel.STRONG
        elif numbers_ok:
            level = SupportLevel.WEAK
        else:
            # Numbers that do not trace to this page rule it out, whatever the
            # prose says: an answer's figures are the part that must be proven.
            level = SupportLevel.NONE

        return PageSupport(
            hit=hit,
            level=level,
            numbers_ok=numbers_ok,
            snippet_ok=verbatim or overlapping,
        )


def _same_doc(doc_name: str, cited_doc: Optional[str]) -> bool:
    """
    Whether a page belongs to the document the model named.

    True when the model named no document, which is every single-document
    question: there is nothing to disambiguate, so nothing to disagree with.
    Comparison is loose because a model asked to echo `AMD_2022_10K` will
    sometimes return `AMD 2022 10-K`.
    """
    if not cited_doc:
        return True
    return _slug(doc_name) == _slug(cited_doc)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _best(
    supports: List[PageSupport],
    prefer_page: Optional[int],
    prefer_doc: Optional[str] = None,
) -> PageSupport:
    """
    The most convincing supporting page.

    Ties break towards the document the model named, then towards the page it
    named, then towards the page retrieval ranked highest -- in that order,
    because a tie means the evidence cannot choose and the next most
    informative signal should. Document outranks page: being in the right
    filing matters more than being near the right page number in the wrong one.
    """

    def key(support: PageSupport) -> Tuple[int, int, int, int]:
        in_doc = 1 if _same_doc(support.doc_name, prefer_doc) else 0
        near = -abs(support.page - prefer_page) if prefer_page is not None else 0
        return (int(support.level), in_doc, near, -support.hit.rank)

    return max(supports, key=key)


# Filings print one scale ("Dollars in millions"), questions ask for another
# ("answer in USD billions"), so a literal string match rejects correct answers:
# an answer of 8.738 is the page's 8,738 read in billions. Comparing significant
# digits instead is scale-free, and unlike a numeric tolerance it does not widen
# into a band that some number on a dense financial page always falls inside.
MIN_SIGNIFICANT_DIGITS = 3
MIN_SHARED_DIGITS = 2


def significant_digits(token: str) -> str:
    """'8,738' -> '8738'; '8.70' -> '87'; '0.096' -> '96'; '(1,577)' -> '1577'."""
    digits = re.sub(r"[^0-9]", "", token)
    return digits.strip("0") or ("0" if digits else "")


def _digit_forms(text: str) -> Set[str]:
    forms: Set[str] = set()
    for match in _NUMBER_PATTERN.finditer(text.replace("(", " ").replace(")", " ")):
        token = significant_digits(match.group(0))
        if len(token) >= MIN_SHARED_DIGITS:
            forms.add(token)
    return forms


def numbers_supported_by_page(answer: str, page_text: str) -> bool:
    """
    Whether the figures in an answer are traceable to figures on the cited page.

    An answer figure is supported when its significant digits are a prefix of a
    page figure's (or vice versa) -- 8.7 or 8.738 both trace to the page's 8,738,
    regardless of the unit the question asked for. At least one side must carry
    MIN_SIGNIFICANT_DIGITS, so a bare "65" cannot be waved through by whatever
    two-digit figure happens to sit on a page full of numbers.

    An answer with no figures at all is left to the snippet check.
    """
    answer_forms = _digit_forms(answer)
    if not answer_forms:
        return True
    page_forms = _digit_forms(page_text)
    for a in answer_forms:
        for p in page_forms:
            shorter, longer = (a, p) if len(a) <= len(p) else (p, a)
            if len(longer) >= MIN_SIGNIFICANT_DIGITS and longer.startswith(shorter):
                return True
    return False


def _snippet_verbatim(snippet: str, page_text: str) -> bool:
    """
    Whether the quoted snippet appears on the page as written.

    Compared with punctuation and whitespace removed, because the same table
    reaches us as plain text from one parser and as a Markdown table from
    another: `Marketable securities - current` and `| Marketable securities |
    current |` are the same evidence, and only the pipes differ.
    """
    compact_snippet = _compact(snippet)
    if len(compact_snippet) < 24:
        return False
    return compact_snippet[:200] in _compact(page_text)


def _snippet_overlaps(snippet: str, page_text: str) -> bool:
    """Whether enough of the snippet's content words appear on the page."""
    words = [w for w in re.findall(r"[a-z0-9]+", snippet.lower()) if len(w) > 3][:12]
    if not words:
        return False
    lowered = page_text.lower()
    hits = sum(1 for word in words if word in lowered)
    return hits >= max(3, (len(words) + 1) // 2)


def _snippet_supported(snippet: str, page_text: str) -> bool:
    """Whether a snippet is backed by a page at all. Retained for callers and tests."""
    if len(_compact(snippet)) < 12:
        return True
    return _snippet_verbatim(snippet, page_text) or _snippet_overlaps(snippet, page_text)


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
