"""Feature B: greetings and empty input get the scope message, deterministically,
before any paid call. The retrieval refusal itself is untouched."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import ask as ask_module
from app.api import deps as deps_module
from app.generation.scope import (
    SCOPE_ASSESS_HINT,
    SCOPE_EXAMPLES,
    SCOPE_MESSAGE,
    is_trivial_input,
)
from app.main import app
from tests._auth import auth_headers


@pytest.mark.parametrize(
    "text",
    [
        "hey",
        "Hi!",
        "hello there",
        "Thanks",
        "ok",
        "???",
        "...",
        "  ",
        "good morning",
        "hello copilot",
        "what can you do",
    ],
)
def test_trivial_inputs_are_detected(text):
    assert is_trivial_input(text)


@pytest.mark.parametrize(
    "text",
    [
        "What obligations apply to providers of high-risk AI systems?",
        "hi, what obligations apply to providers?",
        "Article 5",
        "credit scoring",
        "Is emotion recognition at work prohibited",
        "hello I run a recruitment tool, is it high-risk",
    ],
)
def test_real_questions_are_not_trivial(text):
    assert not is_trivial_input(text)


def test_scope_copy_says_what_it_is_and_is_not_and_stays_honest():
    assert "EU AI Act" in SCOPE_MESSAGE and "not a general chatbot" in SCOPE_MESSAGE
    assert len(SCOPE_EXAMPLES) == 3
    assert "not legal advice" in SCOPE_ASSESS_HINT
    for s in (SCOPE_MESSAGE, SCOPE_ASSESS_HINT, *SCOPE_EXAMPLES):
        assert "—" not in s


@pytest.fixture
def client(monkeypatch):
    session = MagicMock()
    user = MagicMock()
    monkeypatch.setattr(ask_module, "resolve_user", lambda *_: user)

    def quota(*_):
        raise AssertionError("quota consulted for a scope notice")

    def generate(*_, **__):
        raise AssertionError("paid path reached for a scope notice")

    monkeypatch.setattr(ask_module, "enforce_daily_quota", quota)
    monkeypatch.setattr(ask_module, "generate_grounded_answer", generate)
    app.dependency_overrides[deps_module.get_db] = lambda: session
    c = TestClient(app, raise_server_exceptions=False)
    c.session = session
    yield c
    app.dependency_overrides.clear()


def test_greeting_returns_scope_notice_with_no_call_no_session_no_quota(client):
    r = client.post("/ask", json={"question": "hey"}, headers=auth_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope_notice"] is True and body["abstained"] is True
    assert body["answer"] == SCOPE_MESSAGE and body["citations"] == []
    assert body["session_id"] is None
    client.session.add.assert_not_called()  # no chat_session row, no messages
    client.session.commit.assert_not_called()


def test_greeting_inside_an_existing_thread_does_not_touch_it(client):
    r = client.post(
        "/ask",
        json={
            "question": "thanks!",
            "session_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=auth_headers(),
    )
    assert r.status_code == 200 and r.json()["scope_notice"] is True
    client.session.add.assert_not_called()
