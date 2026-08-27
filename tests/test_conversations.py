"""Chat-history contract tests.

The conversations endpoints need a database, so the fixture points the session
factory at an in-memory SQLite database — the same tables the Alembic migration
creates on Postgres, created via the models so the test needs no live server.
The QA pipeline is stubbed, so nothing here calls a model.
"""

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from analyst_copilot.api.config import ApiSettings, get_api_settings
from analyst_copilot.api.db.models import Base
from analyst_copilot.api.dependencies import (
    get_analyst_agent,
    get_conversation_service,
    get_filing_service,
    get_indexer,
    get_job_manager,
    get_qa_service,
    get_session_factory,
)
from analyst_copilot.api.filings import FilingService
from analyst_copilot.api.jobs import IndexingJobManager
from analyst_copilot.api.main import create_app
from analyst_copilot.api.services.conversations import ConversationService
from analyst_copilot.parsing.models import Page
from analyst_copilot.retrieval.models import ScoredPage, SearchResult
from analyst_copilot.services.qa.models import NOT_FOUND_MESSAGE, QAAnswer

from offline_harness import StubDeepSearch, build_agent

API = "/api/v1"
INDEXED = "3M_2018_10K"


class FakeIndexer:
    def indices_exist(self, doc_name):
        return doc_name == INDEXED

    def parse(self, path, doc_name=None):
        return type("Doc", (), {"page_count": 3, "doc_name": doc_name})()

    def build_indices(self, document):
        return type("Indices", (), {"doc_name": document.doc_name})()

    def save_indices(self, indices):
        pass

    def load_indices(self, doc_name):
        pages = [Page(doc_name=doc_name, page_index=i, text="x") for i in range(3)]
        return type("Idx", (), {"bm25_index": type("B", (), {"pages": pages})})()


class FakeQA:
    """Answers any question, or declines those containing 'unknown'."""

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


def _auth_header(user_id: str) -> dict:
    token = f"demo.{base64.b64encode(user_id.encode()).decode()}.123"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    settings = ApiSettings(cors_origins=[])
    monkeypatch.setattr(
        ApiSettings, "upload_dir", property(lambda self: tmp_path), raising=False
    )
    indexer = FakeIndexer()
    jobs = IndexingJobManager(indexer=indexer, max_workers=1, budget_seconds=600)
    service = ConversationService(factory)

    app = create_app(settings)
    app.dependency_overrides[get_api_settings] = lambda: settings
    app.dependency_overrides[get_indexer] = lambda: indexer
    app.dependency_overrides[get_job_manager] = lambda: jobs
    app.dependency_overrides[get_qa_service] = FakeQA
    # The harness is the brain behind /chat, so these tests need it too. Its
    # model-calling parts are stubbed; tier 1 is still the FakeQA above.
    deep = StubDeepSearch()
    app.dependency_overrides[get_analyst_agent] = lambda: build_agent(
        FakeQA(), deep=deep, ready_documents=[INDEXED]
    )
    app.dependency_overrides[get_filing_service] = lambda: FilingService(
        settings=settings, indexer=indexer, jobs=jobs
    )
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_conversation_service] = lambda: service

    with TestClient(app) as test_client:
        test_client.conversations = service
        yield test_client
    jobs.shutdown(wait=True)


def _start(client, title="What is capex?"):
    response = client.post(
        f"{API}/conversations",
        json={"collection": "3M multi-year", "title": title},
    )
    assert response.status_code == 201
    return response.json()


def _ask(client, conversation_id, question="What is FY2018 capex?"):
    return client.post(
        f"{API}/chat",
        json={
            "doc_name": INDEXED,
            "question": question,
            "conversation_id": conversation_id,
        },
    )


# --- lifecycle -------------------------------------------------------------- #
def test_create_and_list_conversations(client):
    created = _start(client)
    assert created["id"]
    assert created["collection"] == "3M multi-year"
    assert created["title"] == "What is capex?"
    assert created["messages"] == []

    body = client.get(f"{API}/conversations").json()
    assert [c["id"] for c in body["conversations"]] == [created["id"]]


def test_create_defaults_the_title(client):
    created = _start(client, title=None)
    assert created["title"] == "New conversation"


