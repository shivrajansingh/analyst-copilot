"""The read surface the agents work over: parsed Markdown pages on disk.

Retrieval reads indices. The agents read **documents** — and deliberately a
different copy of them. The vector index only ever saw the first
`retrieval_max_chars_per_page` characters of each page, which is where 13% of
the corpus's gold evidence hides. The Markdown store holds every page in full,
so an agent handed a page reads what the filing actually says rather than what
fitted into an embedding.

That is the whole reason the deep path can answer questions the fast path
cannot: it is not a better model, it is a complete document.

One corpus wraps one question's scope — a folder of filings, or a single
document. Pages are addressed the way a citation addresses them, by
`(doc_name, page_index)`, so anything an agent reports can be cited without
translation.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from analyst_copilot.parsing.markdown_store import MarkdownPageStore
from analyst_copilot.parsing.models import SegmentKind

# How many pages one reader agent is responsible for. Small enough that a
# reader can hold its whole slice in mind, large enough that a 160-page filing
# is 16 agents rather than 160.
DEFAULT_PAGES_PER_SHARD = 10

# Characters returned by one `read_page` call before it starts paginating. A
# page of a 10-Q cover sheet can be 47,000 characters; handing that to a model
# in one tool result wastes the context the reader needs for the other nine.
DEFAULT_READ_WINDOW = 12000

# Cap on lines returned by one search, so a query of "the" cannot fill a
# context window with matches.
DEFAULT_SEARCH_LIMIT = 40


@dataclass(frozen=True)
class PageRef:
    doc_name: str
    page_index: int

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.doc_name}#{self.page_index}"


@dataclass(frozen=True)
class PageMeta:
    """What is known about a page without reading it."""

    doc_name: str
    page_index: int
    label: str
    segment_kind: SegmentKind
    char_count: int

    @property
    def ref(self) -> PageRef:
        return PageRef(self.doc_name, self.page_index)

    @property
    def display_page(self) -> int:
        return self.page_index + 1


@dataclass
class PageView:
    """One page's text, plus where it sits in its document."""

    doc_name: str
    page_index: int
    label: str
    segment_kind: SegmentKind
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def line_count(self) -> int:
        return self.text.count("\n") + 1 if self.text else 0

    @property
    def display_page(self) -> int:
        return self.page_index + 1


@dataclass
class SearchMatch:
    """One matching line, addressed so the agent can read around it."""

    doc_name: str
    page_index: int
    label: str
    line_number: int  # 1-based, within the page
    line: str

    @property
    def display_page(self) -> int:
        return self.page_index + 1


@dataclass
class Shard:
    """The pages one reader agent is responsible for."""

    index: int  # 1-based
    total: int
    pages: List[PageMeta] = field(default_factory=list)

    @property
    def doc_names(self) -> List[str]:
        seen: List[str] = []
        for page in self.pages:
            if page.doc_name not in seen:
                seen.append(page.doc_name)
        return seen

    @property
    def char_count(self) -> int:
        return sum(page.char_count for page in self.pages)

    def contains(self, doc_name: str, page_index: int) -> bool:
        return any(
            page.doc_name == doc_name and page.page_index == page_index
            for page in self.pages
        )

    def describe(self) -> str:
        """A one-line summary for a progress message."""
        if not self.pages:
            return "empty shard"
        by_doc: Dict[str, List[int]] = {}
        for page in self.pages:
            by_doc.setdefault(page.doc_name, []).append(page.display_page)
        parts = [
            f"{doc} pages {min(nums)}-{max(nums)}" if len(nums) > 1 else f"{doc} page {nums[0]}"
            for doc, nums in by_doc.items()
        ]
        return "; ".join(parts)


class DocumentUnavailable(LookupError):
    """The corpus has no Markdown for that document."""


