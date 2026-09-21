"""The assessment wedge: engine (pure), penalties (pure + parsed from the
corpus), obligation map integrity, and the /assess API.

DB-backed parts are read-only: they load provisions and never write. No LLM
call anywhere; a test asserts the package imports nothing from generation,
embedding or OpenAI.
"""

import os
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app.assessment import obligations, penalties, questionnaire
from app.assessment.engine import ANNEX_III_POINTS, AUTHORITY_GATED, assess
from app.assessment.schema import PROHIBITED_KEYS, Answers
from app.main import app
from app.retrieval.actor import actor_for
from tests._auth import auth_headers

# --- no paid path can be reached from this package --------------------------


def test_assessment_package_imports_no_llm_or_embedding_code():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    files = list((root / "assessment").glob("*.py")) + [root / "api" / "assess.py"]
    forbidden = re.compile(
        r"openai|embed_query|generate_grounded_answer|vector_search|bm25_search"
    )
    for f in files:
        assert not forbidden.search(f.read_text()), (
            f"{f.name} references a paid or retrieval path"
        )


# --- engine ------------------------------------------------------------------


def hr_tech(**over) -> Answers:
    base = {
        "roles": ["provider", "deployer"],
        "annex_iii_point": "anx_III.pt_4.sub_a",
        "interacts_with_persons": True,
        "undertaking": True,
        "turnover_eur": 2_000_000,
        "sme_or_startup": True,
    }
    base.update(over)
    return Answers(**base)


def test_hr_tech_recruitment_is_high_risk_under_annex_iii_4a():
    d = assess(hr_tech())
    assert d.headline == "HIGH_RISK"
    assert d.high_risk_basis == "anx_III.pt_4.sub_a"
    assert d.roles == ["provider", "deployer"]
    assert d.transparency == ["art_50.par_1"]
    assert d.in_scope


@pytest.mark.parametrize("point", ANNEX_III_POINTS)
def test_every_annex_iii_point_matches_when_its_conditions_are_met(point):
    d = assess(
        Answers(
            roles=["provider"], annex_iii_point=point, acts_for_public_authority=True
        )
    )
    assert d.high_risk_basis == point
    assert d.headline == "HIGH_RISK"


@pytest.mark.parametrize("point", sorted(AUTHORITY_GATED))
def test_authority_gated_points_do_not_match_without_the_capacity(point):
    d = assess(
        Answers(
            roles=["provider"], annex_iii_point=point, acts_for_public_authority=False
        )
    )
    assert d.high_risk_basis is None
    assert d.annex_iii_note and "authorities" in d.annex_iii_note
    assert d.headline == "MINIMAL"


def test_textual_exclusions_verification_and_fraud():
    v = assess(
        Answers(
            roles=["provider"],
            annex_iii_point="anx_III.pt_1.sub_a",
            biometric_verification_only=True,
        )
    )
    f = assess(
        Answers(
            roles=["provider"],
            annex_iii_point="anx_III.pt_5.sub_b",
            fraud_detection_only=True,
        )
    )
    assert v.high_risk_basis is None and "verification" in v.annex_iii_note
    assert f.high_risk_basis is None and "fraud" in f.annex_iii_note


@pytest.mark.parametrize("key", PROHIBITED_KEYS)
def test_each_prohibited_pattern_raises_a_flag_not_a_verdict(key):
    d = assess(Answers(roles=["provider"], prohibited_patterns=[key]))
    assert d.prohibited_flags == [f"art_5.par_1.pt_{key}"]
    assert d.headline == "PROHIBITED_FLAG"


def test_unknown_prohibited_key_is_ignored():
    assert (
        assess(Answers(roles=["provider"], prohibited_patterns=["zz"])).prohibited_flags
        == []
    )


def test_headline_priority_prohibited_over_high_risk_over_transparency():
    both = hr_tech(prohibited_patterns=["f"])
    assert assess(both).headline == "PROHIBITED_FLAG"
    assert assess(hr_tech(annex_iii_point=None)).headline == "TRANSPARENCY"
    assert (
        assess(hr_tech(annex_iii_point=None, interacts_with_persons=False)).headline
        == "MINIMAL"
    )
    assert (
        assess(
            hr_tech(
                annex_iii_point=None,
                interacts_with_persons=False,
                product_safety_component=True,
            )
        ).headline
        == "HIGH_RISK_POSSIBLE"
    )


def test_article_25_reclassifies_a_deployer_as_provider_only_when_high_risk():
    d = assess(
        Answers(
            roles=["deployer"],
            annex_iii_point="anx_III.pt_4.sub_a",
            substantial_modification=True,
        )
    )
    assert d.roles == ["deployer", "provider"]
    assert d.treated_as_provider_basis == ["art_25.par_1.pt_b"]
    not_hr = assess(Answers(roles=["deployer"], substantial_modification=True))
    assert not_hr.roles == ["deployer"] and not_hr.treated_as_provider_basis == []


