"""The tools an agent uses to read a filing.

**Page numbers here are the ones a human sees.** Every tool argument and every
line of tool output uses the 1-based page number printed in `list_pages`, which
is also what the citation label says. Internally the pipeline addresses pages by
0-based `page_index`, and that translation happens in exactly one place — where
a reader's finding becomes a citation — because a numbering that changes
meaning halfway through a conversation is how a correct answer ends up cited to
the wrong page.

**Reading is scoped.** A reader agent is given a slice of the document and may
read only that slice; asked for a page outside it, the tool says which pages it
does hold. Every page belongs to exactly one slice, so nothing in the document
goes unread — but no two readers report on the same page, which is what keeps a
dozen agents from all claiming to have found the same figure in different
places. The synthesis agent gets the whole corpus instead, because resolving
which candidate is authoritative is precisely a whole-document question.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from analyst_copilot.agent.corpus import (
    DEFAULT_READ_WINDOW,
    DEFAULT_SEARCH_LIMIT,
    DocumentCorpus,
    DocumentUnavailable,
    PageMeta,
    PageRef,
    first_line,
)
from analyst_copilot.agent.tools.base import Tool, ToolResult, schema

# Bound on how many rows `list_pages` prints before it summarises the rest.
_MAX_LISTED_PAGES = 120


class DocumentToolset:
    """
    Shared state for the document tools: the corpus, and what may be read.

    `allowed` is None for an agent that may read everything, or the exact set
    of pages a reader was assigned. The tools consult it on every call, so a
    scope cannot be widened by a cleverly worded argument.
    """

    def __init__(
        self,
        corpus: DocumentCorpus,
        allowed: Optional[Iterable[PageRef]] = None,
        scope_label: str = "",
    ) -> None:
        self._corpus = corpus
        self._allowed: Optional[Set[PageRef]] = set(allowed) if allowed is not None else None
        self._scope_label = scope_label
        self._pages_read: Set[PageRef] = set()

    # -- scope ------------------------------------------------------------- #
    @property
    def corpus(self) -> DocumentCorpus:
        return self._corpus

    @property
    def scope_label(self) -> str:
        return self._scope_label

    @property
    def pages_read(self) -> int:
        """How many distinct pages this agent actually opened."""
        return len(self._pages_read)

    def in_scope(self) -> List[PageMeta]:
        pages = self._corpus.all_pages()
        if self._allowed is None:
            return pages
        return [page for page in pages if page.ref in self._allowed]

    def documents_in_scope(self) -> List[str]:
        seen: List[str] = []
        for page in self.in_scope():
            if page.doc_name not in seen:
                seen.append(page.doc_name)
        return seen

    def resolve_document(self, doc_name: Optional[str]) -> str:
        """
        Which document a call refers to.

        A single-document scope needs no name, and demanding one invites the
        model to invent a plausible-looking filing name. With several in scope
        the name is required, because a page number alone names nothing.
        """
        available = self.documents_in_scope()
        if not available:
            raise DocumentUnavailable("No readable documents are in scope.")
        if doc_name:
            for name in available:
                if name == doc_name:
                    return name
            # Models paraphrase names: `AMD 2022 10-K` for `AMD_2022_10K`.
            loose = {_slug(name): name for name in available}
            match = loose.get(_slug(doc_name))
            if match:
                return match
            raise DocumentUnavailable(
                f"No document named {doc_name!r} in scope. In scope: {', '.join(available)}."
            )
        if len(available) == 1:
            return available[0]
        raise DocumentUnavailable(
            f"Several documents are in scope, so 'doc_name' is required: "
            f"{', '.join(available)}."
        )

    def check_page(self, doc_name: str, display_page: int) -> PageMeta:
        """Resolve a 1-based page number against the scope, or explain why not."""
        if display_page < 1:
            raise DocumentUnavailable("Page numbers start at 1.")
        page_index = display_page - 1
        scoped = [page for page in self.in_scope() if page.doc_name == doc_name]
        for page in scoped:
            if page.page_index == page_index:
                self._pages_read.add(page.ref)
                return page
        raise DocumentUnavailable(
            f"Page {display_page} of {doc_name} is not in your assigned range. "
            f"You may read {_describe_pages(scoped)}."
        )

    def scope_refs(self) -> Optional[List[PageRef]]:
        if self._allowed is None:
            return None
        return [page.ref for page in self.in_scope()]


def _slug(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _describe_pages(pages: Sequence[PageMeta]) -> str:
    if not pages:
        return "no pages"
    numbers = sorted(page.display_page for page in pages)
    if len(numbers) == 1:
        return f"page {numbers[0]}"
    contiguous = numbers == list(range(numbers[0], numbers[-1] + 1))
    if contiguous:
        return f"pages {numbers[0]}-{numbers[-1]}"
    return "pages " + ", ".join(str(number) for number in numbers)


class _ScopedTool(Tool):
    def __init__(self, toolset: DocumentToolset) -> None:
        self._toolset = toolset


class ListPagesTool(_ScopedTool):
    name = "list_pages"
    description = """
