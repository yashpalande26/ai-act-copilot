"""Follow-up rewriting: turn-1 pass-through, idempotence, the entity guard,
history loading, and the /ask wiring. Zero paid calls (FakeExtractor)."""

import json
import os
import pathlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import ask as ask_module
from app.api import deps as deps_module
from app.db.models import AppUser, ChatSession, CorpusVersion, Message
from app.extraction.llm import FakeExtractor
from app.generation import rewrite as rw
from app.generation.answer import RewriteInfo
from app.main import app
from tests._auth import auth_headers

HISTORY = [
    ("user", "What obligations apply to providers of high-risk AI systems?"),
    (
        "assistant",
        "Article 16 lists the provider obligations for high-risk AI systems.",
    ),
]


def fake(query: str, changed: bool = True) -> FakeExtractor:
    return FakeExtractor(rw.RewriteOutput(standalone_query=query, changed=changed))


# --- pass-through and idempotence ------------------------------------------------


def test_first_turn_makes_no_call_and_passes_through():
    ex = fake("anything")
    r = rw.rewrite_followup([], "And for deployers?", extractor=ex)
    assert r.query == "And for deployers?" and not r.applied and not r.attempted
    assert ex.calls == []


def test_followup_is_rewritten_when_grounded_in_the_conversation():
    ex = fake("What obligations apply to deployers of high-risk AI systems?")
    r = rw.rewrite_followup(HISTORY, "And for deployers?", extractor=ex)
    assert r.applied and r.attempted
    assert r.query == "What obligations apply to deployers of high-risk AI systems?"
    system_prompt, user_text = ex.calls[0]
    assert "Do not add any actor" in system_prompt and "And for deployers?" in user_text
    assert HISTORY[0][1] in user_text  # the earlier turns travel verbatim


def test_already_standalone_question_is_returned_unchanged():
    q = "What measures are required for human oversight to safely interrupt a high-risk AI system?"
    for ex in (
        fake(q, changed=False),
        fake(q + "?", changed=True),
        fake("  " + q, changed=True),
    ):
        r = rw.rewrite_followup(HISTORY, q, extractor=ex)
        assert r.query == q and not r.applied, ex.calls


def test_model_failure_or_empty_output_falls_back_to_the_original():
    class Boom:
        name = "boom"

        def extract(self, **_):
            raise RuntimeError("vendor down")

    r = rw.rewrite_followup(HISTORY, "And for deployers?", extractor=Boom())
    assert r.query == "And for deployers?" and not r.applied and r.attempted
    r = rw.rewrite_followup(
        HISTORY, "And for deployers?", extractor=FakeExtractor(None, refusal="x")
    )
    assert r.query == "And for deployers?" and not r.applied


# --- the entity guard -----------------------------------------------------------


def test_guard_rejects_entities_absent_from_the_conversation():
    convo = "\n".join(c for _, c in HISTORY) + "\nAnd the penalties for that?"
    assert rw.introduced_entities(
        "What are the penalties for providers under Article 99?", convo
    ) == [
        "99",
        "article 99",
    ]
    assert rw.introduced_entities(
        "What obligations apply to importers of high-risk AI systems?", convo
    ) == ["importers"]
    assert (
        rw.introduced_entities(
            "What obligations apply to providers of high-risk AI systems?", convo
        )
        == []
    )


def test_guarded_rewrite_falls_back_to_the_original_and_records_the_terms():
    ex = fake("What are the penalties for deployers under Article 99?")
    r = rw.rewrite_followup(HISTORY, "And the penalties for that?", extractor=ex)
    assert not r.applied and r.query == "And the penalties for that?"
    assert set(r.introduced) == {"99", "article 99", "deployers"}


def test_rewrite_prompt_has_no_em_dash_and_forbids_advice():
    assert "—" not in rw.SYSTEM_PROMPT
    assert "Never turn it into a request for advice" in rw.SYSTEM_PROMPT


# --- eval set integrity -----------------------------------------------------------


def test_followup_set_is_well_formed():
    cases = json.loads(
        (
            pathlib.Path(__file__).resolve().parents[1] / "evals" / "followup_set.json"
        ).read_text()
    )
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and len(cases) >= 25
    for c in cases:
        assert c["history"] and c["history"][0][0] == "user"
        assert "—" not in c["followup"] and "—" not in c["gold_standalone"]
        if c["expected_abstention"]:
            assert c["expected_citation_id"] is None
            assert c["gold_standalone"] == c["followup"]
        else:
            assert c["expected_citation_id"]
        if c["category"] == "already_standalone":
            assert c["gold_standalone"] == c["followup"]


# --- DB-backed: history loading and the /ask wiring -----------------------------


