"""Conversation history: list, reopen, ownership.

The DB-backed tests run inside ONE transaction on the real database: rows are
flushed so the endpoints can see them, never committed, and rolled back at the
end, so the live tables are left exactly as they were. resolve_user commits
only when it has to CREATE an app_user, so the users are flushed first and it
never does. No LLM call is involved anywhere.
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import ask as ask_module
from app.api import deps as deps_module
from app.api.history import derive_title
from app.db.models import AppUser, ChatSession, Citation, CorpusVersion, Message
from app.generation.answer import ABSTENTION_TEXT
from app.main import app
from tests._auth import auth_headers

# --- derive_title: pure -----------------------------------------------------


def test_title_short_question_is_kept_verbatim_with_whitespace_collapsed():
    assert derive_title("  What must   providers do?\n") == "What must providers do?"


def test_title_truncates_at_a_word_boundary_with_one_ellipsis():
    words = " ".join(["obligation"] * 20)  # 219 chars
    title = derive_title(words, max_chars=50)
    assert len(title) <= 51
    assert title.endswith("…")
    assert not title[:-1].endswith(" ")
    assert title[:-1] == "obligation obligation obligation obligation"


def test_title_strips_dangling_punctuation_before_the_ellipsis():
    assert derive_title("alpha beta, gamma", max_chars=11) == "alpha beta…"


# --- /ask sets the title on creation (MagicMock session, no DB) --------------


def test_new_session_gets_title_from_first_question():
    session = MagicMock()
    question = "What obligations apply to providers of high-risk AI systems?"
    chat = ask_module._get_or_create_session(session, uuid4(), 1, None, question)
    added = session.add.call_args[0][0]
    assert added is chat
    assert isinstance(added, ChatSession)
    assert added.title == question


# --- endpoints, DB-backed, flush + rollback ---------------------------------


@pytest.fixture
def seeded():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
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

        alice = AppUser(email=f"history-test-a-{uuid4()}@example.com")
        bob = AppUser(email=f"history-test-b-{uuid4()}@example.com")
        session.add_all([alice, bob])
        session.flush()

        t0 = datetime.now(UTC) - timedelta(hours=2)

        def make_session(user, title, created_at, turns):
            chat = ChatSession(
                user_id=user.id,
                corpus_version_id=cv.id,
                title=title,
                created_at=created_at,
            )
            session.add(chat)
            session.flush()
            for i, (q, a, cites) in enumerate(turns):
                ts = created_at + timedelta(minutes=i)
                # Same timestamp for both rows, exactly as _persist_turn does.
                session.add(
                    Message(session_id=chat.id, role="user", content=q, created_at=ts)
                )
                assistant = Message(
                    session_id=chat.id, role="assistant", content=a, created_at=ts
                )
                session.add(assistant)
                session.flush()
                for cid, text in cites:
                    session.add(
                        Citation(
                            message_id=assistant.id,
                            chunk_id=None,
                            provision_citation_id=cid,
                            quoted_text=text,
                        )
                    )
            session.flush()
            return chat

        older = make_session(
            alice,
            None,  # title never written: exercises the derived-title fallback
            t0,
            [
                (
                    "What obligations apply to providers of high-risk AI systems?",
                    "Providers must ensure compliance.",
                    [("art_16.pt_a", "ensure that..."), ("art_16.pt_c", "have a QMS")],
                ),
                ("Who won the World Cup?", ABSTENTION_TEXT, []),
            ],
        )
        newer = make_session(
            alice,
            "Deployer duties",
            t0 + timedelta(hours=1),
            [
                (
                    "What must a deployer do?",
                    "Deployers must monitor.",
                    [("art_26.par_5", "monitor")],
                )
            ],
        )
        bobs = make_session(
            bob,
            "Bob's chat",
            t0,
            [("Is credit scoring high-risk?", "Yes.", [("anx_III.pt_5.sub_b", "x")])],
        )
        # A session with no messages must never appear in the list.
        empty = ChatSession(user_id=alice.id, corpus_version_id=cv.id, title="empty")
        session.add(empty)
        session.flush()

        app.dependency_overrides[deps_module.get_db] = lambda: session
        client = TestClient(app, raise_server_exceptions=False)
        yield {
            "client": client,
            "alice": alice,
            "bob": bob,
            "older": older,
            "newer": newer,
            "bobs": bobs,
            "empty": empty,
        }
    finally:
        app.dependency_overrides.clear()
        session.rollback()
        session.close()


def test_list_is_scoped_to_the_caller_newest_first_with_derived_titles(seeded):
    r = seeded["client"].get(
        "/sessions", headers=auth_headers(email=seeded["alice"].email)
    )
    assert r.status_code == 200
    rows = r.json()["sessions"]
    ids = [row["id"] for row in rows]

    assert ids == [str(seeded["newer"].id), str(seeded["older"].id)]
    assert str(seeded["bobs"].id) not in ids
    assert str(seeded["empty"].id) not in ids

    newer, older = rows
    assert newer["title"] == "Deployer duties"
    assert newer["message_count"] == 2
    assert (
        older["title"] == "What obligations apply to providers of high-risk AI systems?"
    )
    assert older["message_count"] == 4


def test_detail_orders_user_before_assistant_and_carries_citations(seeded):
    r = seeded["client"].get(
        f"/sessions/{seeded['older'].id}",
        headers=auth_headers(email=seeded["alice"].email),
    )
    assert r.status_code == 200
    body = r.json()
    assert (
        body["title"] == "What obligations apply to providers of high-risk AI systems?"
    )
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]

    first_answer = body["messages"][1]
    assert first_answer["abstained"] is False
    assert first_answer["citations"] == [
        {
            "citation_id": "art_16.pt_a",
            "citation_label": "Article 16, point (a)",
            "quoted_text": "ensure that...",
        },
        {
            "citation_id": "art_16.pt_c",
            "citation_label": "Article 16, point (c)",
            "quoted_text": "have a QMS",
        },
    ]
    abstention = body["messages"][3]
    assert abstention["abstained"] is True
    assert abstention["citations"] == []
    assert body["messages"][0]["citations"] == []


def test_foreign_and_unknown_sessions_are_the_same_404(seeded):
    headers = auth_headers(email=seeded["alice"].email)
    foreign = seeded["client"].get(f"/sessions/{seeded['bobs'].id}", headers=headers)
    unknown = seeded["client"].get(f"/sessions/{uuid4()}", headers=headers)
    assert foreign.status_code == unknown.status_code == 404

    # Identical apart from the per-request id: nothing distinguishes "not
    # yours" from "does not exist".
    def strip(r):
        return {k: v for k, v in r.json()["error"].items() if k != "request_id"}

    assert strip(foreign) == strip(unknown)
    assert strip(foreign) == {
        "code": "session_not_found",
        "message": "session_not_found",
    }


def test_history_requires_the_service_token(seeded):
    assert seeded["client"].get("/sessions").status_code == 401
    assert seeded["client"].get(f"/sessions/{seeded['older'].id}").status_code == 401
