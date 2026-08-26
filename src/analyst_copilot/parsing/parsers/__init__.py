"""Format-specific parsers. Each converts one source format to Markdown segments."""

from analyst_copilot.parsing.parsers.docx import DocxParser
from analyst_copilot.parsing.parsers.html import HtmlParser
from analyst_copilot.parsing.parsers.pdf import PdfParser
from analyst_copilot.parsing.parsers.tabular import CsvParser, ExcelParser, PlainTextParser

__all__ = [
    "CsvParser",
    "DocxParser",
    "ExcelParser",
    "HtmlParser",
    "PdfParser",
    "PlainTextParser",
]