List the pages you may read, with each page's heading and size. Start here: it
is the cheapest way to find which pages are worth opening, because the heading
is taken from the page's own text rather than from the filing's index.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return schema(
            {
                "doc_name": {
                    "type": "string",
                    "description": "Limit to one document. Omit to list every document in scope.",
                }
            }
        )

    def run(self, doc_name: Optional[str] = None, **_extra: Any) -> ToolResult:
        pages = self._toolset.in_scope()
        if doc_name:
            try:
                resolved = self._toolset.resolve_document(doc_name)
            except DocumentUnavailable as exc:
                return ToolResult.failure(str(exc))
            pages = [page for page in pages if page.doc_name == resolved]

        if not pages:
            return ToolResult(content="No pages are in scope.")

        lines: List[str] = []
        current_doc = ""
        shown = pages[:_MAX_LISTED_PAGES]
        for page in shown:
            if page.doc_name != current_doc:
                current_doc = page.doc_name
                total = len([p for p in pages if p.doc_name == current_doc])
                lines.append(f"\n{current_doc} ({total} page(s) in scope):")
            try:
                heading = first_line(self._toolset.corpus.page(page.doc_name, page.page_index).text)
            except DocumentUnavailable:
                heading = "(unreadable)"
            lines.append(
                f"  page {page.display_page}  {page.char_count:>7,} chars  {heading}"
            )

        if len(pages) > len(shown):
            lines.append(f"\n... and {len(pages) - len(shown)} more page(s) in scope.")

        return ToolResult(content="\n".join(lines).strip(), meta={"pages": len(pages)})


class ReadPageTool(_ScopedTool):
    name = "read_page"
    description = """
Read one page in full, as Markdown. Financial tables are preserved as tables, so
a figure's row label and its year column are both visible — read them together
and never take a figure from the wrong column.

Long pages are returned in windows; the result says whether more remains and
which offset to pass to continue.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return schema(
            {
                "page": {
                    "type": "integer",
                    "description": "The page number exactly as shown by list_pages (1-based).",
                },
                "doc_name": {
                    "type": "string",
                    "description": "Required only when more than one document is in scope.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Character offset to resume from. Omit to read from the start.",
                },
            },
            required=["page"],
        )

    def run(
        self,
        page: Optional[int] = None,
        doc_name: Optional[str] = None,
        offset: int = 0,
        **_extra: Any,
    ) -> ToolResult:
        if page is None:
            return ToolResult.failure("read_page needs a 'page'.")
        try:
            resolved = self._toolset.resolve_document(doc_name)
            meta = self._toolset.check_page(resolved, int(page))
            view = self._toolset.corpus.page(resolved, meta.page_index)
        except (DocumentUnavailable, ValueError) as exc:
            return ToolResult.failure(str(exc))

        start = max(0, int(offset or 0))
        window = view.text[start : start + DEFAULT_READ_WINDOW]
        end = start + len(window)
        header = (
            f"{resolved} — {meta.label} ({view.char_count:,} chars, "
            f"{view.line_count} lines)"
        )
        if start:
            header += f"  [characters {start:,}-{end:,}]"
        footer = ""
        if end < view.char_count:
            footer = (
                f"\n\n[...{view.char_count - end:,} characters remain. "
                f"Call read_page again with offset={end} to continue.]"
            )
        if not window:
            footer = f"\n\n[offset {start:,} is past the end of this page.]"

        return ToolResult(
            content=f"{header}\n{'-' * len(header)}\n{window}{footer}",
            meta={"doc_name": resolved, "page_index": meta.page_index},
        )


class ReadLinesTool(_ScopedTool):
    name = "read_lines"
    description = """
