"""Folders: layout, membership, cross-document retrieval and folder-scoped chat."""

import hashlib

import pytest

from analyst_copilot.collections import (
    CollectionIndexer,
    CollectionSearcher,
    CollectionStore,
    InvalidCollectionName,
    sanitize_collection_name,
)
from analyst_copilot.collections.store import CollectionNotFound
from analyst_copilot.config.settings import get_settings
from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.models import ScoredPage
from analyst_copilot.retrieval.vector.builder import VectorIndexBuilder
from analyst_copilot.services.qa.models import LLMExtraction
from analyst_copilot.services.qa.verifier import AnswerVerifier, LocationMatch


class FakeEmbeddings:
    """
    Deterministic hash embeddings, so retrieval can be exercised offline.

    Not semantic — two texts sharing tokens do not land near each other. Tests
    here assert plumbing (which documents were searched, what a citation names),
    never ranking quality, which needs the real model.

    `model_name` reports whatever model is configured rather than a fake name.
    Index invalidation compares the stamped model against the configured one and
    treats a mismatch as "no index", which is right in production and would
    otherwise make every document in these tests report as unindexed.
    """

    dimensions = 32

    @property
    def model_name(self):
        return get_settings().resolved_embedding_model

    def embed_texts(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)

    def _vector(self, text: str):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [b / 255.0 for b in digest[: self.dimensions]]
        norm = sum(value * value for value in raw) ** 0.5 or 1.0
        return [value / norm for value in raw]


@pytest.fixture
def store(tmp_path):
    return CollectionStore(
        storage_dir=tmp_path / "storage", filings_dir=tmp_path / "filings"
    )


@pytest.fixture
def indexer(store):
    return CollectionIndexer(
        store=store,
        vector_builder=VectorIndexBuilder(embedding_client=FakeEmbeddings()),
    )


def _filing(tmp_path, name: str, body: str):
    path = tmp_path / f"{name}.htm"
    path.write_text(
        f'<html><body><p>{body}</p><hr style="page-break-after: always">'
        f"<p>Signatures for {name}.</p></body></html>"
    )
    return path


# -- naming ---------------------------------------------------------------- #

def test_folder_names_are_sanitized_not_trusted():
    assert sanitize_collection_name("  Boeing 2022  ") == "Boeing 2022"
    assert sanitize_collection_name("Q1/Q2 results") == "Q1 Q2 results"
    # A traversal attempt loses its separators rather than escaping the root.
    assert "/" not in sanitize_collection_name("../../etc")
    assert ".." not in sanitize_collection_name("../../etc")


def test_reserved_and_empty_names_are_rejected():
    for name in ("", "   ", "markdown", "vector_indices", "///"):
        with pytest.raises(InvalidCollectionName):
            sanitize_collection_name(name)


# -- layout and lifecycle --------------------------------------------------- #

def test_creating_a_folder_is_idempotent(store):
    first = store.create("Boeing 2022")
    second = store.create("Boeing 2022")
    assert second.created_at == first.created_at
    assert [item.name for item in store.list_all()] == ["Boeing 2022"]


def test_a_folder_mirrors_into_storage_and_filings(store, tmp_path):
    store.create("Boeing 2022")
    assert (tmp_path / "storage" / "collections" / "Boeing 2022").is_dir()
    assert (tmp_path / "filings" / "Boeing 2022").is_dir()


def test_missing_folder_raises_rather_than_returning_empty(store):
    with pytest.raises(CollectionNotFound):
        store.require("nope")


def test_two_folders_may_hold_documents_of_the_same_name(indexer, store, tmp_path):
    """`10-K` in one folder and `10-K` in another are different documents."""
    indexer.index_document("FY2022", _filing(tmp_path, "a", "Revenue was 4,010"), doc_name="10-K")
    indexer.index_document("FY2023", _filing(tmp_path, "b", "Revenue was 5,120"), doc_name="10-K")

    assert indexer.ready_documents("FY2022") == ["10-K"]
    assert indexer.ready_documents("FY2023") == ["10-K"]

    first = store.markdown_store("FY2022").load_pages("10-K")
    second = store.markdown_store("FY2023").load_pages("10-K")
    assert "4,010" in first[0].text
    assert "5,120" in second[0].text


def test_indexing_records_membership_with_format_and_size(indexer, store, tmp_path):
    indexer.index_document("Peer set", _filing(tmp_path, "AMD_2022", "Revenue was 23,601"))

    collection = store.require("Peer set")
    member = collection.find("AMD_2022")
    assert member is not None
    assert member.source_file == "AMD_2022.htm"
    assert member.source_format.value == "html"
    assert member.segment_count == 2


def test_removing_a_document_clears_its_derived_data(indexer, store, tmp_path):
    indexer.index_document("Peer set", _filing(tmp_path, "AMD_2022", "Revenue was 23,601"))
    assert store.markdown_store("Peer set").exists("AMD_2022")

    store.remove_document("Peer set", "AMD_2022")

    assert store.require("Peer set").documents == []
    assert not store.markdown_store("Peer set").exists("AMD_2022")
    assert not store.bm25_store("Peer set").exists("AMD_2022")
    assert indexer.ready_documents("Peer set") == []


