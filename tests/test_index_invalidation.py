"""
An index built by an older parser must be treated as absent.

This logic is load-bearing: without it a parsing fix is silently masked by
embeddings already on disk, and the fix appears to do nothing.
"""

import json

from analyst_copilot.config.settings import get_settings
from analyst_copilot.parsing.html_filing_parser import PARSER_VERSION
from analyst_copilot.parsing.models import FilingDocument, Page
from analyst_copilot.retrieval.bm25.builder import BM25IndexBuilder
from analyst_copilot.retrieval.bm25.storage import BM25IndexStore
from analyst_copilot.retrieval.models import VectorIndexMetadata
from analyst_copilot.retrieval.vector.index import VectorIndex
from analyst_copilot.retrieval.vector.storage import VectorIndexStore

DOC = "TEST_10K"


def _document() -> FilingDocument:
    return FilingDocument(
        doc_name=DOC,
        source_path="/tmp/TEST_10K.htm",
        pages=[
            Page(doc_name=DOC, page_index=0, text="Consolidated balance sheet total assets 100"),
            Page(doc_name=DOC, page_index=1, text="Statement of cash flows capital expenditures 25"),
        ],
    )


def _rewrite_metadata(store, key: str, value) -> None:
    path = store.index_dir(DOC) / "metadata.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[key] = value
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_bm25_index_is_absent_when_parser_version_differs(tmp_path):
    store = BM25IndexStore(base_dir=tmp_path / "bm25")
    store.save(BM25IndexBuilder().build(_document()))

    assert store.exists(DOC) is True

    _rewrite_metadata(store, "parser_version", "0")
    assert store.exists(DOC) is False, "stale parser version must invalidate the index"

    _rewrite_metadata(store, "parser_version", PARSER_VERSION)
    assert store.exists(DOC) is True


def _save_vector_index(store) -> None:
    settings = get_settings()
    document = _document()
    store.save(
        VectorIndex(
            metadata=VectorIndexMetadata(
                doc_name=DOC,
                source_path=document.source_path,
                page_count=len(document.pages),
                embedding_model=settings.resolved_embedding_model,
                dimensions=3,
                max_chars_per_page=settings.retrieval_max_chars_per_page,
                parser_version=PARSER_VERSION,
            ),
            pages=document.pages,
            vectors=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        )
    )


def test_vector_index_invalidates_on_parser_model_or_truncation_change(tmp_path):
    store = VectorIndexStore(base_dir=tmp_path / "vectors")
    _save_vector_index(store)
    assert store.exists(DOC) is True

    # Page boundaries changed, so the embedded text changed.
    _rewrite_metadata(store, "parser_version", "0")
    assert store.exists(DOC) is False
    _rewrite_metadata(store, "parser_version", PARSER_VERSION)

    # Different model means a different vector space entirely.
    _rewrite_metadata(store, "embedding_model", "some-other-embedding-model")
    assert store.exists(DOC) is False
    _rewrite_metadata(store, "embedding_model", get_settings().resolved_embedding_model)

    # The truncation cap decides how much of each page was embedded.
    _rewrite_metadata(store, "max_chars_per_page", 999999)
    assert store.exists(DOC) is False
    _rewrite_metadata(
        store, "max_chars_per_page", get_settings().retrieval_max_chars_per_page
    )

    assert store.exists(DOC) is True


def test_missing_files_report_absent(tmp_path):
    bm25 = BM25IndexStore(base_dir=tmp_path / "bm25")
    vectors = VectorIndexStore(base_dir=tmp_path / "vectors")
    assert bm25.exists("NEVER_INDEXED") is False
    assert vectors.exists("NEVER_INDEXED") is False


def test_corrupt_metadata_reports_absent(tmp_path):
    store = BM25IndexStore(base_dir=tmp_path / "bm25")
    store.save(BM25IndexBuilder().build(_document()))
    (store.index_dir(DOC) / "metadata.json").write_text("{ not json", encoding="utf-8")
    assert store.exists(DOC) is False
