"""The checker that answers before it judges.

The failure these cover is measured, not hypothetical: asked "is this answer
right?", a checker sharing the writer's model approved 9 of 11 wrong answers on
the practice key -- in one case re-deriving the writer's own wrong formula and
confirming its arithmetic. A checker that has to answer first has nothing to
agree with.
"""

from __future__ import annotations

import json

import pytest

from analyst_copilot.agent.models import EvidenceInput
from analyst_copilot.agent.validator import AnswerValidator, Verdict
from analyst_copilot.llm.base import ChatTurn, ToolCall

DOC = "3M_2018_10K"
PAGE_TEXT = "Purchases of property, plant and equipment (PP&E) | (1,577) |"


class _Page:
    def __init__(self, text=PAGE_TEXT, index=59, doc_name=DOC):
        self.doc_name = doc_name
        self.page_index = index
        self.label = f"page {index + 1}"
        self.text = text
        self.segment_kind = "page"


class _Corpus:
    """Just enough corpus for the checker to build its toolset and read a page."""

    def __init__(self, pages=None):
        self._pages = pages or {(DOC, 59): _Page()}

    def page(self, doc_name, page_index):
        try:
            return self._pages[(doc_name, page_index)]
        except KeyError as exc:
            raise LookupError(f"no page {doc_name}#{page_index}") from exc

    def available_documents(self):
        return [DOC]

    def doc_names(self):
        return [DOC]

    def all_pages(self):
        return []


class _Chat:
    """Replays scripted turns; records what it was shown."""

    def __init__(self, turns, prose=""):
        self._turns = list(turns)
        self._prose = prose
        self.prompts = []

    @property
    def model_name(self):
        return "fake-checker"

    def complete_with_tools(self, messages, tools, **_kw):
        self.prompts.append(messages[-1]["content"])
        if not self._turns:
            raise AssertionError("the checker asked for more turns than were scripted")
        return self._turns.pop(0)

    def complete(self, messages, **_kw):
        self.prompts.append(messages[-1]["content"])
        return self._prose


def _reports(tool: str, **arguments) -> ChatTurn:
    call = ToolCall(id="1", name=tool, arguments=json.dumps(arguments))
    return ChatTurn(content="", tool_calls=[call], message={"role": "assistant"})


def _stalls() -> ChatTurn:
    """No text and no tool call -- the shape longcat returned 9 times in 62."""
    return ChatTurn(content="", tool_calls=[], finish_reason="stop", message={})


def _check(chat, answer, inputs=(), corpus=None, **kwargs):
    validator = AnswerValidator(chat, blind=True, **kwargs)
    return validator.check(
        question="What is the FY2018 capital expenditure for 3M?",
        answer=answer,
        doc_name=DOC,
        page=59,
        corpus=corpus or _Corpus(),
        inputs=inputs,
    )


def test_agreeing_figures_are_served():
    chat = _Chat([_reports("report_reading", answered=True, answer="1,577", reason="cash flow statement")])
    assert _check(chat, "$1,577 million").verdict is Verdict.CORRECT


def test_a_different_figure_is_caught_without_asking_a_model():
    """
    The comparison that matters happens in code. No model judgement, so no
    room to be agreeable -- and this is the case the old checker waved through.
    """
    chat = _Chat([_reports("report_reading", answered=True, answer="1,577", reason="")])
    result = _check(chat, "$2,100 million")
    assert result.verdict is Verdict.INCORRECT
    assert result.corrected_answer == "1,577"


def test_rescaled_figures_still_agree():
    """`8.7 billion` and `8,738` under 'Dollars in millions' are one reading."""
    chat = _Chat([_reports("report_reading", answered=True, answer="8,738", reason="")])
    assert _check(chat, "$8.7 billion").verdict is Verdict.CORRECT


def test_a_page_that_does_not_answer_is_insufficient():
    chat = _Chat([_reports("report_reading", answered=False, answer="", reason="this page is the auditor's report")])
    result = _check(chat, "$1,577 million")
    assert result.verdict is Verdict.INSUFFICIENT
    assert "auditor" in result.reason


def test_the_proposed_answer_is_never_shown_to_the_blind_reader():
    """If the answer leaks into the prompt, this is a review again, not a check."""
    chat = _Chat([_reports("report_reading", answered=True, answer="1,577", reason="")])
    _check(chat, "$9,999 million is the capital expenditure")
    assert not any("9,999" in prompt for prompt in chat.prompts)


def test_prose_answers_fall_back_to_a_comparison_call():
    chat = _Chat(
        [_reports("report_reading", answered=True, answer="It rose, driven by gaming", reason="")],
        prose=json.dumps({"same": False, "reason": "different driver named"}),
    )
    result = _check(chat, "It rose, driven by appliances")
    assert result.verdict is Verdict.INCORRECT
    assert "different driver" in result.reason


def test_a_stalled_checker_is_retried_rather_than_believed():
    """
    A checker that returns nothing serves the answer unchecked. That happened on
    9 of 62 measured questions, two of which were wrong, so it is retried.
    """
    chat = _Chat([_stalls(), _reports("report_reading", answered=True, answer="1,577", reason="")])
    assert _check(chat, "$1,577 million", retries=1).verdict is Verdict.CORRECT


def test_a_checker_that_never_reports_does_not_pass_as_a_verdict():
    chat = _Chat([_stalls(), _stalls(), _stalls(), _stalls()])
    assert _check(chat, "$1,577 million", retries=1).verdict is Verdict.UNCHECKED


def test_the_pages_a_derivation_came_from_are_shown_too():
    """
    A ratio spans two statements. A reader given only the cited page cannot
    re-derive it, and would report `answered: false` on a sound answer.
    """
    corpus = _Corpus(
        {
            (DOC, 59): _Page(),
            (DOC, 48): _Page(text="Net sales | 32,765 |", index=48),
        }
    )
    chat = _Chat([_reports("report_reading", answered=True, answer="4.8%", reason="")])
    _check(
        chat,
        "4.8%",
        inputs=[
            EvidenceInput("FY2018 capex", "1,577", DOC, 59),
            EvidenceInput("FY2018 net sales", "32,765", DOC, 48),
        ],
        corpus=corpus,
    )
    assert any("32,765" in prompt for prompt in chat.prompts)


@pytest.mark.parametrize(
    "computation, inputs",
    [
        ("(177,866 - 135,987) / 135,987 * 100", ["177,866", "135,987"]),
        ("9,497,578 / 4,713,500", ["9,497,578", "4,713,500"]),
        ("1,142,464 / 464,798", ["1,142,464", "464,798"]),
    ],
)
def test_long_figures_are_not_torn_into_unexplained_fragments(computation, inputs):
    """
    `177866` used to match as `177` then `866`, so the tail read as a figure
    nobody had cited and correct arithmetic was rejected. Every input a filing
    prints in millions is four digits or more, so this hit all of them.
    """
    from analyst_copilot.agent.verification import _unexplained_literals

    recorded = [EvidenceInput(f"input {i}", value) for i, value in enumerate(inputs)]
    assert _unexplained_literals(computation, recorded) == []