def test_derogation_never_changes_the_tier():
    d = assess(hr_tech(relies_on_6_3=True))
    assert d.headline == "HIGH_RISK" and d.derogation_claimed is True


def test_scope_exclusions_and_open_source():
    assert assess(hr_tech(personal_non_professional=True)).headline == "OUT_OF_SCOPE"
    assert (
        assess(Answers(roles=["provider"], open_source=True)).open_source_exempt is True
    )
    # open source does NOT exempt a high-risk or Article 50 system (art_2.par_12)
    d = assess(hr_tech(open_source=True))
    assert d.open_source_exempt is False and d.headline == "HIGH_RISK"


def test_gpai_branch():
    d = assess(
        Answers(
            roles=["provider"], gpai_provider=True, gpai_non_eu=True, gpai_systemic=True
        )
    )
    assert d.gpai == ["art_53", "art_54", "art_55"]


# --- obligation plan --------------------------------------------------------


def test_plan_for_hr_tech_provider_and_deployer():
    d = assess(hr_tech())
    plan = obligations.plan_obligations(
        d,
        fria_body=False,
        acts_for_public_authority=False,
        generates_synthetic_content=False,
    )
    keys = [g.key for g in plan.groups]
    assert keys[0] == "ai_literacy"
    assert (
        "provider_core" in keys
        and "deployer_core" in keys
        and "deployer_explanation" in keys
    )
    assert "deployer_fria" not in keys and "provider_derogation" not in keys
    assert "transparency_1" in keys
    assert plan.dates == ["art_113.pt_c"]


def test_plan_rows_agree_with_the_actor_map():
    """The obligation table must never list a provision under a role the actor
    map assigns to a different role. Unlabelled (None) provisions are allowed."""
    for spec in obligations.ALL_SPECS:
        if spec.role in ("all", "voluntary"):
            continue
        for cid in spec.ids:
            a = actor_for(cid)
            assert a in (None, spec.role), (
                f"{spec.key}: {cid} is labelled {a}, listed under {spec.role}"
            )


# --- penalties --------------------------------------------------------------

PAR3 = "... fines of up to EUR 35 000 000 or, if the offender is an undertaking, up to 7 % of its total worldwide annual turnover ..., whichever is higher."
PAR4 = "... up to EUR 15 000 000 or, if the offender is an undertaking, up to 3 % of its total worldwide annual turnover ..., whichever is higher:"
PAR5 = "... up to EUR 7 500 000 or, if the offender is an undertaking, up to 1 % of its total ..., whichever is higher."


def test_parse_ceiling():
    assert penalties.parse_ceiling(PAR3) == (35_000_000, 7.0)
    assert penalties.parse_ceiling(PAR5) == (7_500_000, 1.0)
    with pytest.raises(penalties.CeilingParseError):
        penalties.parse_ceiling("no numbers here")


def _compute(**over):
    base = {
        "par3_text": PAR3,
        "par4_text": PAR4,
        "par5_text": PAR5,
        "art5_flagged": False,
        "obligations_flagged": True,
        "undertaking": True,
        "turnover_eur": 2_000_000,
        "sme_or_startup": False,
        "smc": False,
    }
    base.update(over)
    return {c.paragraph_id: c for c in penalties.compute(**base)}


def test_large_undertaking_takes_the_higher_value():
    c = _compute(turnover_eur=1_000_000_000)
    assert c["art_99.par_4"].rule == "higher"
    assert c["art_99.par_4"].ceiling_eur == 30_000_000  # 3% of 1bn beats 15M


def test_sme_takes_the_lower_value_for_every_paragraph():
    c = _compute(sme_or_startup=True, art5_flagged=True)
    assert (
        c["art_99.par_3"].rule == "lower" and c["art_99.par_3"].ceiling_eur == 140_000
    )  # 7% of 2M
    assert c["art_99.par_4"].ceiling_eur == 60_000  # 3% of 2M
    assert c["art_99.par_5"].ceiling_eur == 20_000  # 1% of 2M
    assert c["art_99.par_3"].rule_basis == ("art_99.par_6",)


def test_smc_lower_rule_applies_to_par_4_and_5_only():
    c = _compute(smc=True, art5_flagged=True)
    assert c["art_99.par_3"].rule == "higher"  # par_6a does not reach paragraph 3
    assert c["art_99.par_3"].ceiling_eur == 35_000_000
    assert c["art_99.par_4"].rule == "lower" and c["art_99.par_4"].rule_basis == (
        "art_99.par_6a",
    )


def test_non_undertaking_and_unknown_turnover():
    c = _compute(undertaking=False)
    assert (
        c["art_99.par_4"].rule == "eur_only"
        and c["art_99.par_4"].ceiling_eur == 15_000_000
    )
    c = _compute(turnover_eur=None)
    assert c["art_99.par_4"].ceiling_eur is None


