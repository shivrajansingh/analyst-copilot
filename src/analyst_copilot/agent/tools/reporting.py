"""Terminal tools: the schemas an agent finishes by filling in.

These are tools the way a form is a tool. They are never executed — the runtime
recognises the call, keeps the arguments and ends the run. Declaring the output
as a function schema rather than asking for JSON in prose buys two things:

- the provider validates the shape, so a finding arrives with its required
  fields or does not arrive;
- "I found nothing" becomes a deliberate call with `found: false`, instead of a
  paragraph a parser has to interpret.

`run` returns a harmless acknowledgement for the case where a caller wires one
of these into a registry without marking it terminal.
"""

from __future__ import annotations

from typing import Any, Dict

from analyst_copilot.agent.tools.base import Tool, ToolResult, schema

_EVIDENCE_INPUT = {
    "type": "object",
    "description": "One figure the answer was computed from, and where it was read.",
    "properties": {
        "label": {
            "type": "string",
            "description": "What the figure is, as the filing names it, e.g. 'Operating income FY2022'.",
        },
        "value": {
            "type": "string",
            "description": "The figure exactly as printed on the page, e.g. '21,410'.",
        },
        "page": {
            "type": "integer",
            "description": "The page it was read from, as shown by list_pages.",
        },
        "doc_name": {
            "type": "string",
            "description": "The document it was read from.",
        },
    },
    "required": ["label", "value", "page"],
    "additionalProperties": False,
}


class ReportFindingTool(Tool):
    name = "report_finding"
    description = """
Report what your pages say, and finish. Call this exactly once.

Set found=false when your pages do not answer the question. That is the normal
outcome for most slices of a filing and is the correct thing to report — an
invented answer is far worse than none.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return schema(
            {
                "found": {
                    "type": "boolean",
                    "description": "True only if your own pages answer the question.",
                },
                "answer": {
                    "type": "string",
                    "description": "The answer, with its units. Empty when found is false.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page carrying the evidence, as shown by list_pages.",
                },
                "quote": {
                    "type": "string",
                    "description": (
                        "The sentence or table row that proves it, copied verbatim "
                        "from the page. Required when found is true."
                    ),
                },
                "why_authoritative": {
                    "type": "string",
                    "description": (
                        "Why this page is the right place to cite for this question "
                        "— e.g. 'the consolidated statement of cash flows itself, "
                        "not the MD&A summary of it'."
                    ),
                },
                "inputs": {
                    "type": "array",
                    "items": _EVIDENCE_INPUT,
                    "description": "Required when the answer was computed. One entry per input figure.",
                },
                "computation": {
                    "type": "string",
                    "description": (
                        "The expression passed to `calculate`, when the answer was "
                        "computed. E.g. '21410 / 88187 * 100'."
                    ),
                },
                "partial": {
                    "type": "boolean",
                    "description": (
                        "True when your pages carry part of what was asked but not "
                        "all of it. Report the part you have."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": "0 to 1. How sure you are the quote proves the answer.",
                },
            },
            required=["found"],
        )

    def run(self, **_kwargs: Any) -> ToolResult:  # pragma: no cover - terminal
        return ToolResult(content="Finding recorded.")


class SubmitAnswerTool(Tool):
    name = "submit_answer"
    description = """
Submit the final answer and finish. Call this exactly once.

Cite exactly one document and one page: the page whose own text carries the
evidence. Set found=false when the findings do not support an answer you can
prove.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return schema(
            {
                "found": {
                    "type": "boolean",
                    "description": "True only if the evidence proves an answer.",
                },
                "answer": {
                    "type": "string",
                    "description": "The answer, with units. Empty when found is false.",
                },
                "doc_name": {
                    "type": "string",
                    "description": "The document the citation names.",
                },
                "page": {
                    "type": "integer",
                    "description": "The page carrying the evidence, as shown by list_pages.",
                },
                "quote": {
                    "type": "string",
                    "description": "The verbatim text on that page which proves the answer.",
                },
                "inputs": {
                    "type": "array",
                    "items": _EVIDENCE_INPUT,
                    "description": "Required when the answer was computed.",
                },
                "computation": {
                    "type": "string",
                    "description": "The expression passed to `calculate`, when the answer was computed.",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Why this page over the other candidates, or why the findings "
                        "do not support an answer."
                    ),
                },
            },
            required=["found"],
        )

    def run(self, **_kwargs: Any) -> ToolResult:  # pragma: no cover - terminal
        return ToolResult(content="Answer recorded.")


class ReportValidationTool(Tool):
    name = "report_validation"
    description = """
Report your verdict on the proposed answer, and finish. Call this exactly once.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return schema(
            {
                "verdict": {
                    "type": "string",
                    "enum": ["correct", "incorrect", "insufficient"],
                    "description": (
                        "correct = responsive, complete and supported by this page. "
                        "incorrect = answers the wrong thing or a figure is wrong. "
                        "insufficient = may be right, but this page does not prove it."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "One or two sentences. What you checked and what you found.",
                },
                "corrected_answer": {
                    "type": "string",
                    "description": (
                        "Only when the page clearly supports a different figure than "
                        "the one proposed — e.g. it was taken from the wrong year's "
                        "column. Leave empty otherwise."
                    ),
                },
            },
            required=["verdict", "reason"],
        )

    def run(self, **_kwargs: Any) -> ToolResult:  # pragma: no cover - terminal
        return ToolResult(content="Verdict recorded.")


REPORT_FINDING = "report_finding"
SUBMIT_ANSWER = "submit_answer"
REPORT_VALIDATION = "report_validation"
