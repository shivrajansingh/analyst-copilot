"""Verifying an agent's answer, including one it computed.

The existing verifier asks whether every figure in an answer appears on the
cited page. That is the right test for a figure read off a statement, and it is
the wrong test for a figure derived from one — and derived figures are 43 of the
136 practice questions. An operating margin of 24.3% appears nowhere in a
filing; only the operating income and the revenue do. Requiring the *result* on
the page makes every computed answer unprovable by construction, which turns a
correct answer into an abstention and leaves the marks on the table.

So a derived answer is verified one level down, at its inputs:

1. every input figure's significant digits must trace to the page it was read
   from — the same scale-free test used for a direct answer;
2. the arithmetic must be re-run here, deterministically, from the recorded
   expression;
3. the numbers in that expression must be the recorded inputs, so a real set of
   inputs cannot be laundered through an unrelated calculation;
4. the recomputed result must agree with the figure the answer actually states.

All four have to hold. That is a stricter standard than a human analyst applies
to their own spreadsheet, and it has to be: this is the only thing standing
between the product and a confidently wrong number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Sequence

from analyst_copilot.agent.models import EvidenceInput
from analyst_copilot.agent.tools.calculator import (
    CalculationError,
    evaluate,
    format_result,
    normalize_expression,
)
from analyst_copilot.services.qa.verifier import (
    MIN_SIGNIFICANT_DIGITS,
    numbers_supported_by_page,
    significant_digits,
)

# Where the text of a page comes from. A callable rather than a corpus so the
# checks below can be unit-tested against strings.
PageTextLookup = Callable[[str, int], Optional[str]]

# One number is one match, however long. The earlier pattern tried
# `\d{1,3}(?:,\d{3})*` first, which on a comma-free integer matched only the
# first three digits and then restarted: `177866` came back as `177` and `866`.
# That tore every figure a filing prints in millions into fragments, and
# `_unexplained_literals` then rejected the tail as a number nobody had cited --
# refusing correct arithmetic. Leading `\d+` is greedy, so `1,577`, `177866`
# and `9,497,578` each match whole.
_NUMBER = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")

# A stated answer is a rounding of the computed value, not a re-derivation of
# it, so agreement is relative and generous enough to allow "15%" for 14.86%
# while still rejecting a different figure.
DEFAULT_REL_TOL = 0.02
# Filings print one scale and questions ask for another.
_SCALES = (1.0, 1e3, 1e-3, 1e2, 1e-2, 1e6, 1e-6, 1e9, 1e-9)


class Support(str, Enum):
    """How an accepted answer is proven."""

    DIRECT = "direct"      # its figures are printed on the cited page
    DERIVED = "derived"    # computed from figures printed on cited pages
    QUOTED = "quoted"      # no figures at all; the quoted text carries it


@dataclass
class DerivationCheck:
    """Whether a computed answer's arithmetic holds up."""

    ok: bool
    reason: str = ""
    computed: Optional[float] = None
    traced_inputs: int = 0
    total_inputs: int = 0
    untraced: List[str] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return self.total_inputs > 0


@dataclass
class DeepVerification:
    """The verdict on a deep-path answer."""

    ok: bool
    reason: str
    support: Optional[Support] = None
    doc_name: str = ""
    page: Optional[int] = None
    snippet: str = ""
    location_match: str = "exact"
    page_shift: int = 0
    derivation: Optional[DerivationCheck] = None


# --------------------------------------------------------------------------- #
# numeric agreement
# --------------------------------------------------------------------------- #
def figures_in(text: str) -> List[float]:
    values: List[float] = []
    for match in _NUMBER.finditer(text or ""):
        try:
            values.append(abs(float(match.group(0).replace(",", ""))))
        except ValueError:
            continue
    return values


def figures_agree(stated: float, computed: float, rel_tol: float = DEFAULT_REL_TOL) -> bool:
    """
    Whether a stated figure is the computed one, allowing rounding and rescaling.

    Rescaling matters because the answer may be given in billions while the
    computation ran in millions; rounding matters because "15%" is an honest
    statement of 14.857975 and rejecting it would abstain on a correct answer.
    """
    for scale in _SCALES:
        target = computed * scale
        if target == 0:
            if stated == 0:
                return True
            continue
        if abs(stated - target) <= rel_tol * abs(target):
            return True
    return computed == 0.0 and stated == 0.0


