"""Answering from the thread, and the four ways it must refuse to.

No model calls. `RecallChat` returns a fixed JSON reply, so the guards -- the
part that decides whether an unproved figure reaches an analyst -- are tested
exactly.
"""

from __future__ import annotations

import json

import pytest

from analyst_copilot.agent.models import AnswerMode
from analyst_copilot.agent.planner import Plan, PlanKind
from analyst_copilot.agent.recall import (
    HistoryAnswerer,
    HistoryTurn,
    RecallPayload,
    build_prompt,
    turns_from,
)
from analyst_copilot.llm.base import ChatClient

ANSWERED = [
    {"role": "user", "content": "What was 3M's FY2018 capital expenditure?"},
    {
        "role": "assistant",
        "content": "3M's FY2018 capital expenditure was $1,577 million.",
        "found": True,
        "page": 59,
        "doc_name": "3M_2018_10K",
    },
]

DECLINED = [
    {"role": "user", "content": "What was FY2018 headcount?"},
    {
        "role": "assistant",
        "content": "I could not find that in this filing.",
        "found": False,
        "page": None,
    },
]


class RecallChat(ChatClient):
    """Returns one fixed recollection, and records what it was asked."""

    def __init__(self, payload, raw=None):
        self.payload = payload
        self.raw = raw
        self.prompts = []

    @property
    def model_name(self) -> str:
        return "recall"

    def complete(self, messages, temperature=0.0, max_tokens=700):
        self.prompts.append(messages[-1]["content"])
        return self.raw if self.raw is not None else json.dumps(self.payload)


class BrokenChat(ChatClient):
    @property
    def model_name(self) -> str:
        return "broken"

    def complete(self, messages, temperature=0.0, max_tokens=700):
        raise RuntimeError("provider down")


def _recall(payload, history=None, message="what was that capex figure again?"):
    chat = RecallChat(payload)
    return HistoryAnswerer(chat).recall(message, history if history is not None else ANSWERED), chat


# --- reading stored turns --------------------------------------------------- #
def test_only_a_proved_assistant_answer_is_quotable():
    turns = turns_from(ANSWERED + DECLINED)
    assert [turn.citable for turn in turns] == [False, True, False, False]


def test_a_turn_with_no_page_is_not_quotable():
    assert not HistoryTurn("assistant", "It was $1,577m.", found=True, page=None).citable


def test_a_user_turn_is_never_quotable():
    assert not HistoryTurn("user", "It was $1,577m.", found=True, page=59).citable


def test_empty_turns_are_dropped():
    assert turns_from([{"role": "user", "content": "   "}, *ANSWERED]) == turns_from(ANSWERED)


# --- restating -------------------------------------------------------------- #
def test_a_repeat_question_is_restated_with_the_original_citation():
    recollection, _ = _recall(
        {"found": True, "source": 1, "answer": "$1,577 million.", "reason": "asked again"}
    )
    assert recollection.found
    assert recollection.answer == "$1,577 million."
    assert recollection.source is not None
    assert recollection.source.page == 59
    assert recollection.source.doc_name == "3M_2018_10K"


def test_the_prompt_numbers_only_the_quotable_answers():
    _, chat = _recall({"found": False, "source": None}, history=ANSWERED + DECLINED)
    prompt = chat.prompts[0]
    assert "[answer 1]" in prompt
    assert "[answer 2]" not in prompt  # the decline is shown, but not offered
    assert "I could not find that in this filing." in prompt


# --- the refusals ----------------------------------------------------------- #
def test_a_thread_with_no_proved_answer_never_reaches_the_model():
    chat = RecallChat({"found": True, "source": 1, "answer": "made up"})
    recollection = HistoryAnswerer(chat).recall("what was that again?", DECLINED)
    assert not recollection.found
    assert chat.prompts == []  # not worth a call


def test_an_empty_thread_declines():
    recollection = HistoryAnswerer(RecallChat({})).recall("what was that again?", [])
    assert not recollection.found


def test_a_source_out_of_range_is_refused():
    recollection, _ = _recall({"found": True, "source": 4, "answer": "$1,577 million."})
    assert not recollection.found
    assert recollection.error == "source out of range"


def test_a_yes_with_no_source_is_refused():
    recollection, _ = _recall({"found": True, "source": None, "answer": "$1,577 million."})
    assert not recollection.found


def test_a_yes_with_no_answer_text_is_refused():
    recollection, _ = _recall({"found": True, "source": 1, "answer": "   "})
    assert not recollection.found


def test_a_plain_no_falls_through():
    recollection, _ = _recall(
        {"found": False, "source": None, "reason": "the thread never covered 2017"}
    )
    assert not recollection.found
    assert "2017" in recollection.reason


def test_unparseable_output_falls_through():
    chat = RecallChat({}, raw="I think we said $1,577 million earlier?")
    recollection = HistoryAnswerer(chat).recall("what was that again?", ANSWERED)
    assert not recollection.found
    assert recollection.error == "no JSON object"


def test_an_off_spec_source_type_is_refused():
    recollection, _ = _recall({"found": True, "source": "the first one", "answer": "x"})
    assert not recollection.found
    assert "source" in (recollection.error or "")


def test_a_dead_provider_falls_through():
    recollection = HistoryAnswerer(BrokenChat()).recall("what was that again?", ANSWERED)
    assert not recollection.found
    assert "provider down" in recollection.reason


def test_no_model_at_all_falls_through():
    assert not HistoryAnswerer(None).recall("what was that again?", ANSWERED).found


# --- the payload contract --------------------------------------------------- #
def test_extra_keys_are_ignored():
    payload = RecallPayload.model_validate({"found": True, "source": 1, "tokens": 9})
    assert payload.source == 1


def test_a_missing_found_defaults_to_no():
    assert RecallPayload.model_validate({}).found is False