def test_zero_turnover_is_never_computed_into_a_zero_ceiling():
    # The bug: an SME with turnover 0 got min(cap, 0 % of 0) == 0 on every line.
    for sme in (True, False):
        c = _compute(turnover_eur=0, sme_or_startup=sme)
        assert all(line.ceiling_eur is None for line in c.values())
        # The statutory figures are still there for the report to show.
        assert c["art_99.par_4"].eur_cap == 15_000_000
        assert c["art_99.par_4"].pct_cap == 3.0
        assert c["art_99.par_4"].rule == ("lower" if sme else "higher")
    # A positive turnover computes exactly as before.
    assert (
        _compute(turnover_eur=1, sme_or_startup=True)["art_99.par_4"].ceiling_eur
        == 0.03
    )


def test_turnover_status_tells_missing_from_zero():
    ts = penalties.turnover_status
    assert ts(undertaking=True, turnover_eur=None) == "missing"
    assert ts(undertaking=True, turnover_eur=0) == "zero"
    assert ts(undertaking=True, turnover_eur=2_000_000) == "provided"
    assert ts(undertaking=False, turnover_eur=None) == "not_needed"


# --- corpus-backed: every referenced id exists; API end to end ---------------


@pytest.fixture
def db_session():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_every_referenced_citation_id_exists_in_the_corpus(db_session):
    from app.assessment.report import _Corpus

    corpus = _Corpus(db_session)
    wanted = (
        obligations.all_referenced_ids()
        | questionnaire.all_referenced_ids()
        | {
            "art_6.par_3",
            "art_6.par_4",
            "art_6.par_1",
            "art_6.par_1a",
            "art_6.par_1b",
            "art_2.par_12",
            "art_99.par_3",
            "art_99.par_4",
            "art_99.par_5",
            "art_99.par_7",
            "art_99.par_6",
            "art_99.par_6a",
        }
        | {f"art_5.par_1.pt_{k}" for k in PROHIBITED_KEYS}
        | set(ANNEX_III_POINTS)
    )
    missing = sorted(cid for cid in wanted if cid not in corpus.by_id)
    assert missing == [], f"referenced ids missing from corpus: {missing}"


def test_live_article_99_ceilings_parse(db_session):
    from app.assessment.report import _Corpus

    corpus = _Corpus(db_session)
    assert penalties.parse_ceiling(corpus.text("art_99.par_3")) == (35_000_000, 7.0)
    assert penalties.parse_ceiling(corpus.text("art_99.par_4")) == (15_000_000, 3.0)
    assert penalties.parse_ceiling(corpus.text("art_99.par_5")) == (7_500_000, 1.0)


def test_assess_api_hr_tech_report(db_session):
    from app.api import deps as deps_module

    app.dependency_overrides[deps_module.get_db] = lambda: db_session
    try:
        c = TestClient(app, raise_server_exceptions=False)
        assert c.post("/assess", json=hr_tech().model_dump()).status_code == 401  # gate

        r = c.post("/assess", json=hr_tech().model_dump(), headers=auth_headers())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision"]["headline"] == "HIGH_RISK"
        assert body["headline_text"].startswith("Based on your answers")
        assert body["high_risk_basis"]["citation_id"] == "anx_III.pt_4.sub_a"
        assert "recruitment" in body["high_risk_basis"]["text"]
        keys = [g["key"] for g in body["obligations"]]
        assert "provider_core" in keys and "deployer_core" in keys
        core = next(g for g in body["obligations"] if g["key"] == "provider_core")
        art16 = core["provisions"][0]
        assert art16["citation_id"] == "art_16"
        assert [ch["citation_id"] for ch in art16["children"]][:2] == [
            "art_16.pt_a",
            "art_16.pt_b",
        ]
        assert core["applies_from"]["citation_id"] == "art_113.pt_c"
        assert "2 December 2027" in core["applies_from"]["text"]
        # penalties: SME with EUR 2M turnover, computed from the quoted text
        par4 = next(
            line
            for line in body["penalties"]["lines"]
            if line["paragraph"]["citation_id"] == "art_99.par_4"
        )
        assert par4["rule"] == "lower" and par4["ceiling_eur"] == 60_000
        assert par4["rule_basis"][0]["citation_id"] == "art_99.par_6"
        assert "not legal advice" in " ".join(body["commentary"])

        q = c.get("/assess/questionnaire", headers=auth_headers())
        assert q.status_code == 200
        steps = {s["key"]: s for s in q.json()["steps"]}
        annex = next(
            qq
            for qq in steps["high_risk"]["questions"]
            if qq["id"] == "annex_iii_point"
        )
        assert len(annex["options"]) == len(ANNEX_III_POINTS) + 1
        assert annex["options"][1]["basis"]["text"]
    finally:
        app.dependency_overrides.clear()