def answer_states(answer: str, computed: float, rel_tol: float = DEFAULT_REL_TOL) -> bool:
    """Whether any figure in the answer text is the computed value."""
    return any(figures_agree(value, computed, rel_tol) for value in figures_in(answer))


# --------------------------------------------------------------------------- #
# derivation
# --------------------------------------------------------------------------- #
def check_derivation(
    answer: str,
    inputs: Sequence[EvidenceInput],
    computation: str,
    page_text: PageTextLookup,
    rel_tol: float = DEFAULT_REL_TOL,
) -> DerivationCheck:
    """Re-run a computed answer from its recorded inputs, or say why it fails."""
    if not inputs or not computation.strip():
        return DerivationCheck(ok=False, reason="no recorded derivation", total_inputs=0)

    untraced: List[str] = []
    for item in inputs:
        if item.page is None:
            untraced.append(f"{item.label} (no page recorded)")
            continue
        text = page_text(item.doc_name, item.page)
        if not text:
            untraced.append(f"{item.label} (page {item.page + 1} unreadable)")
            continue
        if not numbers_supported_by_page(item.value, text):
            untraced.append(f"{item.label}={item.value} not on page {item.page + 1}")

    traced = len(inputs) - len(untraced)
    if untraced:
        return DerivationCheck(
            ok=False,
            reason="input figures do not appear on the pages they were cited to: "
            + "; ".join(untraced[:4]),
            traced_inputs=traced,
            total_inputs=len(inputs),
            untraced=untraced,
        )

    try:
        computed = evaluate(computation)
    except CalculationError as exc:
        return DerivationCheck(
            ok=False,
            reason=f"the recorded computation is not valid arithmetic: {exc}",
            traced_inputs=traced,
            total_inputs=len(inputs),
        )

    unexplained = _unexplained_literals(computation, inputs)
    if unexplained:
        return DerivationCheck(
            ok=False,
            reason=(
                "the computation uses figures that are not among its recorded "
                f"inputs: {', '.join(unexplained[:4])}"
            ),
            computed=computed,
            traced_inputs=traced,
            total_inputs=len(inputs),
        )

    if not answer_states(answer, computed, rel_tol):
        return DerivationCheck(
            ok=False,
            reason=(
                f"the answer does not state the computed result "
                f"({format_result(computed)})"
            ),
            computed=computed,
            traced_inputs=traced,
            total_inputs=len(inputs),
        )

    return DerivationCheck(
        ok=True,
        reason=f"{normalize_expression(computation)} = {format_result(computed)}",
        computed=computed,
        traced_inputs=traced,
        total_inputs=len(inputs),
    )


# Scale and rounding constants a computation may legitimately contain without
# being an input read off a page: converting to a percentage, to millions, to
# billions, halving, or rounding to a number of places.
_STRUCTURAL_LITERALS = {
    "1", "2", "3", "4", "10", "100", "1000", "10000", "100000",
    "1000000", "1000000000", "12", "365", "0", "5",
}


def _unexplained_literals(computation: str, inputs: Sequence[EvidenceInput]) -> List[str]:
    """
    Numbers in the expression that are neither an input nor a scale factor.

    Without this, a model could record two real figures as inputs and then
    compute something else entirely — the inputs would trace, the arithmetic
    would evaluate, and the answer would be unproven.
    """
    known = {significant_digits(item.value) for item in inputs}
    known.discard("")
    unexplained: List[str] = []

    for match in _NUMBER.finditer(normalize_expression(computation)):
        token = match.group(0)
        plain = token.lstrip("-")
        if plain in _STRUCTURAL_LITERALS:
            continue
        digits = significant_digits(token)
        if not digits or len(digits) < MIN_SIGNIFICANT_DIGITS:
            # Two significant digits is a scale, a period count or a rounding
            # precision far more often than it is a line item.
            continue
        if any(
            digits == candidate
            or (len(candidate) >= MIN_SIGNIFICANT_DIGITS and candidate.startswith(digits))
            or (len(digits) >= MIN_SIGNIFICANT_DIGITS and digits.startswith(candidate))
            for candidate in known
        ):
            continue
        unexplained.append(token)

    return unexplained


