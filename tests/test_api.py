"""HTTP contract tests.

The pipeline is stubbed through `dependency_overrides`, so these run offline and
in milliseconds: what is under test is the API's behaviour, not the retriever's.
"""

import time

import pytest
from fastapi.testclient import TestClient

from analyst_copilot.api.config import ApiSettings, get_api_settings
from analyst_copilot.api.dependencies import (
    get_filing_service,
    get_indexer,
    get_job_manager,
    get_qa_service,
)
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.jobs import IndexingJobManager, JobStatus
from analyst_copilot.api.main import create_app
from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.models import ScoredPage, SearchResult
from analyst_copilot.services.qa.models import NOT_FOUND_MESSAGE, QAAnswer

API = "/api/v1"
INDEXED = "3M_2018_10K"


class FakeIndexer:
    """Stands in for HybridFilingIndexer without parsing or embedding anything."""

    def __init__(self):
        self.indexed = {INDEXED}
        self.saved = []

    def indices_exist(self, doc_name):
        return doc_name in self.indexed

    def parse(self, path, doc_name=None):
        return type("Doc", (), {"page_count": 3, "doc_name": doc_name})()

    def build_indices(self, document):
        return type("Indices", (), {"doc_name": document.doc_name})()

    def save_indices(self, indices):
        self.saved.append(indices.doc_name)
        self.indexed.add(indices.doc_name)

    def load_indices(self, doc_name):
        pages = [Page(doc_name=doc_name, page_index=i, text="x") for i in range(3)]
        return type("Idx", (), {"bm25_index": type("B", (), {"pages": pages})()})()


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

    app = create_app(settings)
    app.dependency_overrides[get_api_settings] = lambda: settings
    app.dependency_overrides[get_indexer] = lambda: indexer
    app.dependency_overrides[get_job_manager] = lambda: jobs
    app.dependency_overrides[get_qa_service] = FakeQA
    app.dependency_overrides[get_filing_service] = lambda: FilingService(
        settings=settings, indexer=indexer, jobs=jobs
    )

    with TestClient(app) as test_client:
        test_client.indexer = indexer
        test_client.jobs = jobs
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


def test_add_filing_rejects_a_non_html_upload(client):
    response = client.post(
        f"{API}/filings", files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")}
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


def test_listing_shows_queryable_filings(client):
    body = client.get(f"{API}/filings").json()
    assert isinstance(body["filings"], list)


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
    assert body["retrieved_pages"] == [59]


def test_chat_declines_with_200_not_an_error(client):
    response = client.post(
        f"{API}/chat", json={"doc_name": INDEXED, "question": "What is the unknown figure?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["answer"] == NOT_FOUND_MESSAGE
    assert body["evidence"] is None
    assert body["abstention_reason"] == "model_abstain"


def test_chat_on_an_unindexed_filing_is_409(client):
    response = client.post(
        f"{API}/chat", json={"doc_name": "NOT_ADDED", "question": "What is capex?"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "filing_not_indexed"


def test_chat_validates_the_request_body(client):
    assert client.post(f"{API}/chat", json={"doc_name": INDEXED, "question": "hi"}).status_code == 422
    assert client.post(f"{API}/chat", json={"question": "What is capex?"}).status_code == 422
