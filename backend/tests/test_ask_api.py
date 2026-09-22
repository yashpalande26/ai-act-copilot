import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import ask as ask_module
from app.api import deps as deps_module
from app.db.models import AppUser, ChatSession, CorpusVersion
from app.generation.answer import ABSTENTION_TEXT
from app.main import app
from app.retrieval.search import SearchResult
from tests._auth import auth_headers, make_token

# Token helpers and the INTERNAL_API_SECRET / limiter-reset fixtures are shared
# with test_classify_api via tests/_auth.py and conftest.py.
_token = make_token
_auth = auth_headers


def _sr(citation_id="art_16.pt_a"):
    return SearchResult(
        chunk_id=1,
        citation_id=citation_id,
        citation_label="Article 16, point (a)",
        chunk_text="ensure that their high-risk AI systems are compliant",
        similarity=0.9,
        article_heading="Obligations of providers",
    )


class _Answer:
    def __init__(self, answer, citations):
        self.answer = answer
        self.citations = citations
        self.message_id = uuid4()


@pytest.fixture
def client(monkeypatch):
    """Wires a fake DB + fake generation so the endpoint is exercised without
    Postgres or OpenAI."""
    user = AppUser(email="a@example.com")
    user.id = uuid4()
    corpus = CorpusVersion()
    corpus.id = 1
    chat = ChatSession(user_id=user.id, corpus_version_id=1)
    chat.id = uuid4()

    session = MagicMock()

    def fake_resolve_user(_s, _caller):
        return user

    monkeypatch.setattr(ask_module, "resolve_user", fake_resolve_user)
    monkeypatch.setattr(ask_module, "enforce_daily_quota", lambda *a, **kw: None)
    monkeypatch.setattr(
        ask_module,
        "_get_or_create_session",
        lambda *a, **kw: chat,
    )
    session.execute.return_value.scalars.return_value.first.return_value = corpus

    generated = MagicMock(
        return_value=_Answer("Providers must ensure compliance.", [_sr()])
    )
    monkeypatch.setattr(ask_module, "generate_grounded_answer", generated)

    app.dependency_overrides[deps_module.get_db] = lambda: session
    c = TestClient(app, raise_server_exceptions=False)
    c.generated = generated
    c.chat_id = chat.id
    yield c
    app.dependency_overrides.clear()


# --- happy path ---------------------------------------------------------


def test_ask_happy_path(client):
    r = client.post(
        "/ask", json={"question": "What must providers do?"}, headers=_auth()
    )

    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Providers must ensure compliance."
    assert body["abstained"] is False
    assert body["session_id"] == str(client.chat_id)
    assert body["citations"] == [
        {
            "citation_id": "art_16.pt_a",
            "citation_label": "Article 16, point (a)",
            "quoted_text": "ensure that their high-risk AI systems are compliant",
        }
    ]


def test_abstention_passes_through(client, monkeypatch):
    monkeypatch.setattr(
        ask_module,
        "generate_grounded_answer",
        MagicMock(return_value=_Answer(ABSTENTION_TEXT, [])),
    )

    r = client.post(
        "/ask", json={"question": "Who won the World Cup?"}, headers=_auth()
    )

    assert r.status_code == 200
    assert r.json()["abstained"] is True
    assert r.json()["citations"] == []


# --- auth ---------------------------------------------------------------


def test_unauthenticated_is_rejected_without_spending(client):
    r = client.post("/ask", json={"question": "What must providers do?"})

    assert r.status_code == 401
    client.generated.assert_not_called()


def test_token_signed_with_wrong_secret_is_rejected(client):
    r = client.post(
        "/ask",
        json={"question": "hello"},
        headers={"Authorization": f"Bearer {_token(secret='wrong-secret')}"},
    )

    assert r.status_code == 401
    client.generated.assert_not_called()


def test_expired_token_is_rejected(client):
    # Well past the 10s leeway, so this is a genuine expiry, not clock drift.
    r = client.post("/ask", json={"question": "hello"}, headers=_auth(expires_in=-120))

    assert r.status_code == 401
    client.generated.assert_not_called()


def test_token_just_expired_within_leeway_is_accepted(client):
    """Clock drift between the BFF and FastAPI must not cause spurious 401s."""
    r = client.post("/ask", json={"question": "hello"}, headers=_auth(expires_in=-5))

    assert r.status_code == 200


# --- input validation (cost guard) --------------------------------------


def test_empty_question_is_422(client):
    r = client.post("/ask", json={"question": ""}, headers=_auth())

    assert r.status_code == 422
    client.generated.assert_not_called()


