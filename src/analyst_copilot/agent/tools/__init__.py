"""Tools the agents call to read filings and do arithmetic."""

from analyst_copilot.agent.tools.base import Tool, ToolRegistry, ToolResult, schema
from analyst_copilot.agent.tools.calculator import (
    CalculateTool,
    CalculationError,
    evaluate,
    format_result,
    normalize_expression,
)
from analyst_copilot.agent.tools.reporting import (
    REPORT_FINDING,
    REPORT_READING,
    REPORT_VALIDATION,
    SUBMIT_ANSWER,
    ReportFindingTool,
    ReportReadingTool,
    ReportValidationTool,
    SubmitAnswerTool,
)
from analyst_copilot.agent.tools.document import (
    DocumentToolset,
    ListPagesTool,
    ReadLinesTool,
    ReadPageTool,
    SearchDocumentTool,
    document_tools,
)

__all__ = [
    "REPORT_FINDING",
    "REPORT_READING",
    "REPORT_VALIDATION",
    "SUBMIT_ANSWER",
    "CalculateTool",
    "CalculationError",
    "DocumentToolset",
    "ListPagesTool",
    "ReadLinesTool",
    "ReadPageTool",
    "ReportFindingTool",
    "ReportReadingTool",
    "ReportValidationTool",
    "SearchDocumentTool",
    "SubmitAnswerTool",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "document_tools",
    "evaluate",
    "format_result",
    "normalize_expression",
    "schema",
]