# --------------------------------------------------------------------------- #
# the deep-path verdict
# --------------------------------------------------------------------------- #
def verify_agent_answer(
    answer: str,
    doc_name: str,
    page: Optional[int],
    quote: str,
    inputs: Sequence[EvidenceInput],
    computation: str,
    page_text: PageTextLookup,
    locate_quote: Optional[Callable[[str], Optional[tuple]]] = None,
    rel_tol: float = DEFAULT_REL_TOL,
) -> DeepVerification:
    """
    Accept an agent's answer only if the document proves it.

    Tried in order: the figures are on the cited page; the answer is a valid
    derivation from traced inputs; the answer carries no figures and its quote
    is on the page. A citation may be moved onto the page bearing the quote,
    which changes where an answer is said to live and never what it says.
    """
    if not answer.strip():
        return DeepVerification(ok=False, reason="empty_answer")
    if page is None:
        page, doc_name = _relocate(quote, doc_name, locate_quote)
        if page is None:
            return DeepVerification(ok=False, reason="no_page_cited")

    text = page_text(doc_name, page)
    location_match = "exact"
    shift = 0

    if not text and locate_quote is not None:
        moved_page, moved_doc = _relocate(quote, doc_name, locate_quote)
        if moved_page is None:
            return DeepVerification(
                ok=False, reason="cited_page_unreadable", doc_name=doc_name, page=page
            )
        shift = abs(moved_page - page) if moved_doc == doc_name else 0
        page, doc_name, location_match = moved_page, moved_doc, "relocated"
        text = page_text(doc_name, page)

    if not text:
        return DeepVerification(
            ok=False, reason="cited_page_unreadable", doc_name=doc_name, page=page
        )

    derivation = check_derivation(answer, inputs, computation, page_text, rel_tol)
    figures = figures_in(answer)

    # A derived answer is checked against its inputs' pages, so it is verified
    # even when the cited page carries none of its figures -- which is the
    # normal case for a computed metric.
    if derivation.ok:
        return DeepVerification(
            ok=True,
            reason="ok_derived",
            support=Support.DERIVED,
            doc_name=doc_name,
            page=page,
            snippet=_snippet(quote, text),
            location_match=location_match,
            page_shift=shift,
            derivation=derivation,
        )

    if numbers_supported_by_page(answer, text):
        return DeepVerification(
            ok=True,
            reason="ok" if figures else "ok_no_figures",
            support=Support.DIRECT if figures else Support.QUOTED,
            doc_name=doc_name,
            page=page,
            snippet=_snippet(quote, text),
            location_match=location_match,
            page_shift=shift,
            derivation=derivation if derivation.applicable else None,
        )

    # The figures are not on this page. If the quote is verbatim elsewhere, the
    # citation was misplaced rather than the answer being wrong.
    moved_page, moved_doc = _relocate(quote, doc_name, locate_quote)
    if moved_page is not None and (moved_page != page or moved_doc != doc_name):
        moved_text = page_text(moved_doc, moved_page)
        if moved_text and numbers_supported_by_page(answer, moved_text):
            return DeepVerification(
                ok=True,
                reason="ok_page_relocated",
                support=Support.DIRECT,
                doc_name=moved_doc,
                page=moved_page,
                snippet=_snippet(quote, moved_text),
                location_match="relocated",
                page_shift=abs(moved_page - page) if moved_doc == doc_name else 0,
            )

    if derivation.applicable:
        return DeepVerification(
            ok=False,
            reason=f"derivation_failed: {derivation.reason}",
            doc_name=doc_name,
            page=page,
            derivation=derivation,
        )
    return DeepVerification(
        ok=False,
        reason="number_not_on_page",
        doc_name=doc_name,
        page=page,
    )


def _relocate(
    quote: str,
    doc_name: str,
    locate_quote: Optional[Callable[[str], Optional[tuple]]],
) -> tuple:
    if not quote or locate_quote is None:
        return None, doc_name
    found = locate_quote(quote)
    if not found:
        return None, doc_name
    return found[1], found[0]


def _snippet(quote: str, page_text_value: str, limit: int = 320) -> str:
    """
    The quote when the page bears it out, else the head of the page.

    A reader is never shown a "quotation" that verification could not find.
    """
    compact_quote = re.sub(r"[^a-z0-9]", "", quote.lower())
    if len(compact_quote) >= 24:
        compact_page = re.sub(r"[^a-z0-9]", "", page_text_value.lower())
        if compact_quote[:200] in compact_page:
            return quote.strip()
    words = [word for word in re.findall(r"[a-z0-9]+", quote.lower()) if len(word) > 3][:12]
    if words:
        lowered = page_text_value.lower()
        hits = sum(1 for word in words if word in lowered)
        if hits >= max(3, (len(words) + 1) // 2):
            return quote.strip()
    return page_text_value[:limit].strip()
