"""PROTOTYPE: the Act navigator. Read-only against the real corpus; no LLM."""

import os

import pytest
from fastapi.testclient import TestClient

from app.api import deps as deps_module
from app.api.act import _refs_in, _term_of
from app.main import app
from tests._auth import auth_headers


def test_term_extraction_and_reference_parsing_are_deterministic():
    assert _term_of("‘provider’ means a natural or legal person") == "provider"
    assert _term_of("'AI system' means a machine-based system") == "AI system"
    assert _term_of("The following AI practices shall be prohibited:") is None
    refs = _refs_in(
        "in accordance with Article 6(2) and Annex III, and Articles 16 to 21"
    )
    assert {"art_6", "anx_III", "art_16", "art_21"} <= refs


@pytest.fixture
def client():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        app.dependency_overrides[deps_module.get_db] = lambda: session
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        session.rollback()
        session.close()


def test_definitions_are_verbatim_article_3_and_searchable(client):
    assert client.get("/act/definitions").status_code == 401
    r = client.get("/act/definitions", headers=auth_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 60 and body["corpus_consolidated_date"]
    by_term = {d["term"].lower(): d for d in body["definitions"]}
    assert by_term["provider"]["citation_id"] == "art_3.pt_3"
    assert by_term["deployer"]["text"].startswith("‘deployer’ means")
    q = client.get("/act/definitions?q=deep fake", headers=auth_headers()).json()
    assert q["total"] >= 1 and any(
        d["citation_id"] == "art_3.pt_60" for d in q["definitions"]
    )
    assert "—" not in r.text


def test_provision_view_has_text_children_and_text_derived_references(client):
    r = client.get("/act/provisions/art_6", headers=auth_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provision"]["citation_id"] == "art_6"
    assert any(c["citation_id"] == "art_6.par_2" for c in body["provision"]["children"])
    refs = {x["citation_id"] for x in body["references"]}
    assert "anx_III" in refs  # Article 6(2) points at Annex III in its own words
    back = {x["citation_id"] for x in body["referenced_by"]}
    assert back and all(not c.startswith("art_6.") and c != "art_6" for c in back)
    assert all(x["snippet"] for x in body["references"] + body["referenced_by"])
    # A sub-provision carries its parent.
    sub = client.get("/act/provisions/art_16.pt_b", headers=auth_headers()).json()
    assert sub["parent"]["citation_id"] == "art_16"
    assert (
        client.get("/act/provisions/art_999", headers=auth_headers()).status_code == 404
    )
