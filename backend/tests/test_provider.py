"""Model-provider failures degrade cleanly (23 Sep 2026). Through the real
/ask route with the plain pipeline: a RateLimitError (insufficient_quota) in
generation is a 503 with the short notice and no provider text or traceback;
an embeddings failure with BM25 results proceeds bm25-only; an embeddings
failure with nothing from BM25 is a 503. Also the description logged."""

import logging
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app.api import ask as ask_module
from app.api import deps as deps_module
from app.db.models import AppUser, ChatSession, CorpusVersion, Message
from app.generation import answer as answer_module
from app.generation.provider import USER_MESSAGE, describe
from app.main import app
from app.retrieval.search import SearchResult
from tests._auth import auth_headers


def _rate_limit_error():
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.RateLimitError(
        "You exceeded your current quota, please check your plan and billing details.",
        response=httpx.Response(429, request=req),
        body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
    )


def _connection_error():
    return openai.APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    )


def _sr(chunk_id=1, cid="art_16.pt_a"):
    return SearchResult(
        chunk_id=chunk_id,
        citation_id=cid,
        citation_label=cid,
        chunk_text="ensure compliance",
        similarity=0.5,
        article_heading=None,
    )


@pytest.fixture
def client(monkeypatch):
    """The real ask route and the real plain pipeline; only the DB, auth and
    quota are faked. AGENTIC_RAG off so the path is retrieve -> generate."""
    monkeypatch.setenv("AGENTIC_RAG", "0")
    user = AppUser(email="a@example.com")
    user.id = uuid4()
    corpus = CorpusVersion()
    corpus.id = 1
    chat = ChatSession(user_id=user.id, corpus_version_id=1)
    chat.id = uuid4()
    session = MagicMock()
    added = []

    def fake_add(obj):
        added.append(obj)
        if isinstance(obj, Message) and obj.id is None:
            obj.id = uuid4()

    session.add.side_effect = fake_add
    session.execute.return_value.scalars.return_value.first.return_value = corpus
    session.execute.return_value.scalar_one.return_value = user.id
    monkeypatch.setattr(ask_module, "resolve_user", lambda s, c: user)
    monkeypatch.setattr(ask_module, "enforce_daily_quota", lambda *a, **kw: None)
    monkeypatch.setattr(ask_module, "_get_or_create_session", lambda *a, **kw: chat)
    app.dependency_overrides[deps_module.get_db] = lambda: session
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


def _no_secrets(text: str):
    for needle in (
        "Traceback",
        "RateLimitError",
        "insufficient_quota",
        "exceeded your current quota",
        "sk-",
        "APIConnectionError",
    ):
        assert needle not in text, needle


def test_generation_rate_limit_is_a_clean_503(client, monkeypatch, caplog):
    monkeypatch.setattr(answer_module, "vector_search", lambda *a, **kw: [_sr()])
    monkeypatch.setattr(answer_module, "load_index", lambda cv: object())
    monkeypatch.setattr(answer_module, "bm25_search", lambda *a, **kw: [_sr()])
    fake = MagicMock()
    fake.chat.completions.create.side_effect = _rate_limit_error()
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake)
    with caplog.at_level(logging.ERROR, logger="app.provider"):
        r = client.post(
            "/ask", json={"question": "What must providers do?"}, headers=auth_headers()
        )
    assert r.status_code == 503
    body = r.json()
    assert body["error"]["code"] == "provider_unavailable"
    assert body["error"]["message"] == USER_MESSAGE
    _no_secrets(r.text)
    # the real error is in the server log, with type, status, code and stage
    assert any(
        "stage=generation" in rec.message
        and "RateLimitError" in rec.message
        and "insufficient_quota" in rec.message
        for rec in caplog.records
    )


def test_embeddings_failure_with_bm25_results_proceeds_bm25_only(client, monkeypatch):
    def boom(*a, **kw):
        raise _connection_error()

    monkeypatch.setattr(answer_module, "vector_search", boom)
    monkeypatch.setattr(answer_module, "load_index", lambda cv: object())
    monkeypatch.setattr(answer_module, "bm25_search", lambda *a, **kw: [_sr()])
    fake = MagicMock()
    fake.chat.completions.create.return_value.choices[
        0
    ].message.content = "Providers must ensure compliance (Article 16, point (a))."
    fake.chat.completions.create.return_value.usage.prompt_tokens = 10
    fake.chat.completions.create.return_value.usage.completion_tokens = 2
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake)
    r = client.post(
        "/ask", json={"question": "What must providers do?"}, headers=auth_headers()
    )
    assert r.status_code == 200
    assert r.json()["abstained"] is False and r.json()["citations"]


def test_retrieval_fully_failing_is_a_clean_503(client, monkeypatch, caplog):
    def boom(*a, **kw):
        raise _connection_error()

    monkeypatch.setattr(answer_module, "vector_search", boom)
    monkeypatch.setattr(
        answer_module, "load_index", lambda cv: None
    )  # no BM25 index either
    fake = MagicMock()
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake)
    with caplog.at_level(logging.ERROR, logger="app.provider"):
        r = client.post(
            "/ask", json={"question": "What must providers do?"}, headers=auth_headers()
        )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "provider_unavailable"
    assert r.json()["error"]["message"] == USER_MESSAGE
    _no_secrets(r.text)
    assert fake.chat.completions.create.call_count == 0
    assert any(
        "stage=retrieval" in rec.message and "APIConnectionError" in rec.message
        for rec in caplog.records
    )


def test_describe_never_carries_the_message_text():
    d = describe(_rate_limit_error())
    assert d == "RateLimitError status=429 code=insufficient_quota"
    assert "quota, please" not in d


def test_unwrapped_provider_error_anywhere_is_still_a_clean_503(client, monkeypatch):
    def boom(*a, **kw):
        raise openai.AuthenticationError(
            "Incorrect API key provided: sk-abc",
            response=httpx.Response(
                401, request=httpx.Request("POST", "https://api.openai.com/v1/x")
            ),
            body=None,
        )

    monkeypatch.setattr(ask_module, "generate_grounded_answer", boom)
    r = client.post(
        "/ask", json={"question": "What must providers do?"}, headers=auth_headers()
    )
    assert r.status_code == 503 and r.json()["error"]["message"] == USER_MESSAGE
    _no_secrets(r.text)
    assert "sk-abc" not in r.text
