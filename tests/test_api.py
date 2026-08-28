"""HTTP contract tests.

The pipeline is stubbed through `dependency_overrides`, so these run offline and
in milliseconds: what is under test is the API's behaviour, not the retriever's.
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analyst_copilot.api.config import ApiSettings, get_api_settings
from analyst_copilot.agent.validator import Verdict
from analyst_copilot.api.dependencies import (
    get_analyst_agent,
    get_collection_indexer,
    get_filing_service,
    get_indexer,
    get_job_manager,
    get_qa_service,
)
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.jobs import IndexingJobManager, JobStatus
from analyst_copilot.api.main import create_app
from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.models import (
    BM25IndexMetadata,
    ScoredPage,
    SearchResult,
    VectorIndexMetadata,
)
from analyst_copilot.services.qa.models import NOT_FOUND_MESSAGE, QAAnswer

from offline_harness import StubCollections, StubDeepSearch, StubValidator, build_agent

API = "/api/v1"
INDEXED = "3M_2018_10K"


class FakeStore:
    """
    An index store rooted in a temp directory.

    Real directories, because `list_known` discovers filings by scanning the
    store roots — a purely in-memory fake would not exercise that path.
    """

    def __init__(self, root, metadata_factory):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._metadata_factory = metadata_factory
        self.add(INDEXED)

    def add(self, doc_name):
        (self._root / doc_name).mkdir(parents=True, exist_ok=True)

    @property
    def present(self):
        return {path.name for path in self._root.iterdir() if path.is_dir()}

    def exists(self, doc_name):
        return doc_name in self.present

    def is_stale(self, doc_name):
        return False

    def load_metadata(self, doc_name):
        return self._metadata_factory(doc_name) if doc_name in self.present else None

    def load_pages(self, doc_name):
        return None

    def index_dir(self, doc_name):
        return self._root / doc_name


class FakeIndexer:
    """Stands in for HybridFilingIndexer without parsing or embedding anything."""

    def __init__(self):
        self.indexed = {INDEXED}
        self.saved = []
        self.stores = []

    def indices_exist(self, doc_name):
        return doc_name in self.indexed

    def parse(self, path, doc_name=None):
        return type("Doc", (), {"page_count": 3, "doc_name": doc_name})()

    def build_indices(self, document):
        return type("Indices", (), {"doc_name": document.doc_name})()

    def save_indices(self, indices):
        self.saved.append(indices.doc_name)
        self.indexed.add(indices.doc_name)
        for store in self.stores:
            store.add(indices.doc_name)

    def load_indices(self, doc_name):
        pages = [Page(doc_name=doc_name, page_index=i, text="x") for i in range(3)]
        return type("Idx", (), {"bm25_index": type("B", (), {"pages": pages})()})()


def _bm25_metadata(doc_name):
    return BM25IndexMetadata(
        doc_name=doc_name, source_path="", page_count=3, parser_version="3"
    )


def _vector_metadata(doc_name):
    return VectorIndexMetadata(
        doc_name=doc_name,
        source_path="",
        page_count=3,
        embedding_model="test-embed",
        dimensions=8,
        max_chars_per_page=2500,
        parser_version="3",
    )


class FakeQA:
    """Returns a fixed answer, or a decline for questions containing 'unknown'."""

    def answer(self, question, doc_name, filing_path=None):
        hits = [
            ScoredPage(page=Page(doc_name=doc_name, page_index=59, text="(1,577)"), score=0.9, rank=1)
        ]
        search = SearchResult(query=question, doc_name=doc_name, hits=hits)
        if "unknown" in question.lower():
            return QAAnswer(
                question=question,
                doc_name=doc_name,
                answer=NOT_FOUND_MESSAGE,
                found=False,
                retrieval=search,
                abstention_reason="model_abstain",
            )
        return QAAnswer(
            question=question,
            doc_name=doc_name,
            answer="$1,577 million",
            found=True,
            page=59,
            evidence_snippet="Purchases of property, plant and equipment",
            retrieval=search,
        )


@pytest.fixture
def client(tmp_path, monkeypatch):
    indexer = FakeIndexer()
    settings = ApiSettings(max_upload_bytes=2048, cors_origins=[])
    monkeypatch.setattr(
        ApiSettings, "upload_dir", property(lambda self: tmp_path), raising=False
    )
    jobs = IndexingJobManager(indexer=indexer, max_workers=1, budget_seconds=600)
    bm25_store = FakeStore(tmp_path / "bm25", _bm25_metadata)
    vector_store = FakeStore(tmp_path / "vector", _vector_metadata)
    indexer.stores = [bm25_store, vector_store]

    app = create_app(settings)
    app.dependency_overrides[get_api_settings] = lambda: settings
    app.dependency_overrides[get_indexer] = lambda: indexer
    app.dependency_overrides[get_job_manager] = lambda: jobs
    app.dependency_overrides[get_qa_service] = FakeQA

    qa = FakeQA()
    validator = StubValidator()
    deep = StubDeepSearch()
    app.dependency_overrides[get_collection_indexer] = lambda: StubCollections([INDEXED])
    app.dependency_overrides[get_analyst_agent] = lambda: build_agent(
        qa, validator=validator, deep=deep, ready_documents=[INDEXED]
    )
    app.dependency_overrides[get_filing_service] = lambda: FilingService(
        settings=settings,
        indexer=indexer,
        jobs=jobs,
        bm25_store=bm25_store,
        vector_store=vector_store,
    )

    with TestClient(app) as test_client:
        test_client.indexer = indexer
        test_client.jobs = jobs
        test_client.stores = (bm25_store, vector_store)
        test_client.validator = validator
        test_client.deep = deep
        test_client.app = app
        yield test_client
    jobs.shutdown(wait=True)


def _await_status(client, job_id, target, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"{API}/jobs/{job_id}").json()
        if body["status"] == target:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {target}")


# --- health ---------------------------------------------------------------- #
def test_health_reports_indexed_filings(client):
    body = client.get(f"{API}/health").json()
    assert body["status"] == "ok"
    assert "chat_model" in body


# --- add filing ------------------------------------------------------------ #
def test_add_filing_returns_202_and_indexes_in_the_background(client):
    response = client.post(
        f"{API}/filings",
        files={"file": ("NEWCO_2024_10K.htm", b"<html>filing</html>", "text/html")},
    )
    assert response.status_code == 202
    job = response.json()
    assert job["doc_name"] == "NEWCO_2024_10K"
    assert job["budget_seconds"] == 600

    done = _await_status(client, job["job_id"], JobStatus.READY.value)
    assert done["page_count"] == 3
    assert done["over_budget"] is False
    assert "NEWCO_2024_10K" in client.indexer.indexed


def test_add_filing_rejects_an_unsupported_upload(client):
    """PDF, Word, Excel and CSV are all accepted now; an image is not."""
    response = client.post(
        f"{API}/filings", files={"file": ("chart.png", b"\x89PNG\r\n", "image/png")}
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_add_filing_rejects_an_oversized_upload(client):
    response = client.post(
        f"{API}/filings", files={"file": ("big.htm", b"x" * 4096, "text/html")}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_uploaded_filename_cannot_escape_the_storage_root(client):
    response = client.post(
        f"{API}/filings",
        files={"file": ("../../../etc/passwd.htm", b"<html>x</html>", "text/html")},
    )
    assert response.status_code == 202
    assert response.json()["doc_name"] == "passwd"


def test_a_failed_index_is_reported_not_raised(client):
    def explode(document):
        raise RuntimeError("embedding provider down")

    client.indexer.build_indices = explode
    response = client.post(
        f"{API}/filings", files={"file": ("BROKEN_10K.htm", b"<html>x</html>", "text/html")}
    )
    job = _await_status(client, response.json()["job_id"], JobStatus.FAILED.value)
    assert "embedding provider down" in job["error"]


# --- status ---------------------------------------------------------------- #
def test_status_of_a_filing_indexed_before_this_process_started(client):
    body = client.get(f"{API}/filings/{INDEXED}/status").json()
    assert body["status"] == JobStatus.READY.value
    assert body["page_count"] == 3


def test_status_of_an_unknown_filing_is_404(client):
    response = client.get(f"{API}/filings/NOPE/status")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "filing_not_found"


def test_unknown_job_id_is_404(client):
    assert client.get(f"{API}/jobs/deadbeef").status_code == 404


def test_listing_reports_each_index_separately(client):
    body = client.get(f"{API}/filings").json()
    row = next(f for f in body["filings"] if f["doc_name"] == INDEXED)
    assert row["bm25"]["state"] == "ready"
    assert row["vector"]["state"] == "ready"
    assert row["vector"]["model"] == "test-embed"
    assert row["vector"]["dimensions"] == 8
    assert row["page_count"] == 3


def test_an_index_present_for_only_one_retriever_is_reported_as_such(client):
    """BM25 succeeded, embedding did not: the two badges must disagree."""
    bm25_store, vector_store = client.stores
    bm25_store.add("HALF_DONE")
    body = client.get(f"{API}/filings").json()
    row = next(f for f in body["filings"] if f["doc_name"] == "HALF_DONE")
    assert row["bm25"]["state"] == "ready"
    assert row["vector"]["state"] == "missing"


# --- chat ------------------------------------------------------------------ #
def test_chat_returns_the_answer_with_its_evidence(client):
    response = client.post(
        f"{API}/chat", json={"doc_name": INDEXED, "question": "What is FY2018 capex?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert body["answer"] == "$1,577 million"
    assert body["evidence"]["page"] == 59
    assert body["evidence"]["display_page"] == 60
    assert body["evidence"]["doc_name"] == INDEXED
    assert [hit["page"] for hit in body["retrieval"]] == [59]
    assert body["retrieval"][0]["cited"] is True
    assert body["retrieval"][0]["rank"] == 1


def test_chat_declines_with_200_not_an_error(client):
    """A decline that survived both tiers is still a 200, never an error."""
    response = client.post(
        f"{API}/chat", json={"doc_name": INDEXED, "question": "What is the unknown figure?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["answer"] == NOT_FOUND_MESSAGE
    assert body["evidence"] is None
    # The fast path abstained, so the deep path ran and also found nothing. The
    # reason names the tier that gave up last, which is the more useful one.
    assert body["abstention_reason"] == "deep_search_found_nothing"
    assert body["mode"] == "deep"
    assert client.deep.calls == ["What is the unknown figure?"]


def test_a_fast_answer_that_validates_is_served_without_deep_search(client):
    """Tier 3 costs ~50x tier 1, so it must not run when tier 1 was believed."""
    response = client.post(
        f"{API}/chat", json={"doc_name": INDEXED, "question": "What is FY2018 capex?"}
    )
    assert response.json()["mode"] == "fast"
    assert client.deep.calls == []
    assert client.validator.calls, "the fast answer should have been validated"


def test_a_fast_answer_that_fails_validation_escalates(client):
    """The validator is the gate: an answer it doubts must not be served."""
    client.app.dependency_overrides[get_analyst_agent] = lambda: build_agent(
        FakeQA(),
        validator=StubValidator(Verdict.INCORRECT, "wrong fiscal year"),
        deep=client.deep,
        ready_documents=[INDEXED],
    )
    response = client.post(
        f"{API}/chat", json={"doc_name": INDEXED, "question": "What is FY2018 capex?"}
    )
    body = response.json()
    assert client.deep.calls == ["What is FY2018 capex?"]
    assert body["found"] is False
    assert body["mode"] == "deep"


def test_a_greeting_is_answered_as_a_greeting(client):
    """The product must not search a 10-K for the word 'hi'."""
    response = client.post(f"{API}/chat", json={"doc_name": INDEXED, "question": "Hi"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "conversational"
    assert body["intent"] == "smalltalk"
    assert body["evidence"] is None
    assert body["answer"] != NOT_FOUND_MESSAGE
    assert client.deep.calls == []


def test_a_greeting_works_even_with_nothing_indexed(client):
    """Saying hello cannot require a finished index -- that is when people say it."""
    response = client.post(f"{API}/chat", json={"doc_name": "NOT_ADDED", "question": "Hi"})
    assert response.status_code == 200
    assert response.json()["mode"] == "conversational"


def test_chat_on_an_unindexed_filing_is_409(client):
    response = client.post(
        f"{API}/chat", json={"doc_name": "NOT_ADDED", "question": "What is capex?"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "filing_not_indexed"


def test_chat_validates_the_request_body(client):
    assert client.post(f"{API}/chat", json={"doc_name": INDEXED, "question": ""}).status_code == 422
    assert client.post(f"{API}/chat", json={"question": "What is capex?"}).status_code == 422


# --- streaming ------------------------------------------------------------- #
def _events(raw: str):
    """Parse an SSE body into (event, data) pairs."""
    import json as _json

    parsed = []
    for block in raw.strip().split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        name, data = "", ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if name:
            parsed.append((name, _json.loads(data) if data else {}))
    return parsed


def test_chat_stream_reports_progress_then_the_answer(client):
    response = client.post(
        f"{API}/chat/stream",
        json={"doc_name": INDEXED, "question": "What is FY2018 capex?"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # nginx buffers proxied responses by default, which would hold every event
    # until the answer arrived and defeat the endpoint entirely.
    assert response.headers["x-accel-buffering"] == "no"

    events = _events(response.text)
    names = [name for name, _ in events]
    assert "stage" in names
    assert names[-1] == "answer", "the answer must be the last event"
    assert names.count("answer") == 1

    answer = events[-1][1]
    assert answer["found"] is True
    assert answer["evidence"]["page"] == 59
    assert [stage["stage"] for _, stage in events if _ == "stage"][0] == "planning"


def test_chat_stream_reports_an_error_as_an_event_not_a_broken_stream(client):
    response = client.post(
        f"{API}/chat/stream", json={"doc_name": "NOT_ADDED", "question": "What is capex?"}
    )
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "filing_not_indexed"


def test_page_endpoint_returns_text_and_the_embedding_boundary(client, monkeypatch):
    """BM25 sees the whole page; the vector index only saw the first N chars."""
    long_text = "A" * 6000
    _, vector_store = client.stores
    monkeypatch.setattr(
        vector_store,
        "load_pages",
        lambda doc_name: [Page(doc_name=doc_name, page_index=0, text=long_text)],
        raising=False,
    )
    body = client.get(f"{API}/filings/{INDEXED}/pages/0").json()
    assert body["char_count"] == 6000
    assert body["embedded_chars"] == 2500
    assert body["truncated"] is True
    assert body["display_page"] == 1


def test_page_endpoint_404s_for_a_page_the_filing_does_not_have(client, monkeypatch):
    _, vector_store = client.stores
    monkeypatch.setattr(
        vector_store,
        "load_pages",
        lambda doc_name: [Page(doc_name=doc_name, page_index=0, text="only page")],
        raising=False,
    )
    response = client.get(f"{API}/filings/{INDEXED}/pages/99")
    assert response.status_code == 404


def test_chat_stream_reports_the_activity_under_each_milestone(client):
    """
    Stages are milestones; traces are what happened underneath them. A client
    should be able to render the thinking without asking for a second endpoint.
    """
    response = client.post(
        f"{API}/chat/stream",
        json={"doc_name": INDEXED, "question": "What is the unknown figure?"},
    )
    events = _events(response.text)
    traces = [payload for name, payload in events if name == "trace"]

    kinds = {trace["kind"] for trace in traces}
    assert kinds == {"agent", "thought", "tool"}
    assert [t["tool"] for t in traces if t["kind"] == "tool"] == ["search_document"]

    # The planner reports first, then the reader. Both are named, so a client can
    # show who is working rather than one undifferentiated feed.
    agents = [t["agent"] for t in traces if t["kind"] == "agent"]
    assert agents[:2] == ["planner", "planner"]
    assert "reader 1" in agents
    reader_statuses = [
        t["status"] for t in traces if t["kind"] == "agent" and t["agent"] == "reader 1"
    ]
    assert reader_statuses == ["running", "empty"]
    # Traces come before the answer, which is still the last event.
    assert [name for name, _ in events][-1] == "answer"


def test_the_stream_never_carries_tool_arguments_or_results(client):
    """
    A tool result is document text the verifier has not seen yet. Putting it on
    the wire would leak exactly the unverified figures the product withholds --
    so a trace carries a tool's *name* and nothing else.
    """
    response = client.post(
        f"{API}/chat/stream",
        json={"doc_name": INDEXED, "question": "What is the unknown figure?"},
    )
    for name, payload in _events(response.text):
        if name != "trace":
            continue
        assert set(payload) <= {"kind", "agent", "text", "tool", "status"}
        assert "arguments" not in payload
        assert "result" not in payload
