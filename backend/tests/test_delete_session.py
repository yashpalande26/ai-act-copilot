"""Feature A: DELETE /sessions/{id}. Owner-only, 404 no-leak, messages and
citations gone, query_trace preserved (detached, user kept, quota unchanged),
saved assessments untouched. One transaction, flush not commit, rollback."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import deps as deps_module
from app.db.models import (
    AppUser,
    Assessment,
    ChatSession,
    Citation,
    CorpusVersion,
    Message,
    QueryTrace,
    RetrievalTrace,
)
from app.main import app
from tests._auth import auth_headers


@pytest.fixture
def seeded():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import SessionLocal

    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        alice = AppUser(email=f"delete-test-a-{uuid4()}@example.com")
        bob = AppUser(email=f"delete-test-b-{uuid4()}@example.com")
        session.add_all([alice, bob])
        session.flush()
        chat = ChatSession(user_id=alice.id, corpus_version_id=cv.id, title="Providers")
        keep = ChatSession(user_id=alice.id, corpus_version_id=cv.id, title="Keep me")
        session.add_all([chat, keep])
        session.flush()
        for c in (chat, keep):
            session.add(Message(session_id=c.id, role="user", content="q"))
            a = Message(session_id=c.id, role="assistant", content="a")
            session.add(a)
            session.flush()
            session.add(
                Citation(
                    message_id=a.id,
                    chunk_id=None,
                    provision_citation_id="art_16.pt_a",
                    quoted_text="x",
                )
            )
        trace = QueryTrace(
            user_id=alice.id,
            chat_session_id=chat.id,
            corpus_version_id=cv.id,
            query_text="q",
            answer_text="a",
            abstained=False,
            model="test-model",
            environment="test",
            retrieval_config="hybrid_bm25|actor=none",
            retrieval_latency_ms=1,
        )
        session.add(trace)
        session.flush()
        session.add(
            RetrievalTrace(
                query_trace_id=trace.id,
                chunk_id=None,
                provision_citation_id="art_16.pt_a",
                final_rank=1,
                rrf_score=0.1,
                vector_rank=1,
                lexical_rank=1,
                similarity=0.5,
                used_in_context=True,
            )
        )
        assessment = Assessment(
            user_id=alice.id,
            corpus_version_id=cv.id,
            environment="test",
            engine_version="assess-2.test",
            corpus_consolidated_date="2026-07-27",
            answers={"roles": ["provider"]},
            headline="MINIMAL",
            roles=["provider"],
            obligation_citation_ids=[],
            penalties={},
        )
        session.add(assessment)
        session.flush()
        app.dependency_overrides[deps_module.get_db] = lambda: session
        yield {
            "session": session,
            "client": TestClient(app, raise_server_exceptions=False),
            "alice": auth_headers(email=alice.email),
            "alice_id": alice.id,
            "bob": auth_headers(email=bob.email),
            "chat": chat,
            "keep": keep,
            "trace": trace,
            "assessment": assessment,
        }
    finally:
        app.dependency_overrides.clear()
        session.commit = real_commit
        session.rollback()
        session.close()


def _count(session, model, **where):
    stmt = select(func.count()).select_from(model)
    for k, v in where.items():
        stmt = stmt.where(getattr(model, k) == v)
    return session.execute(stmt).scalar()


def test_non_owner_and_unknown_id_get_the_same_404_and_nothing_changes(seeded):
    c, s = seeded["client"], seeded["session"]
    foreign = c.delete(f"/sessions/{seeded['chat'].id}", headers=seeded["bob"])
    unknown = c.delete(f"/sessions/{uuid4()}", headers=seeded["bob"])
    assert foreign.status_code == unknown.status_code == 404
    strip = lambda r: {k: v for k, v in r.json()["error"].items() if k != "request_id"}
    assert (
        strip(foreign) == strip(unknown)
        and strip(foreign)["code"] == "session_not_found"
    )
    assert _count(s, Message, session_id=seeded["chat"].id) == 2
    assert c.delete(f"/sessions/{seeded['chat'].id}").status_code == 401


def test_owner_delete_removes_chat_keeps_trace_quota_and_assessments(seeded):
    c, s, alice = seeded["client"], seeded["session"], seeded["alice"]
    chat_id, trace_id = seeded["chat"].id, seeded["trace"].id
    quota_before = deps_module.calls_today(s, seeded["alice_id"])
    assert quota_before >= 1

    r = c.delete(f"/sessions/{chat_id}", headers=alice)
    assert r.status_code == 204, r.text

    # The chat, its messages and their citations are gone.
    assert s.get(ChatSession, chat_id) is None
    assert _count(s, Message, session_id=chat_id) == 0
    assert (
        s.execute(
            select(func.count())
            .select_from(Citation)
            .join(Message, Message.id == Citation.message_id)
            .where(Message.session_id == chat_id)
        ).scalar()
        == 0
    )
    # The other chat is untouched.
    assert _count(s, Message, session_id=seeded["keep"].id) == 2

    # The quota / audit row survives: detached from the session, still the user's.
    s.expire_all()
    trace = s.get(QueryTrace, trace_id)
    assert trace is not None
    assert trace.chat_session_id is None and trace.user_id == seeded["alice_id"]
    assert _count(s, RetrievalTrace, query_trace_id=trace_id) == 1
    assert deps_module.calls_today(s, seeded["alice_id"]) == quota_before

    # Saved assessments are separate records.
    assert s.get(Assessment, seeded["assessment"].id) is not None

    # Gone from the list; deleting again is the same 404.
    ids = [x["id"] for x in c.get("/sessions", headers=alice).json()["sessions"]]
    assert str(chat_id) not in ids and str(seeded["keep"].id) in ids
    assert c.delete(f"/sessions/{chat_id}", headers=alice).status_code == 404


def test_admin_trace_list_still_shows_a_detached_trace(seeded, monkeypatch):
    c, alice = seeded["client"], seeded["alice"]
    monkeypatch.setattr(
        deps_module, "admin_emails", lambda: frozenset({alice_email(alice)})
    )
    assert c.delete(f"/sessions/{seeded['chat'].id}", headers=alice).status_code == 204
    listed = c.get("/admin/traces", headers=alice)
    assert listed.status_code == 200
    assert str(seeded["trace"].id) in [t["id"] for t in listed.json()["traces"]]


def alice_email(headers: dict) -> str:
    import jwt

    from tests._auth import SECRET

    token = headers["Authorization"].removeprefix("Bearer ")
    return jwt.decode(token, SECRET, algorithms=["HS256"])["email"]