def test_get_returns_the_thread_with_its_messages(client):
    created = _start(client)
    answer = _ask(client, created["id"])
    assert answer.status_code == 200
    body = answer.json()
    assert body["conversation_id"] == created["id"]
    assert body["message_id"]
    assert body["user_message_id"]
    assert body["latency_ms"] is not None

    detail = client.get(f"{API}/conversations/{created['id']}").json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant"]
    user, assistant = detail["messages"]
    assert user["content"] == "What is FY2018 capex?"
    assert assistant["found"] is True
    assert assistant["page"] == 59
    # The stored result is the full ChatResponse, for verbatim re-rendering.
    assert assistant["result"]["answer"] == "$1,577 million"
    assert assistant["result"]["evidence"]["page"] == 59


def test_title_comes_from_the_first_question(client):
    created = client.post(
        f"{API}/conversations", json={"collection": "3M multi-year"}
    ).json()
    _ask(client, created["id"], question="What is the FY2018 capex figure?")
    detail = client.get(f"{API}/conversations/{created['id']}").json()
    assert detail["title"] == "What is the FY2018 capex figure?"
    assert detail["updated_at"] >= detail["created_at"]


def test_rename_conversation(client):
    created = _start(client)
    response = client.patch(
        f"{API}/conversations/{created['id']}", json={"title": "Capex question"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Capex question"


def test_delete_conversation_cascades_to_messages(client):
    created = _start(client)
    _ask(client, created["id"])
    assert client.delete(f"{API}/conversations/{created['id']}").status_code == 204
    assert client.get(f"{API}/conversations/{created['id']}").status_code == 404
    assert client.get(f"{API}/conversations").json()["conversations"] == []


def test_unknown_conversation_is_404(client):
    assert client.get(f"{API}/conversations/nope").status_code == 404
    assert client.patch(f"{API}/conversations/nope", json={"title": "x"}).status_code == 404
    assert client.delete(f"{API}/conversations/nope").status_code == 404
    assert _ask(client, "nope").status_code == 404


# --- scoping ---------------------------------------------------------------- #
def test_conversations_are_private_per_user(client):
    created = _start(client)  # u_demo
    other = client.get(
        f"{API}/conversations", headers=_auth_header("u_analyst")
    )
    assert other.json()["conversations"] == []
    # The same id exists but belongs to someone else: 404, never 403 or a leak.
    assert (
        client.get(
            f"{API}/conversations/{created['id']}", headers=_auth_header("u_analyst")
        ).status_code
        == 404
    )


def test_chat_in_another_users_conversation_is_404(client):
    created = _start(client)  # u_demo
    response = client.post(
        f"{API}/chat",
        json={
            "doc_name": INDEXED,
            "question": "What is capex?",
            "conversation_id": created["id"],
        },
        headers=_auth_header("u_analyst"),
    )
    assert response.status_code == 404


def test_malformed_token_falls_back_to_the_demo_user(client):
    created = _start(client)  # u_demo
    body = client.get(
        f"{API}/conversations", headers={"Authorization": "Bearer demo.notbase64.x"}
    ).json()
    assert [c["id"] for c in body["conversations"]] == [created["id"]]


# --- chat without persistence ------------------------------------------------ #
def test_chat_without_conversation_id_records_nothing(client):
    response = client.post(
        f"{API}/chat",
        json={"doc_name": INDEXED, "question": "What is capex?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] is None
    assert body["message_id"] is None


def test_chat_persists_a_decline_too(client):
    created = _start(client)
    body = _ask(client, created["id"], question="What is the unknown figure?").json()
    assert body["found"] is False
    detail = client.get(f"{API}/conversations/{created['id']}").json()
    assistant = detail["messages"][-1]
    assert assistant["found"] is False
    assert assistant["result"]["found"] is False


# --- no database ------------------------------------------------------------ #
def test_conversations_503_when_no_database_is_configured(client):
    client.app.dependency_overrides[get_conversation_service] = lambda: ConversationService(None)
    assert client.get(f"{API}/conversations").status_code == 503
    assert client.post(f"{API}/conversations", json={}).status_code == 503