def test_oversized_question_rejected_before_any_llm_call(client):
    r = client.post(
        "/ask",
        json={"question": "x" * (config.MAX_QUESTION_CHARS + 1)},
        headers=_auth(),
    )

    assert r.status_code == 422
    # The whole point of the cap: rejected before we spend anything.
    client.generated.assert_not_called()


def test_output_token_ceiling_is_passed_to_generation(client):
    client.post("/ask", json={"question": "What must providers do?"}, headers=_auth())

    _, kwargs = client.generated.call_args
    assert kwargs["max_output_tokens"] == config.MAX_OUTPUT_TOKENS


# --- rate limiting / quota ----------------------------------------------


def test_per_minute_limit_returns_429(client):
    headers = _auth()
    codes = [
        client.post("/ask", json={"question": "hi"}, headers=headers).status_code
        for _ in range(12)
    ]

    assert 429 in codes
    assert codes.count(200) <= 10
    assert client.generated.call_count <= 10


def test_daily_quota_exceeded_returns_429(client, monkeypatch):
    def _over_quota(*a, **kw):
        from fastapi import HTTPException

        raise HTTPException(status_code=429, detail="daily_quota_exceeded")

    monkeypatch.setattr(ask_module, "enforce_daily_quota", _over_quota)

    r = client.post(
        "/ask", json={"question": "What must providers do?"}, headers=_auth()
    )

    assert r.status_code == 429
    assert r.json()["error"]["code"] == "daily_quota_exceeded"
    client.generated.assert_not_called()


# --- error hygiene ------------------------------------------------------


def test_internal_error_leaks_nothing(client, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError(
            "connection failed: postgresql://user:hunter2@db.example.com:5432/postgres"
        )

    monkeypatch.setattr(ask_module, "generate_grounded_answer", _boom)

    r = client.post(
        "/ask", json={"question": "What must providers do?"}, headers=_auth()
    )

    assert r.status_code == 500
    raw = r.text
    assert r.json()["error"]["code"] == "internal_error"
    assert r.json()["error"]["request_id"]
    # No connection string, credentials, driver text or traceback.
    for leak in ("postgresql://", "hunter2", "Traceback", "RuntimeError"):
        assert leak not in raw


def test_existing_endpoints_unaffected():
    c = TestClient(app)
    # conftest forces APP_ENV=test; on Railway this reads "production".
    assert c.get("/health").json() == {"status": "ok", "environment": "test"}


# --- quota is scoped to the current environment --------------------------


def test_calls_today_counts_only_current_environment(monkeypatch):
    """A trace written under one environment is invisible to another's quota.

    Runs inside ONE transaction that is rolled back at the end: rows are
    flushed so calls_today can see them, never committed, so the live table
    is left exactly as it was. No LLM call is involved anywhere.
    """
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from sqlalchemy import select

    from app.db.models import QueryTrace
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        if cv is None:
            pytest.skip("No corpus_version found; run ingest.py first")

        user = AppUser(email=f"quota-scope-test-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        chat = ChatSession(user_id=user.id, corpus_version_id=cv.id)
        session.add(chat)
        session.flush()
        assert deps_module.calls_today(session, user.id) == 0

        session.add(
            QueryTrace(
                user_id=user.id,
                chat_session_id=chat.id,
                corpus_version_id=cv.id,
                query_text="q",
                answer_text="a",
                abstained=False,
                model="test-model",
                environment=config.app_env(),  # "test" under conftest
                retrieval_config="hybrid_bm25|actor=none",
                retrieval_latency_ms=1,
            )
        )
        session.flush()

        # Visible to the environment that wrote it...
        assert deps_module.calls_today(session, user.id) == 1
        assert deps_module.calls_today(session) >= 1
        # ...and invisible to production's quota.
        monkeypatch.setattr(deps_module, "app_env", lambda: "production")
        assert deps_module.calls_today(session, user.id) == 0
    finally:
        session.rollback()
        session.close()


# --- integration --------------------------------------------------------


@pytest.mark.live
def test_ask_integration_real_stack():
    if not os.environ.get("DATABASE_URL") or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("DATABASE_URL / OPENAI_API_KEY not configured")
    if not os.environ.get("INTERNAL_API_SECRET"):
        pytest.skip("INTERNAL_API_SECRET not configured")

    c = TestClient(app)
    r = c.post(
        "/ask",
        json={
            "question": "What obligations apply to providers of high-risk AI systems?"
        },
        headers={
            "Authorization": f"Bearer {_token(secret=os.environ['INTERNAL_API_SECRET'], email=f'ask-it-{uuid4()}@example.com')}"
        },
    )

    assert r.status_code == 200
    assert r.json()["citations"]
