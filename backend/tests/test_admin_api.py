"""Admin trace viewer: allowlist gate, list, detail, and the derived fields.

DB-backed tests run inside ONE transaction on the real database (flush, never
commit, rollback at the end). The admin allowlist is monkeypatched at
deps.admin_emails, which is the function require_admin consults. No LLM call
anywhere.
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import deps as deps_module
from app.api.admin import parse_retrieval_config
from app.db.models import (
    AppUser,
    ChatSession,
    CorpusVersion,
    QueryTrace,
    RetrievalTrace,
)
from app.generation.answer import ABSTENTION_TEXT
from app.main import app
from tests._auth import auth_headers

# --- parse_retrieval_config: the shapes that exist in the live table -------


@pytest.mark.parametrize(
    "raw, config, actor, factor, legacy",
    [
        ("hybrid_bm25", "hybrid_bm25", None, None, True),
        ("hybrid_bm25|actor=none", "hybrid_bm25", None, None, False),
        (
            "hybrid_bm25|actor=provider|factor=0.25",
            "hybrid_bm25",
            "provider",
            0.25,
            False,
        ),
        (
            "vector_only_degraded|actor=deployer|factor=0.25",
            "vector_only_degraded",
            "deployer",
            0.25,
            False,
        ),
    ],
)
def test_parse_retrieval_config(raw, config, actor, factor, legacy):
    info = parse_retrieval_config(raw)
    assert (info.config, info.query_actor, info.factor, info.legacy) == (
        config,
        actor,
        factor,
        legacy,
    )


# --- endpoints, DB-backed --------------------------------------------------

# 20 candidates for a provider question. Ranks 1-15 reach the context. Two
# rows are deployer provisions, which the actor prior down-weighted.
PROVIDER_CANDIDATES = (
    [f"art_16.pt_{c}" for c in "abcdefgh"]  # 1-8 provider
    + ["art_5.par_1.pt_a", "art_13.par_1"]  # 9-10 unlabelled
    + [f"art_16.pt_{c}" for c in "ijkl"]  # 11-14 provider
    + ["art_17.par_1"]  # 15 provider (last in context)
    + ["art_26.par_5", "art_9.par_1", "art_27.par_2", "art_16.par_1", "art_18.par_1"]
)  # 16-20 cut; 16 and 18 are deployer -> downweighted
EXPECTED_DOWNWEIGHTED = {"art_26.par_5", "art_27.par_2"}


@pytest.fixture
def seeded(monkeypatch):
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

        admin = AppUser(email=f"admin-test-{uuid4()}@example.com")
        owner = AppUser(email=f"owner-test-{uuid4()}@example.com")
        session.add_all([admin, owner])
        session.flush()
        # The admin is NOT the owner of anything seeded below.
        monkeypatch.setattr(
            deps_module, "admin_emails", lambda: frozenset({admin.email})
        )

        chat = ChatSession(user_id=owner.id, corpus_version_id=cv.id, title="t")
        session.add(chat)
        session.flush()

        t0 = datetime.now(UTC) - timedelta(hours=3)
        older = QueryTrace(
            user_id=owner.id,
            chat_session_id=chat.id,
            corpus_version_id=cv.id,
            query_text="Who won the World Cup?",
            answer_text=ABSTENTION_TEXT,
            abstained=True,
            model="gpt-4o",
            environment="test",
            retrieval_config="hybrid_bm25",  # legacy: pre-ADR-10 shape
            retrieval_latency_ms=120,
            generation_latency_ms=800,
            prompt_tokens=500,
            completion_tokens=20,
            created_at=t0,
        )
        newer = QueryTrace(
            user_id=owner.id,
            chat_session_id=chat.id,
            corpus_version_id=cv.id,
            query_text="What obligations apply to providers of high-risk AI systems?",
            answer_text="Providers must ensure compliance.",
            abstained=False,
            model="gpt-4o",
            environment="test",
            retrieval_config="hybrid_bm25|actor=provider|factor=0.25",
            retrieval_latency_ms=340,
            generation_latency_ms=4100,
            prompt_tokens=1400,
            completion_tokens=260,
            created_at=t0 + timedelta(hours=1),
        )
        session.add_all([older, newer])
        session.flush()
        for rank, cid in enumerate(PROVIDER_CANDIDATES, start=1):
            session.add(
                RetrievalTrace(
                    query_trace_id=newer.id,
                    chunk_id=None,
                    provision_citation_id=cid,
                    final_rank=rank,
                    rrf_score=round(0.02 - rank * 0.0005, 5),
                    vector_rank=rank - 1 if rank % 3 else None,
                    lexical_rank=rank - 1 if rank % 4 else None,
                    similarity=0.5 if rank % 3 else None,
                    used_in_context=rank <= 15,
                )
            )
        # The legacy abstained trace still has its candidates.
        for rank, cid in enumerate(["art_1", "art_2.par_1", "art_26.par_1"], start=1):
            session.add(
                RetrievalTrace(
                    query_trace_id=older.id,
                    chunk_id=None,
                    provision_citation_id=cid,
                    final_rank=rank,
                    rrf_score=0.01,
                    vector_rank=rank - 1,
                    lexical_rank=None,
                    similarity=0.4,
                    used_in_context=True,
                )
            )
        session.flush()

        app.dependency_overrides[deps_module.get_db] = lambda: session
        yield {
            "client": TestClient(app, raise_server_exceptions=False),
            "admin": admin,
            "owner": owner,
            "older": older,
            "newer": newer,
        }
    finally:
        app.dependency_overrides.clear()
        session.rollback()
        session.close()


def _admin(seeded):
    return auth_headers(email=seeded["admin"].email)


def test_admin_list_is_newest_first_and_paginates_by_before(seeded):
    c = seeded["client"]
    r = c.get("/admin/traces?limit=1&environment=test", headers=_admin(seeded))
    assert r.status_code == 200
    body = r.json()
    assert [t["id"] for t in body["traces"]] == [str(seeded["newer"].id)]
    first = body["traces"][0]
    assert first["question"].startswith("What obligations apply")
    assert first["environment"] == "test"
    assert first["abstained"] is False
    assert first["prompt_tokens"] == 1400
    assert body["next_before"] is not None

    r2 = c.get(
        f"/admin/traces?limit=50&environment=test&before={body['next_before']}",
        headers=_admin(seeded),
    )
    ids = [t["id"] for t in r2.json()["traces"]]
    assert str(seeded["older"].id) in ids
    assert str(seeded["newer"].id) not in ids


def test_admin_list_shows_who_asked_and_filters_by_user_email(seeded):
    c = seeded["client"]
    owner, admin = seeded["owner"], seeded["admin"]

    r = c.get("/admin/traces?environment=test", headers=_admin(seeded))
    rows = [
        t
        for t in r.json()["traces"]
        if t["id"] in {str(seeded["older"].id), str(seeded["newer"].id)}
    ]
    assert len(rows) == 2
    assert {t["user_email"] for t in rows} == {owner.email}
    assert {t["user_id"] for t in rows} == {str(owner.id)}

    # Exact-match filter, case-insensitive on the address.
    both = c.get(
        f"/admin/traces?user_email={owner.email.upper()}", headers=_admin(seeded)
    ).json()["traces"]
    assert {t["id"] for t in both} == {str(seeded["older"].id), str(seeded["newer"].id)}
    none = c.get(
        f"/admin/traces?user_email={admin.email}", headers=_admin(seeded)
    ).json()
    assert none["traces"] == []

    detail = c.get(f"/admin/traces/{seeded['newer'].id}", headers=_admin(seeded)).json()
    assert detail["user_email"] == owner.email
    assert detail["user_id"] == str(owner.id)


def test_admin_detail_orders_candidates_and_replays_the_actor_prior(seeded):
    r = seeded["client"].get(
        f"/admin/traces/{seeded['newer'].id}", headers=_admin(seeded)
    )
    assert r.status_code == 200
    body = r.json()

    assert body["answer"] == "Providers must ensure compliance."
    assert body["retrieval"] == {
        "config": "hybrid_bm25",
        "query_actor": "provider",
        "factor": 0.25,
        "legacy": False,
    }
    cands = body["candidates"]
    assert [c["final_rank"] for c in cands] == list(range(1, 21))
    assert [c["citation_id"] for c in cands] == PROVIDER_CANDIDATES
    assert [c["used_in_context"] for c in cands] == [True] * 15 + [False] * 5
    assert {
        c["citation_id"] for c in cands if c["downweighted"]
    } == EXPECTED_DOWNWEIGHTED
    assert cands[0]["citation_label"] == "Article 16, point (a)"
    assert cands[0]["actor"] == "provider"
    assert cands[8]["actor"] is None  # art_5 is unlabelled
    assert [c["citation_id"] for c in body["citations"]] == PROVIDER_CANDIDATES[:15]


def test_admin_detail_legacy_abstained_trace(seeded):
    r = seeded["client"].get(
        f"/admin/traces/{seeded['older'].id}", headers=_admin(seeded)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is True
    assert body["citations"] == []  # dropped on abstention, as _persist_turn does
    assert body["retrieval"]["legacy"] is True
    assert len(body["candidates"]) == 3
    # No actor information was recorded, so nothing can be marked down-weighted,
    # even though art_26.par_1 is a deployer provision.
    assert all(c["downweighted"] is False for c in body["candidates"])


def test_admin_sees_traces_they_do_not_own_and_owners_do_not_see_admin_routes(seeded):
    c = seeded["client"]
    owner = auth_headers(email=seeded["owner"].email)
    # Owner of the session, not an admin: the admin surface does not exist.
    assert c.get("/admin/traces", headers=owner).status_code == 404
    assert (
        c.get(f"/admin/traces/{seeded['newer'].id}", headers=owner).status_code == 404
    )
    assert c.get("/admin/traces", headers=owner).json()["error"]["code"] == "not_found"
    # Admin, not the owner: sees it.
    assert (
        c.get(f"/admin/traces/{seeded['newer'].id}", headers=_admin(seeded)).status_code
        == 200
    )


def test_admin_unknown_trace_is_404_and_no_token_is_401(seeded):
    c = seeded["client"]
    assert c.get(f"/admin/traces/{uuid4()}", headers=_admin(seeded)).status_code == 404
    assert c.get("/admin/traces").status_code == 401
    assert c.get(f"/admin/traces/{seeded['newer'].id}").status_code == 401


def test_empty_allowlist_closes_the_viewer(seeded, monkeypatch):
    monkeypatch.setattr(deps_module, "admin_emails", lambda: frozenset())
    assert (
        seeded["client"].get("/admin/traces", headers=_admin(seeded)).status_code == 404
    )