Read a numbered range of lines from one page. Use this after search_document
gives you a line number, to read the rows around a match — a table row means
little without the header above it.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return schema(
            {
                "page": {
                    "type": "integer",
                    "description": "The page number as shown by list_pages (1-based).",
                },
                "start_line": {"type": "integer", "description": "First line, 1-based."},
                "end_line": {"type": "integer", "description": "Last line, inclusive."},
                "doc_name": {
                    "type": "string",
                    "description": "Required only when more than one document is in scope.",
                },
            },
            required=["page", "start_line", "end_line"],
        )

    def run(
        self,
        page: Optional[int] = None,
        start_line: int = 1,
        end_line: Optional[int] = None,
        doc_name: Optional[str] = None,
        **_extra: Any,
    ) -> ToolResult:
        if page is None:
            return ToolResult.failure("read_lines needs a 'page'.")
        try:
            resolved = self._toolset.resolve_document(doc_name)
            meta = self._toolset.check_page(resolved, int(page))
            first, last, text = self._toolset.corpus.lines(
                resolved, meta.page_index, int(start_line), end_line
            )
        except (DocumentUnavailable, ValueError) as exc:
            return ToolResult.failure(str(exc))

        if not text:
            return ToolResult(
                content=f"{resolved} — {meta.label} has fewer than {start_line} lines."
            )

        numbered = "\n".join(
            f"{number:>5}  {line}"
            for number, line in enumerate(text.split("\n"), start=first)
        )
        header = f"{resolved} — {meta.label}, lines {first}-{last}"
        return ToolResult(content=f"{header}\n{'-' * len(header)}\n{numbered}")


class SearchDocumentTool(_ScopedTool):
    name = "search_document"
    description = """
Find every line containing a phrase, within the pages you may read. Returns the
page and line number of each match so you can read around it.

Matching ignores case and digit grouping, so searching 1577 finds "1,577".
Search for the wording a filing uses — "Purchases of property, plant and
equipment" rather than "capex" — and for the figure itself when you have one.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return schema(
            {
                "query": {
                    "type": "string",
                    "description": "The phrase or figure to find.",
                },
                "doc_name": {
                    "type": "string",
                    "description": "Limit to one document. Omit to search every document in scope.",
                },
                "regex": {
                    "type": "boolean",
                    "description": "Treat the query as a regular expression.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maximum matches to return (default {DEFAULT_SEARCH_LIMIT}).",
                },
            },
            required=["query"],
        )

    def run(
        self,
        query: Optional[str] = None,
        doc_name: Optional[str] = None,
        regex: bool = False,
        limit: int = DEFAULT_SEARCH_LIMIT,
        **_extra: Any,
    ) -> ToolResult:
        if not query:
            return ToolResult.failure("search_document needs a 'query'.")

        scope_docs: Optional[List[str]] = None
        if doc_name:
            try:
                scope_docs = [self._toolset.resolve_document(doc_name)]
            except DocumentUnavailable as exc:
                return ToolResult.failure(str(exc))

        refs = self._toolset.scope_refs()
        if refs is not None and scope_docs:
            refs = [ref for ref in refs if ref.doc_name in scope_docs]

        try:
            matches = self._toolset.corpus.search(
                str(query),
                doc_names=scope_docs if refs is None else None,
                pages=refs,
                regex=bool(regex),
                limit=max(1, min(int(limit or DEFAULT_SEARCH_LIMIT), 200)),
            )
        except ValueError as exc:
            return ToolResult.failure(str(exc))

        if not matches:
            return ToolResult(
                content=(
                    f"No line matching {query!r} in {self._toolset.scope_label or 'scope'}. "
                    "Try the filing's own wording, or a different figure."
                ),
                meta={"matches": 0},
            )

        lines = [f"{len(matches)} match(es) for {query!r}:"]
        for match in matches:
            lines.append(
                f"  {match.doc_name} page {match.display_page} line {match.line_number}: {match.line}"
            )
        return ToolResult(content="\n".join(lines), meta={"matches": len(matches)})


def document_tools(toolset: DocumentToolset) -> List[Tool]:
    """The read tools, in the order an agent should think about reaching for them."""
    return [
        ListPagesTool(toolset),
        SearchDocumentTool(toolset),
        ReadPageTool(toolset),
        ReadLinesTool(toolset),
    ]