class DocumentCorpus:
    """
    Read access to one question's documents, as parsed Markdown pages.

    The manifest is read once per document and cached, so listing 300 pages
    costs one file read rather than 300. Page text is cached on first read: a
    reader agent typically reads the same page two or three times as it narrows
    down a figure, and re-reading it from disk each time is pure latency.
    """

    def __init__(
        self,
        store: MarkdownPageStore,
        doc_names: Sequence[str],
        collection: Optional[str] = None,
    ) -> None:
        self._store = store
        self._collection = collection
        self._doc_names = list(doc_names)
        self._meta: Dict[str, List[PageMeta]] = {}
        self._text: Dict[PageRef, str] = {}
        # Readers run concurrently over one corpus and share this cache, which
        # is the point -- a folder's pages are loaded once, not once per agent.
        # Dict writes are atomic under the GIL, so the lock is here to stop two
        # readers doing the same file read rather than to prevent corruption.
        self._lock = threading.Lock()

    # -- construction ------------------------------------------------------- #
    @classmethod
    def for_collection(cls, name: str, doc_names: Sequence[str]) -> "DocumentCorpus":
        from analyst_copilot.collections.store import CollectionStore

        return cls(
            store=CollectionStore().markdown_store(name),
            doc_names=doc_names,
            collection=name,
        )

    @classmethod
    def for_document(cls, doc_name: str) -> "DocumentCorpus":
        return cls(store=MarkdownPageStore(), doc_names=[doc_name])

    # -- structure ---------------------------------------------------------- #
    @property
    def collection(self) -> Optional[str]:
        return self._collection

    @property
    def doc_names(self) -> List[str]:
        return list(self._doc_names)

    def pages_of(self, doc_name: str) -> List[PageMeta]:
        """Every page of one document, in order, without reading their text."""
        cached = self._meta.get(doc_name)
        if cached is not None:
            return cached

        manifest = self._store.load_manifest(doc_name)
        if manifest is None:
            raise DocumentUnavailable(
                f"No parsed Markdown for {doc_name!r}. It may still be indexing."
            )
        pages = [
            PageMeta(
                doc_name=doc_name,
                page_index=int(entry["page_index"]),
                label=str(entry.get("label") or f"page {int(entry['page_index']) + 1}"),
                segment_kind=SegmentKind(str(entry.get("kind", "page"))),
                char_count=int(entry.get("char_count", 0)),
            )
            for entry in manifest.segments
        ]
        pages.sort(key=lambda page: page.page_index)
        self._meta[doc_name] = pages
        return pages

    def all_pages(self) -> List[PageMeta]:
        """Every page of every document in scope, document order preserved."""
        pages: List[PageMeta] = []
        for doc_name in self._doc_names:
            try:
                pages.extend(self.pages_of(doc_name))
            except DocumentUnavailable:
                # A document still indexing must not make the whole folder
                # unreadable: the others can answer the question.
                continue
        return pages

    @property
    def page_count(self) -> int:
        return len(self.all_pages())

    def available_documents(self) -> List[str]:
        """Documents this corpus can actually read, in scope order."""
        readable: List[str] = []
        for doc_name in self._doc_names:
            try:
                self.pages_of(doc_name)
            except DocumentUnavailable:
                continue
            readable.append(doc_name)
        return readable

    # -- reading ------------------------------------------------------------ #
    def page(self, doc_name: str, page_index: int) -> PageView:
        meta = self._page_meta(doc_name, page_index)
        ref = meta.ref
        text = self._text.get(ref)
        if text is None:
            with self._lock:
                text = self._text.get(ref)
                if text is None:
                    loaded = self._store.load_markdown(doc_name, page_index)
                    if loaded is None:
                        raise DocumentUnavailable(
                            f"{doc_name} has no stored text for page {page_index + 1}."
                        )
                    text = loaded
                    self._text[ref] = text
        return PageView(
            doc_name=doc_name,
            page_index=page_index,
            label=meta.label,
            segment_kind=meta.segment_kind,
            text=text,
        )

    def prewarm(self) -> int:
        """
        Load every manifest up front, before agents fan out.

        Manifest reads are the one part of the cache that several readers would
        otherwise race to populate at the same instant, and doing it once here
        keeps the fan-out itself free of first-call latency spikes.
        """
        for doc_name in self._doc_names:
            try:
                self.pages_of(doc_name)
            except DocumentUnavailable:
                continue
        return self.page_count

    def lines(
        self,
        doc_name: str,
        page_index: int,
        start: int = 1,
        end: Optional[int] = None,
    ) -> Tuple[int, int, str]:
        """
        A 1-based, inclusive line range of one page.

        Returns the clamped bounds alongside the text, so a caller that asked
        for lines 400-500 of a 120-line page is told what it actually got
        rather than silently handed an empty string.
        """
        page = self.page(doc_name, page_index)
        rows = page.text.split("\n")
        first = max(1, start)
        last = len(rows) if end is None else min(len(rows), max(first, end))
        if first > len(rows):
            return first, len(rows), ""
        return first, last, "\n".join(rows[first - 1 : last])

    def search(
        self,
        pattern: str,
        doc_names: Optional[Sequence[str]] = None,
        pages: Optional[Sequence[PageRef]] = None,
        regex: bool = False,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> List[SearchMatch]:
        """
        Every line matching `pattern`, with its page and line number.

        Matching is case-insensitive, and digit grouping is normalized on both
        sides — a filing's `1,577` and a query's `1577` are the same figure, and
        a search that misses on a comma is a search an analyst cannot trust.
        """
        if not pattern.strip():
            return []

        matcher = _build_matcher(pattern, regex=regex)
        scope = self._scope(doc_names=doc_names, pages=pages)
        matches: List[SearchMatch] = []

        for meta in scope:
            try:
                page = self.page(meta.doc_name, meta.page_index)
            except DocumentUnavailable:
                continue
            for number, line in enumerate(page.text.split("\n"), start=1):
                if not line.strip():
                    continue
                if matcher(line):
                    matches.append(
                        SearchMatch(
                            doc_name=meta.doc_name,
                            page_index=meta.page_index,
                            label=meta.label,
                            line_number=number,
                            line=line.strip()[:400],
                        )
                    )
                    if len(matches) >= limit:
                        return matches
        return matches

    def find_quote(self, quote: str, min_chars: int = 24) -> Optional[PageRef]:
        """
        The page carrying this text verbatim, ignoring punctuation and spacing.

        Compared compacted because the same table row reaches us as plain text
        from one parser and as a Markdown table from another: `Marketable
        securities - current` and `| Marketable securities | current |` are the
        same evidence and only the pipes differ.
        """
        needle = _compact(quote)
        if len(needle) < min_chars:
            return None
        probe = needle[:200]
        for meta in self.all_pages():
            try:
                text = self.page(meta.doc_name, meta.page_index).text
            except DocumentUnavailable:
                continue
            if probe in _compact(text):
                return meta.ref
        return None

    def outline(self, doc_name: str) -> List[Tuple[int, str]]:
        """
        Each page's first heading or first meaningful line.

        This is how an agent orients itself in a 300-page filing without
        reading it: a table of contents built from what the pages actually say
        rather than from what the filing's own index claims.
        """
        summary: List[Tuple[int, str]] = []
        for meta in self.pages_of(doc_name):
            try:
                page = self.page(doc_name, meta.page_index)
            except DocumentUnavailable:
                continue
            summary.append((meta.page_index, first_line(page.text)))
        return summary

    # -- sharding ----------------------------------------------------------- #
    def shards(
        self,
        pages_per_shard: int = DEFAULT_PAGES_PER_SHARD,
        only: Optional[Sequence[str]] = None,
        excluding: Optional[Sequence[str]] = None,
    ) -> List[Shard]:
        """
        Split the corpus into consecutive slices of at most `pages_per_shard`.

        Shards never straddle two documents. A reader asked about "page 4" must
        not have to ask "of which filing", and a slice that spans a year-end
        boundary is exactly where a model blends two fiscal years into one
        wrong figure.

        `only` limits the sharding to named documents -- the planner's scope. On a
        three-year filing set, "what was FY2018 revenue" has no business reading
        the other two documents, and doing so triples the readers for nothing.

        `excluding` is the other half of that: sharding what a scoped search
        skipped, so a scope that turned out to be wrong can be widened rather
        than costing the answer. A name in neither list is simply absent.
        """
        if pages_per_shard <= 0:
            raise ValueError("pages_per_shard must be positive")

        wanted = self.scoped_documents(only=only, excluding=excluding)
        groups: List[List[PageMeta]] = []
        for doc_name in wanted:
            pages = self.pages_of(doc_name)
            for start in range(0, len(pages), pages_per_shard):
                groups.append(pages[start : start + pages_per_shard])

        total = len(groups)
        return [
            Shard(index=number, total=total, pages=group)
            for number, group in enumerate(groups, start=1)
        ]

    def scoped_documents(
        self,
        only: Optional[Sequence[str]] = None,
        excluding: Optional[Sequence[str]] = None,
    ) -> List[str]:
        """
        Readable documents after a scope is applied, in corpus order.

        A name in `only` that this corpus does not hold is ignored rather than
        being an error: a scope is a hint from a planner reading filenames, and
        it must not be able to break a search.
        """
        available = self.available_documents()
        if only:
            kept = [name for name in available if name in set(only)]
            # An `only` list that matches nothing would silently search nothing at
            # all, which is worse than ignoring it.
            available = kept or available
        if excluding:
            available = [name for name in available if name not in set(excluding)]
        return available

    def page_counts(self) -> Dict[str, int]:
        """Pages per document, for the planner's document cards."""
        counts: Dict[str, int] = {}
        for doc_name in self._doc_names:
            try:
                counts[doc_name] = len(self.pages_of(doc_name))
            except DocumentUnavailable:
                continue
        return counts

    # -- internals ---------------------------------------------------------- #
    def _page_meta(self, doc_name: str, page_index: int) -> PageMeta:
        for meta in self.pages_of(doc_name):
            if meta.page_index == page_index:
                return meta
        available = len(self.pages_of(doc_name))
        raise DocumentUnavailable(
            f"{doc_name} has {available} segments; page {page_index + 1} is not one of them."
        )

    def _scope(
        self,
        doc_names: Optional[Sequence[str]],
        pages: Optional[Sequence[PageRef]],
    ) -> List[PageMeta]:
        if pages is not None:
            wanted = set(pages)
            return [meta for meta in self.all_pages() if meta.ref in wanted]
        if doc_names:
            allowed = set(doc_names)
            return [meta for meta in self.all_pages() if meta.doc_name in allowed]
        return self.all_pages()


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
_DIGIT_GROUP = re.compile(r"(?<=\d),(?=\d)")


def _normalize(text: str) -> str:
    return _DIGIT_GROUP.sub("", text.lower())


def _build_matcher(pattern: str, regex: bool):
    if regex:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
        return lambda line: bool(compiled.search(line))

    needle = _normalize(pattern.strip())
    return lambda line: needle in _normalize(line)


def first_line(text: str, limit: int = 120) -> str:
    """The first heading, or the first line carrying words, of a page."""
    lines = [line.strip() for line in text.split("\n")]
    for line in lines:
        if line.startswith("#"):
            return line.lstrip("# ").strip()[:limit]
    for line in lines:
        if len(line) > 3 and re.search(r"[A-Za-z]", line):
            return line.strip("|").strip()[:limit]
    return ""


def iter_page_refs(pages: Iterable[PageMeta]) -> List[PageRef]:
    return [page.ref for page in pages]


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