def test_deleting_a_folder_keeps_the_uploads_unless_asked(indexer, store, tmp_path):
    """Indices regenerate; the originals do not."""
    source = _filing(tmp_path, "AMD_2022", "Revenue was 23,601")
    indexer.index_document("Peer set", source)
    uploads = store.uploads_dir("Peer set")
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "AMD_2022.htm").write_text(source.read_text())

    store.delete("Peer set")
    assert not store.exists("Peer set")
    assert (uploads / "AMD_2022.htm").exists()

    store.delete("Peer set", remove_uploads=True)
    assert not uploads.exists()


# -- cross-document retrieval ----------------------------------------------- #

def test_search_spans_every_document_and_names_the_source(indexer, tmp_path):
    for name, body in [
        ("AMD_2022", "Revenue was 23,601 million in fiscal 2022"),
        ("AMD_2015", "Revenue was 3,991 million in fiscal 2015"),
        ("INTEL_2022", "Revenue was 63,054 million in fiscal 2022"),
    ]:
        indexer.index_document("Semis", _filing(tmp_path, name, body))

    searcher = CollectionSearcher(
        vector_searcher=_vector_searcher(), candidate_pool=40
    )
    result = searcher.search(
        indexer.load_collection("Semis"), "revenue", top_k=6, collection_name="Semis"
    )

    assert result.hits, "a folder search must return pages"
    # Every hit knows which document it came from -- page 0 exists in all three.
    assert {hit.page.doc_name for hit in result.hits} <= {"AMD_2022", "AMD_2015", "INTEL_2022"}
    assert len({hit.page.doc_name for hit in result.hits}) > 1
    assert [hit.rank for hit in result.hits] == list(range(1, len(result.hits) + 1))


def test_search_of_an_empty_folder_returns_no_hits_rather_than_failing(indexer, store):
    store.create("Empty")
    searcher = CollectionSearcher(vector_searcher=_vector_searcher())
    result = searcher.search([], "revenue", top_k=5, collection_name="Empty")
    assert result.hits == []


def test_reindexing_a_document_invalidates_the_cached_index(indexer, tmp_path):
    """A rebuild mid-session must not keep answering from the old embeddings."""
    first = _filing(tmp_path, "AMD_2022", "Revenue was 23,601 million")
    indexer.index_document("Semis", first, doc_name="AMD_2022")
    assert "23,601" in indexer.load_document("Semis", "AMD_2022").bm25_index.pages[0].text

    revised = _filing(tmp_path, "AMD_2022_v2", "Revenue was 99,999 million")
    indexer.index_document("Semis", revised, doc_name="AMD_2022")
    assert "99,999" in indexer.load_document("Semis", "AMD_2022").bm25_index.pages[0].text


def _vector_searcher():
    from analyst_copilot.retrieval.vector.searcher import VectorSearcher

    return VectorSearcher(embedding_client=FakeEmbeddings())


# -- verification across documents ------------------------------------------ #

def _hit(doc_name: str, page_index: int, text: str, rank: int = 1) -> ScoredPage:
    return ScoredPage(
        page=Page(doc_name=doc_name, page_index=page_index, text=text),
        score=1.0,
        rank=rank,
    )


def test_a_page_number_alone_cannot_resolve_across_documents():
    """Page 59 exists in every filing; only the document says which one."""
    hits = [
        _hit("AMD_2015", 59, "Revenue was 3,991 million", rank=1),
        _hit("AMD_2022", 59, "Revenue was 23,601 million", rank=2),
    ]
    extraction = LLMExtraction(
        not_found=False, answer="23,601", page=59, document="AMD_2022"
    )
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is True
    assert result.doc_name == "AMD_2022"
    assert result.location_match is LocationMatch.EXACT


def test_document_names_are_matched_loosely():
    """A model asked to echo AMD_2022_10K will sometimes return 'AMD 2022 10-K'."""
    hits = [_hit("AMD_2022_10K", 59, "Revenue was 23,601 million")]
    extraction = LLMExtraction(
        not_found=False, answer="23,601", page=59, document="AMD 2022 10-K"
    )
    assert AnswerVerifier().verify(extraction, hits).ok is True


def test_page_tolerance_does_not_reach_into_another_document():
    """
    Page 60 of a different filing is not 'near' page 61 of this one.

    Without this, a folder of one company's annual reports would let a citation
    drift between years -- the same line item sits at a similar page in each.
    """
    hits = [_hit("AMD_2015", 60, "Revenue was 3,991 million")]
    extraction = LLMExtraction(
        not_found=False, answer="3,991", page=61, document="AMD_2022"
    )
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is False
    assert result.reason == "evidence_in_a_different_document"


def test_a_verbatim_quote_still_relocates_across_documents():
    """Quoted evidence found word for word outweighs the wrong document name."""
    text = "Total revenue for fiscal 2022 was 23,601 million dollars"
    hits = [_hit("AMD_2022", 59, text)]
    extraction = LLMExtraction(
        not_found=False,
        answer="23,601",
        page=12,
        document="AMD_2015",
        evidence_snippet=text,
    )
    result = AnswerVerifier().verify(extraction, hits)
    assert result.ok is True
    assert result.doc_name == "AMD_2022"
    assert result.location_match is LocationMatch.RELOCATED
