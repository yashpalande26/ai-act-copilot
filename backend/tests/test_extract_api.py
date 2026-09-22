"""POST /assess/extract and the extraction provenance on saved assessments.

DB-backed tests run inside ONE transaction (commit pointed at flush, rollback
at the end). The model is a FakeExtractor: zero paid calls. The one live test
is gated behind RUN_LIVE_TESTS=1 (1 gpt-4o-mini call).
"""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import assess as assess_module
from app.api import deps as deps_module
from app.db.models import AppUser, ExtractionRun
from app.extraction.extraction import LEGAL_CHARACTERISATION_FIELDS, ExtractedAnswers
from app.extraction.llm import FakeExtractor
from app.main import app
from tests._auth import auth_headers

DESC = (
    "TalentRank Ltd is an Irish company; we are an SME with EUR 2.1 million "
    "turnover. We build and sell a tool that ranks incoming CVs for recruiters "
    "and we also use it for our own hiring. Candidates never interact with it."
)


def fake_output() -> ExtractedAnswers:
    """A plausible model output for DESC: quotes are real substrings; the
    legal-five carry a 'yes' the mapper must ignore."""
    base = {
        f: {"value": "unknown", "quote": ""}
        for f in ExtractedAnswers.model_fields
        if f not in ("roles", "prohibited_patterns", "annex_iii_point", "turnover_eur")
    }
    base.update(
        is_ai_system={"value": "yes", "quote": "ranks incoming CVs"},  # must be ignored
        undertaking={"value": "yes", "quote": "TalentRank Ltd is an Irish company"},
        sme_or_startup={"value": "yes", "quote": "we are an SME"},
        interacts_with_persons={
            "value": "no",
            "quote": "Candidates never interact with it",
        },
        open_source={"value": "no", "quote": ""},  # unquoted: downgraded
        roles={"value": ["provider", "deployer"], "quote": "We build and sell a tool"},
        prohibited_patterns={"value": [], "quote": ""},
        annex_iii_point={
            "value": "anx_III.pt_4.sub_a",
            "quote": "ranks incoming CVs for recruiters",
        },
        turnover_eur={"value": 2_100_000, "quote": "EUR 2.1 million"},
    )
    return ExtractedAnswers.model_validate(base)


@pytest.fixture
def seeded(monkeypatch):
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import SessionLocal

    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush  # endpoints "commit"; nothing leaves the transaction
    fake = FakeExtractor(fake_output())
    monkeypatch.setattr(assess_module, "get_extractor", lambda: fake)
    try:
        alice = AppUser(email=f"extract-test-a-{uuid4()}@example.com")
        bob = AppUser(email=f"extract-test-b-{uuid4()}@example.com")
        session.add_all([alice, bob])
        session.flush()
        app.dependency_overrides[deps_module.get_db] = lambda: session
        yield {
            "client": TestClient(app, raise_server_exceptions=False),
            "session": session,
            "fake": fake,
            "alice": auth_headers(email=alice.email),
            "alice_id": alice.id,
            "bob": auth_headers(email=bob.email),
            "bob_id": bob.id,
        }
    finally:
        app.dependency_overrides.clear()
        session.commit = real_commit
        session.rollback()
        session.close()


def _runs(session, user_id) -> int:
    return session.execute(
        select(func.count())
        .select_from(ExtractionRun)
        .where(ExtractionRun.user_id == user_id)
    ).scalar()


def test_unauthenticated_is_401(seeded):
    assert (
        seeded["client"].post("/assess/extract", json={"description": DESC}).status_code
        == 401
    )


def test_extract_returns_answers_and_provenance_never_a_verdict(seeded):
    c, alice = seeded["client"], seeded["alice"]
    r = c.post("/assess/extract", json={"description": DESC}, headers=alice)
    assert r.status_code == 201, r.text
    body = r.json()
    assert "headline" not in body and "report" not in body and "decision" not in body
    assert body["model"] == "fake" and len(body["prompt_version"]) == 12
    assert body["answers"]["roles"] == ["provider", "deployer"]
    assert body["answers"]["annex_iii_point"] == "anx_III.pt_4.sub_a"
    assert body["answers"]["turnover_eur"] == 2_100_000
    assert body["provenance"]["roles"] == "inferred"
    assert body["quotes"]["turnover_eur"] == "EUR 2.1 million"
    # Unquoted "no" and the legal five are unknown, listed for confirmation.
    assert body["provenance"]["open_source"] == "unknown"
    for f in LEGAL_CHARACTERISATION_FIELDS:
        assert body["provenance"][f] == "unknown", f
        assert f in body["to_confirm"]
    assert "head start" in body["note"]
    # The prompt the fake saw carries the verbatim law text and the rules.
    system_prompt, user_text = seeded["fake"].calls[-1]
    assert "Annex III points, verbatim" in system_prompt and user_text == DESC
    # The quota record was written, environment-stamped.
    session = seeded["session"]
    run = session.get(ExtractionRun, body["id"])
    assert run.status == "ok" and run.environment == "test" and run.model == "fake"
    assert run.description == DESC and run.provenance["roles"] == "inferred"


