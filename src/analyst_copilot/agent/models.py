"""Data models for the agent harness.

The harness answers a message in one of three modes, and the mode is part of
the answer rather than an implementation detail:

    CONVERSATIONAL  the message was not a question about a document
    FAST            hybrid retrieval answered it and validation agreed
    DEEP            the fast path failed, so every page was read

Keeping the mode on the answer is what lets the product be honest about how
hard it had to work, and lets the eval attribute a score to a tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from analyst_copilot.parsing.models import SegmentKind


class Intent(str, Enum):
    """What the user's message is asking for."""

    SMALLTALK = "smalltalk"          # greeting, thanks, chit-chat
    CAPABILITY = "capability"        # what can you do, which filings do you have
    DOCUMENT_QUESTION = "document_question"


class AnswerMode(str, Enum):
    CONVERSATIONAL = "conversational"
    FAST = "fast"
    DEEP = "deep"


class Stage(str, Enum):
    """Progress milestones, streamed to the caller as they happen."""

    PLANNING = "planning"
    DECOMPOSING = "decomposing"
    RETRIEVING = "retrieving"
    READING = "reading"
    VALIDATING = "validating"
    ESCALATING = "escalating"
    DEEP_SEARCH = "deep_search"
    SYNTHESIZING = "synthesizing"
    VERIFYING = "verifying"
    DONE = "done"


@dataclass
class StageEvent:
    """One progress milestone. `done`/`total` are set only while fanning out."""

    stage: Stage
    detail: str = ""
    done: Optional[int] = None
    total: Optional[int] = None
    part: Optional[int] = None
    part_total: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {"stage": self.stage.value, "detail": self.detail}
        for key, value in (
            ("done", self.done),
            ("total", self.total),
            ("part", self.part),
            ("part_total", self.part_total),
        ):
            if value is not None:
                payload[key] = value
        return payload


@dataclass
class EvidenceInput:
    """
    One figure a derived answer was computed from, and where it was read.

    This is what makes a computed answer provable. `24.26` appears nowhere in a
    filing, but the two figures it came from do, each on a page whose text can
    be checked. The verifier traces these instead of the result.
    """

    label: str
    value: str
    doc_name: str = ""
    page: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "value": self.value,
            "doc_name": self.doc_name,
            "page": self.page,
        }


@dataclass
class Finding:
    """What one reader agent reports back about its own slice of the document."""

    found: bool
    answer: str = ""
    doc_name: str = ""
    page: Optional[int] = None
    quote: str = ""
    reasoning: str = ""
    why_authoritative: str = ""
    inputs: List[EvidenceInput] = field(default_factory=list)
    computation: str = ""
    confidence: float = 0.0
    # Which shard produced this, for progress reporting and debugging.
    shard: Optional[int] = None
    partial: bool = False

    @property
    def is_derived(self) -> bool:
        """Whether the figure was computed rather than read off a page."""
        return bool(self.computation and self.inputs)

    @property
    def contributes(self) -> bool:
        """
        Whether this finding is worth showing the adjudicator.

        A reader that cannot answer may still hold half of what the answer needs
        -- revenue when the question also wants capex, and the two statements
        sit on pages assigned to different readers. Such a finding reports
        `found: false, partial: true`, and dropping it is how a question
        spanning two statements becomes unanswerable however many agents read
        the document.
        """
        return self.found or self.partial


@dataclass
class Citation:
    """One place an answer can be checked."""

    doc_name: str
    page: int
    label: str
    snippet: str
    segment_kind: SegmentKind = SegmentKind.PAGE
    location_match: str = "exact"
    model_cited_page: Optional[int] = None
    page_shift: int = 0

    @property
    def display_page(self) -> int:
        return self.page + 1


@dataclass
class AnswerPart:
    """
    One sub-question of a multi-part question, answered on its own.

    "What was capex in FY2022 and what drove the change?" is two questions
    wearing one question mark. Retrieval for the pair finds the union of two
    topics and ranks neither well, so each part is retrieved, answered and
    cited separately, then composed. The parts stay visible in the response
    because each one carries its own citation.
    """

    question: str
    answer: str
    found: bool
    mode: AnswerMode = AnswerMode.FAST
    citation: Optional[Citation] = None
    abstention_reason: Optional[str] = None
    inputs: List[EvidenceInput] = field(default_factory=list)
    computation: str = ""
    # Why this part escalated past the fast path, when it did. Kept because it
    # is the diagnostic that says whether the tier boundary is drawn correctly.
    escalation_reason: str = ""
    validation: str = ""
    # The fast path's ranked pages for this part, whichever tier answered it.
    retrieval: Optional[object] = None
    pages_read: int = 0
    shards_run: int = 0


@dataclass
class AgentAnswer:
    """The harness's answer to one user message."""

    question: str
    answer: str
    found: bool
    mode: AnswerMode
    intent: Intent = Intent.DOCUMENT_QUESTION
    doc_name: str = ""
    collection: Optional[str] = None
    searched_documents: int = 0
    citation: Optional[Citation] = None
    citations: List[Citation] = field(default_factory=list)
    parts: List[AnswerPart] = field(default_factory=list)
    abstention_reason: Optional[str] = None
    # Retrieval trace from the fast path, kept even when the deep path answered:
    # it is the record of what the cheap tier looked at before escalating.
    retrieval: Optional[object] = None
    validation: Optional[str] = None
    pages_read: int = 0
    shards_run: int = 0
    inputs: List[EvidenceInput] = field(default_factory=list)
    computation: str = ""
