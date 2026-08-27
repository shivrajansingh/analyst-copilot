"""The agent loop and the reader, driven by a scripted tool-calling client.

`ScriptedChat` replays a fixed list of turns, so the loop's behaviour is exactly
reproducible: what it does with a terminal call, with malformed arguments, with
a model that stalls, and with one that never reports at all.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from analyst_copilot.agent.corpus import DocumentCorpus
from analyst_copilot.agent.reader import ShardReader
from analyst_copilot.agent.runtime import AgentRuntime
from analyst_copilot.agent.tools import (
    REPORT_FINDING,
    CalculateTool,
    DocumentToolset,
    ReportFindingTool,
    ToolRegistry,
    document_tools,
)
from analyst_copilot.llm.base import ChatClient, ChatTurn, ToolCall, ToolsUnsupported
from analyst_copilot.parsing.markdown_store import MarkdownPageStore
from analyst_copilot.parsing.models import FilingDocument, Page

DOC = "TESTCO_2022_10K"


def call(name: str, arguments: str, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def turn(content: str = "", calls: Optional[List[ToolCall]] = None) -> ChatTurn:
    message: Dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in calls
        ]
    return ChatTurn(
        content=content,
        tool_calls=calls or [],
        finish_reason="tool_calls" if calls else "stop",
        message=message,
    )


class ScriptedChat(ChatClient):
    """Replays scripted turns and records the transcripts it was sent."""

    def __init__(self, turns: List[ChatTurn]) -> None:
        self._turns = list(turns)
        self.seen: List[List[dict]] = []

    @property
    def model_name(self) -> str:
        return "scripted"

    @property
    def supports_tools(self) -> bool:
        return True

    def complete(self, messages, temperature=0.0, max_tokens=800):
        return ""

    def complete_with_tools(
        self, messages, tools, temperature=0.0, max_tokens=4096, tool_choice="auto"
    ):
        self.seen.append([dict(message) for message in messages])
        if not self._turns:
            return turn("nothing left to say")
        return self._turns.pop(0)


class BrokenChat(ChatClient):
    @property
    def model_name(self) -> str:
        return "broken"

    def complete(self, messages, temperature=0.0, max_tokens=800):
        raise RuntimeError("provider down")

    def complete_with_tools(self, *args, **kwargs):
        raise RuntimeError("provider down")


@pytest.fixture
def corpus(tmp_path):
    pages = [
        Page(doc_name=DOC, page_index=0, text="# Cover\n\nTESTCO 2022"),
        Page(
            doc_name=DOC,
            page_index=1,
            text=(
                "# Consolidated Statement of Cash Flows\n\n"
                "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |"
            ),
        ),
        Page(doc_name=DOC, page_index=2, text="# Notes\n\nNothing relevant here."),
    ]
    store = MarkdownPageStore(base_dir=tmp_path / "md")
    store.save(FilingDocument(doc_name=DOC, source_path="", pages=pages))
    return DocumentCorpus(store=store, doc_names=[DOC])


def _registry(corpus):
    toolset = DocumentToolset(corpus)
    return ToolRegistry(document_tools(toolset) + [CalculateTool(), ReportFindingTool()])


# --- the loop -------------------------------------------------------------- #
def test_a_terminal_call_ends_the_run_and_returns_its_arguments(corpus):
    chat = ScriptedChat([turn(calls=[call(REPORT_FINDING, '{"found": true, "answer": "x"}')])])
    run = AgentRuntime(chat).run("sys", "user", _registry(corpus), terminal_tools=(REPORT_FINDING,))
    assert run.reported
    assert run.report == {"found": True, "answer": "x"}
    assert run.iterations == 1


def test_tools_are_executed_and_their_output_reaches_the_next_turn(corpus):
    chat = ScriptedChat(
        [
            turn(calls=[call("read_page", '{"page": 2}')]),
            turn(calls=[call(REPORT_FINDING, '{"found": true, "answer": "$1,577 million"}')]),
        ]
    )
    run = AgentRuntime(chat).run("sys", "user", _registry(corpus), terminal_tools=(REPORT_FINDING,))
    assert run.reported
    assert run.tool_calls == 2
    second_transcript = chat.seen[1]
    tool_messages = [m for m in second_transcript if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "Purchases of property, plant and equipment" in tool_messages[0]["content"]


def test_other_calls_in_the_same_turn_are_still_answered(corpus):
    """A provider that batches a read alongside the report needs both replied to."""
    chat = ScriptedChat(
        [
            turn(
                calls=[
                    call("read_page", '{"page": 2}', "a"),
                    call(REPORT_FINDING, '{"found": true, "answer": "x"}', "b"),
                ]
            )
        ]
    )
    run = AgentRuntime(chat).run("sys", "user", _registry(corpus), terminal_tools=(REPORT_FINDING,))
    assert run.reported
    transcript = run.transcript
    replied = {m["tool_call_id"] for m in transcript if m.get("role") == "tool"}
    assert replied == {"a", "b"}


def test_malformed_terminal_arguments_get_one_chance_to_be_fixed(corpus):
    chat = ScriptedChat(
        [
            turn(calls=[call(REPORT_FINDING, "{not json")]),
            turn(calls=[call(REPORT_FINDING, '{"found": false}')]),
        ]
    )
    run = AgentRuntime(chat).run("sys", "user", _registry(corpus), terminal_tools=(REPORT_FINDING,))
    assert run.reported
    assert run.report == {"found": False}
    nudge = [m for m in run.transcript if m.get("role") == "user" and "not valid JSON" in m["content"]]
    assert nudge, "the model should have been told its JSON was malformed"


def test_a_run_that_never_reports_is_exhausted_not_successful(corpus):
    chat = ScriptedChat([turn(calls=[call("read_page", '{"page": 1}')]) for _ in range(10)])
    run = AgentRuntime(chat, max_iterations=3).run(
        "sys", "user", _registry(corpus), terminal_tools=(REPORT_FINDING,)
    )
    assert run.exhausted
    assert not run.reported
    assert run.iterations == 3


def test_a_stalled_model_is_an_error_not_a_silent_success(corpus):
    chat = ScriptedChat([turn(content="")])
    run = AgentRuntime(chat).run("sys", "user", _registry(corpus), terminal_tools=(REPORT_FINDING,))
    assert not run.ok
    assert "neither text nor a tool call" in run.error


def test_a_dead_provider_ends_the_run_with_an_error_not_an_exception(corpus):
    run = AgentRuntime(BrokenChat()).run(
        "sys", "user", _registry(corpus), terminal_tools=(REPORT_FINDING,)
    )
    assert not run.ok
    assert "provider down" in run.error


def test_a_tool_budget_nudges_the_agent_to_report(corpus):
    chat = ScriptedChat([turn(calls=[call("read_page", '{"page": 1}')]) for _ in range(6)])
    run = AgentRuntime(chat, max_iterations=4, max_tool_calls=2).run(
        "sys", "user", _registry(corpus), terminal_tools=(REPORT_FINDING,)
    )
    nudges = [m for m in run.transcript if m.get("role") == "user" and "tool budget" in m["content"]]
    assert nudges


def test_a_client_without_tool_support_says_so():
    class Plain(ChatClient):
        @property
        def model_name(self):
            return "plain"

        def complete(self, messages, temperature=0.0, max_tokens=800):
            return "{}"

    with pytest.raises(ToolsUnsupported, match="deep search"):
        Plain().complete_with_tools([], [])


# --- the reader ------------------------------------------------------------ #
def _shard(corpus, size=3):
    return corpus.shards(size)[0]


def test_a_reader_converts_a_report_into_a_finding(corpus):
    chat = ScriptedChat(
        [
            turn(
                calls=[
                    call(
                        REPORT_FINDING,
                        '{"found": true, "answer": "$1,577 million", "page": 2, '
                        '"quote": "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |", '
                        '"why_authoritative": "the cash flow statement", "confidence": 0.9}',
                    )
                ]
            )
        ]
    )
    finding = ShardReader(chat, corpus).read("What was capex?", _shard(corpus))
    assert finding.found
    # The tool spoke page 2; a citation is 0-based, so the finding is page_index 1.
    assert finding.page == 1
    assert finding.confidence == 0.9
    assert finding.shard == 1


def test_a_quote_outranks_a_misattributed_page_number(corpus):
    """
    Models quote the right row and name the neighbouring page; trust the quote.

    Re-anchoring needs a quote long enough to be evidence rather than a
    coincidence, so a terse fragment leaves the model's own page number in
    place — the safe fallback.
    """
    chat = ScriptedChat(
        [
            turn(
                calls=[
                    call(
                        REPORT_FINDING,
                        '{"found": true, "answer": "$1,577 million", "page": 3, '
                        '"quote": "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |"}',
                    )
                ]
            )
        ]
    )
    finding = ShardReader(chat, corpus).read("What was capex?", _shard(corpus))
    assert finding.found
    assert finding.page == 1, "the citation should follow the quote, not the number"


def test_a_reported_page_outside_the_slice_with_no_quote_is_not_a_finding(corpus):
    chat = ScriptedChat(
        [turn(calls=[call(REPORT_FINDING, '{"found": true, "answer": "x", "page": 99}')])]
    )
    finding = ShardReader(chat, corpus).read("What was capex?", _shard(corpus))
    assert not finding.found
    assert "not in this reader's slice" in finding.reasoning


def test_found_with_no_answer_is_not_a_finding(corpus):
    chat = ScriptedChat([turn(calls=[call(REPORT_FINDING, '{"found": true, "page": 2}')])])
    finding = ShardReader(chat, corpus).read("What was capex?", _shard(corpus))
    assert not finding.found
    assert "no answer" in finding.reasoning


def test_a_reader_that_reports_nothing_found_is_a_clean_negative(corpus):
    chat = ScriptedChat([turn(calls=[call(REPORT_FINDING, '{"found": false}')])])
    finding = ShardReader(chat, corpus).read("What was capex?", _shard(corpus))
    assert not finding.found
    assert finding.answer == ""


def test_prose_instead_of_a_report_is_not_treated_as_evidence(corpus):
    """The terminal tool exists so an unstructured claim can never be a finding."""
    chat = ScriptedChat([turn(content="I think capex was about $1.6 billion.")])
    finding = ShardReader(chat, corpus).read("What was capex?", _shard(corpus))
    assert not finding.found
    assert "did not report a finding" in finding.reasoning


def test_a_reader_whose_provider_dies_reports_nothing_rather_than_raising(corpus):
    finding = ShardReader(BrokenChat(), corpus).read("What was capex?", _shard(corpus))
    assert not finding.found
    assert "reader failed" in finding.reasoning


def test_derived_inputs_are_carried_through_with_their_pages(corpus):
    chat = ScriptedChat(
        [
            turn(
                calls=[
                    call(
                        REPORT_FINDING,
                        '{"found": true, "answer": "14.9%", "page": 2, '
                        '"quote": "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |", '
                        '"computation": "(1577-1373)/1373*100", '
                        '"inputs": [{"label": "FY2022 capex", "value": "1,577", "page": 2}, '
                        '{"label": "FY2021 capex", "value": "1,373", "page": 2}]}',
                    )
                ]
            )
        ]
    )
    finding = ShardReader(chat, corpus).read("How did capex change?", _shard(corpus))
    assert finding.is_derived
    assert [item.page for item in finding.inputs] == [1, 1]
    assert finding.inputs[0].doc_name == DOC


# --- partial findings ------------------------------------------------------- #
def test_a_partial_finding_survives_even_though_it_cannot_answer(corpus):
    """
    The measured case: capex is on the cash flow statement and revenue on the
    income statement, pages apart and so in different readers' slices. Neither
    reader can answer; between them they hold everything the question needs. A
    reader that reports its figures and is then discarded makes such a question
    unanswerable however much of the document was read.
    """
    chat = ScriptedChat(
        [
            turn(
                calls=[
                    call(
                        REPORT_FINDING,
                        '{"found": false, "partial": true, '
                        '"quote": "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |", '
                        '"inputs": [{"label": "FY2022 capex", "value": "1,577", "page": 2}]}',
                    )
                ]
            )
        ]
    )
    finding = ShardReader(chat, corpus).read("Capex as a % of revenue?", _shard(corpus))
    assert not finding.found, "it did not answer the question"
    assert finding.partial
    assert finding.contributes, "but it must still reach the adjudicator"
    assert [item.value for item in finding.inputs] == ["1,577"]


def test_a_partial_needs_no_page_of_its_own(corpus):
    """Its figures carry their own pages; the finding itself may name none."""
    chat = ScriptedChat(
        [
            turn(
                calls=[
                    call(
                        REPORT_FINDING,
                        '{"found": false, "partial": true, '
                        '"inputs": [{"label": "FY2022 revenue", "value": "88,187", "page": 3}]}',
                    )
                ]
            )
        ]
    )
    finding = ShardReader(chat, corpus).read("Capex as a % of revenue?", _shard(corpus))
    assert finding.contributes
    assert finding.inputs[0].page == 2


def test_a_partial_carrying_nothing_is_not_a_contribution(corpus):
    """Claiming to hold part of it without the figures is not a contribution."""
    chat = ScriptedChat(
        [turn(calls=[call(REPORT_FINDING, '{"found": false, "partial": true}')])]
    )
    finding = ShardReader(chat, corpus).read("Capex as a % of revenue?", _shard(corpus))
    assert not finding.contributes
    assert "nothing to contribute" in finding.reasoning


def test_a_plain_not_found_still_contributes_nothing(corpus):
    chat = ScriptedChat([turn(calls=[call(REPORT_FINDING, '{"found": false}')])])
    finding = ShardReader(chat, corpus).read("What was capex?", _shard(corpus))
    assert not finding.contributes