def test_over_long_description_is_422_and_spends_nothing(seeded):
    c, alice = seeded["client"], seeded["alice"]
    r = c.post("/assess/extract", json={"description": "x" * 4001}, headers=alice)
    assert r.status_code == 422
    assert seeded["fake"].calls == []
    assert _runs(seeded["session"], seeded["alice_id"]) == 0


def test_refusal_is_422_and_still_counted(seeded, monkeypatch):
    c, alice = seeded["client"], seeded["alice"]
    monkeypatch.setattr(
        assess_module, "get_extractor", lambda: FakeExtractor(None, refusal="no")
    )
    r = c.post("/assess/extract", json={"description": DESC}, headers=alice)
    assert r.status_code == 422 and r.json()["error"]["code"] == "extraction_refused"
    assert _runs(seeded["session"], seeded["alice_id"]) == 1


def test_extraction_counts_against_the_shared_daily_quota(seeded, monkeypatch):
    c, alice, bob = seeded["client"], seeded["alice"], seeded["bob"]
    monkeypatch.setenv("DAILY_LIMIT_PER_USER", "1")
    assert (
        c.post("/assess/extract", json={"description": DESC}, headers=alice).status_code
        == 201
    )
    over = c.post("/assess/extract", json={"description": DESC}, headers=alice)
    assert over.status_code == 429
    assert over.json()["error"]["code"] == "daily_quota_exceeded"
    assert _runs(seeded["session"], seeded["alice_id"]) == 1  # nothing spent on the 429
    # Per-user: bob is unaffected by alice's usage...
    monkeypatch.setenv("DAILY_LIMIT_GLOBAL", "1")
    # ...but the global circuit breaker counts everyone in this environment.
    blocked = c.post("/assess/extract", json={"description": DESC}, headers=bob)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "service_daily_quota_exceeded"
    assert deps_module.calls_today(seeded["session"]) >= 1


def test_saving_with_extraction_id_records_provenance_owner_scoped(seeded):
    c, alice, bob = seeded["client"], seeded["alice"], seeded["bob"]
    extracted = c.post(
        "/assess/extract", json={"description": DESC}, headers=alice
    ).json()
    answers = {**extracted["answers"], "is_ai_system": True}  # the user confirmed it

    saved = c.post(
        f"/assessments?extraction_id={extracted['id']}", json=answers, headers=alice
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["source"] == "extracted" and body["extraction_id"] == extracted["id"]
    assert body["report"]["decision"]["headline"] == "HIGH_RISK"  # engine, not model
    listed = c.get("/assessments", headers=alice).json()["assessments"]
    assert listed[0]["source"] == "extracted"
    html = c.get(f"/assessments/{body['id']}/export.html", headers=alice).text
    assert "pre-filled from a description on" in html
    assert "reviewed and confirmed by the user" in html
    assert "—" not in html

    # Plain form saves say so.
    plain = c.post("/assessments", json=answers, headers=alice).json()
    assert plain["source"] == "form" and plain["extraction_id"] is None
    plain_html = c.get(f"/assessments/{plain['id']}/export.html", headers=alice).text
    assert "entered by the user" in plain_html

    # Bob cannot attach alice's extraction, and an unknown id looks the same.
    before = len(c.get("/assessments", headers=bob).json()["assessments"])
    foreign = c.post(
        f"/assessments?extraction_id={extracted['id']}", json=answers, headers=bob
    )
    unknown = c.post(f"/assessments?extraction_id={uuid4()}", json=answers, headers=bob)
    assert foreign.status_code == unknown.status_code == 404
    assert (
        foreign.json()["error"]["code"]
        == unknown.json()["error"]["code"]
        == ("extraction_not_found")
    )
    assert len(c.get("/assessments", headers=bob).json()["assessments"]) == before


@pytest.mark.live
def test_live_extract_endpoint_one_real_call(monkeypatch):
    """One real gpt-4o-mini call through the endpoint (RUN_LIVE_TESTS=1)."""
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("DATABASE_URL"):
        pytest.skip("live keys not configured")
    from app.db.session import SessionLocal

    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush
    try:
        user = AppUser(email=f"extract-live-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        app.dependency_overrides[deps_module.get_db] = lambda: session
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post(
            "/assess/extract",
            json={"description": DESC},
            headers=auth_headers(email=user.email),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["model"] == "openai:gpt-4o-mini"
        assert "provider" in body["answers"]["roles"]
        for f in LEGAL_CHARACTERISATION_FIELDS:
            assert body["provenance"][f] == "unknown"
        run = session.get(ExtractionRun, body["id"])
        assert run.prompt_tokens and run.completion_tokens
        print(
            f"\nlive extract: prompt_tokens={run.prompt_tokens} "
            f"completion_tokens={run.completion_tokens} latency_ms={run.latency_ms}"
        )
    finally:
        app.dependency_overrides.clear()
        session.commit = real_commit
        session.rollback()
        session.close()
