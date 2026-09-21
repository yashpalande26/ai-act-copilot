"""Saved assessments: save (answers only), list, reopen, ownership, version.

DB-backed tests run inside ONE transaction: the session's commit is pointed at
flush for the duration, so the endpoint code path (which commits) still runs
end to end while nothing persists; rollback at the end. No LLM anywhere.
"""

import hashlib
import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import deps as deps_module
from app.assessment.version import ENGINE_VERSION, rules_hash, rules_payload
from app.db.models import AppUser
from app.main import app
from tests._auth import auth_headers

HR_TECH = {
    "roles": ["provider", "deployer"],
    "annex_iii_point": "anx_III.pt_4.sub_a",
    "interacts_with_persons": True,
    "undertaking": True,
    "turnover_eur": 2_000_000,
    "sme_or_startup": True,
}


# --- engine_version ----------------------------------------------------------


def test_engine_version_shape_and_stability():
    assert ENGINE_VERSION.startswith("assess-1.")
    assert len(ENGINE_VERSION.split(".")[-1]) == 12
    assert rules_hash() == rules_hash()


def test_rules_hash_is_canonical_sha256_of_sorted_json():
    # Reproducible by anyone from the payload alone: sorted keys, no spaces, ASCII.
    canonical = json.dumps(
        rules_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    assert rules_hash() == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    # The payload is plain JSON data: no sets, no objects, nothing order-dependent.
    assert json.loads(canonical) == rules_payload()


# --- API, DB-backed ----------------------------------------------------------


@pytest.fixture
def seeded():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import SessionLocal

    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush  # endpoints "commit"; nothing leaves the transaction
    try:
        alice = AppUser(email=f"assess-test-a-{uuid4()}@example.com")
        bob = AppUser(email=f"assess-test-b-{uuid4()}@example.com")
        session.add_all([alice, bob])
        session.flush()
        app.dependency_overrides[deps_module.get_db] = lambda: session
        yield {
            "client": TestClient(app, raise_server_exceptions=False),
            "alice": auth_headers(email=alice.email),
            "bob": auth_headers(email=bob.email),
        }
    finally:
        app.dependency_overrides.clear()
        session.commit = real_commit
        session.rollback()
        session.close()


def test_unauthenticated_is_401_everywhere(seeded):
    c = seeded["client"]
    assert c.post("/assessments", json=HR_TECH).status_code == 401
    assert c.get("/assessments").status_code == 401
    assert c.get(f"/assessments/{uuid4()}").status_code == 401


def test_owner_saves_lists_and_reopens(seeded):
    c, alice = seeded["client"], seeded["alice"]

    r = c.post("/assessments", json=HR_TECH, headers=alice)
    assert r.status_code == 201, r.text
    saved = r.json()
    assert saved["environment"] == "test"  # stamped from app_env(), like query_trace
    assert saved["engine_version"] == ENGINE_VERSION
    assert saved["corpus_consolidated_date"]
    assert saved["report"]["decision"]["headline"] == "HIGH_RISK"
    assert "not an immutable snapshot" in saved["known_limitation"]
    saved_id = saved["id"]

    listed = c.get("/assessments", headers=alice).json()["assessments"]
    assert [row["id"] for row in listed] == [saved_id]
    assert listed[0]["headline"] == "HIGH_RISK"
    assert listed[0]["roles"] == ["provider", "deployer"]
    assert listed[0]["high_risk_basis"] == "anx_III.pt_4.sub_a"
    assert listed[0]["engine_version"] == ENGINE_VERSION

    reopened = c.get(f"/assessments/{saved_id}", headers=alice)
    assert reopened.status_code == 200
    body = reopened.json()
    assert body["answers"]["annex_iii_point"] == "anx_III.pt_4.sub_a"
    assert body["answers"]["turnover_eur"] == 2_000_000
    # Re-rendered from the stored answers against the live corpus.
    assert body["report"]["high_risk_basis"]["citation_id"] == "anx_III.pt_4.sub_a"
    assert "recruitment" in body["report"]["high_risk_basis"]["text"]
    par4 = next(
        line
        for line in body["report"]["penalties"]["lines"]
        if line["paragraph"]["citation_id"] == "art_99.par_4"
    )
    assert par4["ceiling_eur"] == 60_000


def test_a_client_cannot_save_a_result_it_did_not_earn(seeded):
    c, alice = seeded["client"], seeded["alice"]
    tampered = {**HR_TECH, "headline": "MINIMAL", "report": {"anything": True}}
    r = c.post("/assessments", json=tampered, headers=alice)
    assert r.status_code == 201
    # Unknown fields are ignored; the stored headline is what the engine decided.
    assert r.json()["report"]["decision"]["headline"] == "HIGH_RISK"
    assert (
        c.get("/assessments", headers=alice).json()["assessments"][0]["headline"]
        == "HIGH_RISK"
    )


def test_second_user_gets_404_and_an_empty_list(seeded):
    c, alice, bob = seeded["client"], seeded["alice"], seeded["bob"]
    saved_id = c.post("/assessments", json=HR_TECH, headers=alice).json()["id"]

    foreign = c.get(f"/assessments/{saved_id}", headers=bob)
    unknown = c.get(f"/assessments/{uuid4()}", headers=bob)
    assert foreign.status_code == unknown.status_code == 404

    def strip(r):
        return {k: v for k, v in r.json()["error"].items() if k != "request_id"}

    assert strip(foreign) == strip(unknown)
    assert strip(foreign)["code"] == "assessment_not_found"
    assert c.get("/assessments", headers=bob).json()["assessments"] == []


def test_invalid_answers_are_422_and_nothing_is_saved(seeded):
    c, alice = seeded["client"], seeded["alice"]
    r = c.post("/assessments", json={**HR_TECH, "turnover_eur": -5}, headers=alice)
    assert r.status_code == 422
    assert c.get("/assessments", headers=alice).json()["assessments"] == []