@pytest.fixture
def seeded(monkeypatch):
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import SessionLocal

    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush
    try:
        cv = (
            session.execute(
                __import__("sqlalchemy")
                .select(CorpusVersion)
                .order_by(CorpusVersion.id.desc())
            )
            .scalars()
            .first()
        )
        user = AppUser(email=f"rewrite-test-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        chat = ChatSession(user_id=user.id, corpus_version_id=cv.id, title="t")
        session.add(chat)
        session.flush()
        for role, content in HISTORY:
            session.add(Message(session_id=chat.id, role=role, content=content))
        session.flush()
        app.dependency_overrides[deps_module.get_db] = lambda: session
        yield {
            "session": session,
            "chat": chat,
            "user": user,
            "headers": auth_headers(email=user.email),
        }
    finally:
        app.dependency_overrides.clear()
        session.commit = real_commit
        session.rollback()
        session.close()


def test_load_history_returns_the_last_messages_oldest_first(seeded):
    got = rw.load_history(seeded["session"], seeded["chat"].id)
    assert got == HISTORY
    assert rw.load_history(seeded["session"], uuid4()) == []


def test_ask_uses_the_rewrite_for_retrieval_and_stores_the_original(
    seeded, monkeypatch
):
    monkeypatch.setenv("FOLLOWUP_REWRITE", "1")  # opt in: off by default
    calls = {}

    def fake_generate(session, query, cv_id, chat_id, **kw):
        calls.update(query=query, kw=kw)
        from app.generation.answer import GroundedAnswer

        return GroundedAnswer(answer="ok", citations=[], message_id=uuid4())

    monkeypatch.setattr(ask_module, "generate_grounded_answer", fake_generate)
    monkeypatch.setattr(ask_module, "enforce_daily_quota", lambda *a, **k: None)
    monkeypatch.setattr(
        rw,
        "get_extractor",
        lambda *_: fake("What obligations apply to deployers of high-risk AI systems?"),
    )
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/ask",
        json={"question": "And for deployers?", "session_id": str(seeded["chat"].id)},
        headers=seeded["headers"],
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["rewritten_query"]
        == "What obligations apply to deployers of high-risk AI systems?"
    )
    assert (
        calls["query"] == "What obligations apply to deployers of high-risk AI systems?"
    )
    assert calls["kw"]["user_text"] == "And for deployers?"
    assert (
        isinstance(calls["kw"]["rewrite"], RewriteInfo)
        and calls["kw"]["rewrite"].applied
    )

    # First turn (no session_id): no rewrite, no call, response field is null.
    monkeypatch.setattr(
        rw, "get_extractor", lambda *_: (_ for _ in ()).throw(AssertionError("called"))
    )
    r = c.post(
        "/ask", json={"question": "And for deployers?"}, headers=seeded["headers"]
    )
    assert r.status_code == 200 and r.json()["rewritten_query"] is None
    assert calls["query"] == "And for deployers?" and not calls["kw"]["rewrite"].applied


def test_ask_makes_no_rewrite_call_when_the_flag_is_off(seeded, monkeypatch):
    """Default state after the 22 Sep 2026 gate: history exists, session_id is
    given, and still nothing is rewritten and no model is called."""
    monkeypatch.delenv("FOLLOWUP_REWRITE", raising=False)
    calls = {}

    def fake_generate(session, query, cv_id, chat_id, **kw):
        calls.update(query=query, kw=kw)
        from app.generation.answer import GroundedAnswer

        return GroundedAnswer(answer="ok", citations=[], message_id=uuid4())

    monkeypatch.setattr(ask_module, "generate_grounded_answer", fake_generate)
    monkeypatch.setattr(ask_module, "enforce_daily_quota", lambda *a, **k: None)
    monkeypatch.setattr(
        rw, "get_extractor", lambda *_: (_ for _ in ()).throw(AssertionError("called"))
    )
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/ask",
        json={"question": "And for deployers?", "session_id": str(seeded["chat"].id)},
        headers=seeded["headers"],
    )
    assert r.status_code == 200 and r.json()["rewritten_query"] is None
    assert calls["query"] == "And for deployers?"
    assert not calls["kw"]["rewrite"].applied


def test_rewrite_info_trace_fields():
    assert RewriteInfo().trace_fields("q") == {
        "rewritten_query": None,
        "rewrite_prompt_tokens": None,
        "rewrite_completion_tokens": None,
    }
    assert RewriteInfo(applied=True, prompt_tokens=3, completion_tokens=1).trace_fields(
        "Q"
    ) == {
        "rewritten_query": "Q",
        "rewrite_prompt_tokens": 3,
        "rewrite_completion_tokens": 1,
    }


@pytest.mark.live
def test_live_three_turn_conversation_rewrites_then_refuses_off_corpus(monkeypatch):
    """Real stack, 3 turns: grounded, follow-up (rewritten), off-corpus
    follow-up (must refuse). 3 gpt-4o calls + 2 gpt-4o-mini calls."""
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("DATABASE_URL"):
        pytest.skip("live keys not configured")
    from app.db.session import SessionLocal

    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush  # nothing persists
    try:
        user = AppUser(email=f"rewrite-live-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        app.dependency_overrides[deps_module.get_db] = lambda: session
        c = TestClient(app, raise_server_exceptions=False)
        h = auth_headers(email=user.email)
        t1 = c.post("/ask", json={"question": HISTORY[0][1]}, headers=h).json()
        assert not t1["abstained"] and t1["rewritten_query"] is None
        sid = t1["session_id"]
        t2 = c.post(
            "/ask",
            json={"question": "And for deployers?", "session_id": sid},
            headers=h,
        ).json()
        assert t2["rewritten_query"] and "deployer" in t2["rewritten_query"].lower()
        assert not t2["abstained"]
        assert any(
            cit["citation_id"].startswith("art_26") for cit in t2["citations"]
        ), [cit["citation_id"] for cit in t2["citations"]]
        t3 = c.post(
            "/ask",
            json={
                "question": "And what's the best pizza place in Dublin?",
                "session_id": sid,
            },
            headers=h,
        ).json()
        assert t3["abstained"], t3
        print(
            f"\nlive 3-turn: t2 rewritten -> {t2['rewritten_query']!r}; t3 abstained={t3['abstained']} rewritten={t3['rewritten_query']!r}"
        )
    finally:
        app.dependency_overrides.clear()
        session.commit = real_commit
        session.rollback()
        session.close()
