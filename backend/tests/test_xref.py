"""Cross-reference expansion: the structure map, the reference parser, the
resolver's chapter disambiguation, the capped selection, the pure insertion
that never floods the top five, and the flag. Zero paid calls; a DB test
checks the map's articles exist in the corpus and a source test regenerates
the map from the cached HTML when it is present."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import config
from app.generation import answer as answer_module
from app.retrieval import structure, xref
from app.retrieval.search import FusedResult, SearchResult
from app.retrieval.xref import (
    MAX_XREF_CHUNKS,
    XREF_POSITION,
    Reference,
    apply_xref_expansion,
    pointed_references_in,
    references_in,
    resolve_references,
    select_chunks,
)

ROOT = Path(__file__).resolve().parents[1]


def _sr(chunk_id, cid, text=""):
    return SearchResult(
        chunk_id=chunk_id,
        citation_id=cid,
        citation_label=cid,
        chunk_text=text,
        similarity=0.5,
        article_heading=None,
    )


def _fr(chunk_id, cid="art_1", text=""):
    return FusedResult(
        result=_sr(chunk_id, cid, text),
        rrf_score=0.01,
        vector_rank=0,
        lexical_rank=None,
    )


# --- structure map ---------------------------------------------------------------


def test_structure_map_matches_the_act():
    assert structure.section_articles("III", "2") == [f"art_{n}" for n in range(8, 16)]
    assert structure.chapter_section_heads("III") == [
        "art_6",
        "art_8",
        "art_16",
        "art_28",
        "art_40",
    ]
    assert structure.chapter_section_heads("XII") == ["art_99", "art_100", "art_101"]
    assert structure.location_of("art_16") == ("III", "3")
    assert structure.location_of("art_99") == ("XII", None)
    assert structure.location_of("art_999") is None
    assert structure.chapters_with_section("2") == ["III", "V", "VII", "IX"]
    assert structure.is_annex("anx_III") and not structure.is_annex("anx_XX")
    data = structure.load_structure()
    articles = [a for c in data["chapters"] for a in c["articles"]]
    assert len(articles) == 119 == len(set(articles))


def test_structure_map_regenerates_from_the_cached_source():
    html = ROOT / "data" / "aiact_02024R1689-20260727.html"
    if not html.exists():
        pytest.skip("cached source HTML not present")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_structure", ROOT / "scripts" / "build_structure.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.build(html) == json.loads(structure.STRUCTURE_PATH.read_text())


# --- parsing ---------------------------------------------------------------------


def test_references_in_parses_containers_articles_and_ranges():
    assert references_in("the requirements set out in Section 2?") == [
        Reference("section", "2")
    ]
    assert references_in("Section 3 of Chapter III") == [
        Reference("section", "3", "III"),
        Reference("chapter", "III"),
    ]
    refs = references_in("Articles 9 to 15 and Article 16(a), Annex III")
    assert [r.number for r in refs if r.kind == "article"] == [
        str(n) for n in range(9, 17)
    ]
    assert Reference("annex", "III") in refs
    assert references_in("Articles 53 and 54") == [
        Reference("article", "53"),
        Reference("article", "54"),
    ]
    assert references_in("nothing here") == []


def test_pointed_references_need_a_pointer_phrase():
    text = "compliant with the requirements set out in Section 2; see also Article 48 for the marking."
    assert pointed_references_in(text) == [Reference("section", "2")]
    assert pointed_references_in("Article 48 applies.") == []


# --- resolution ------------------------------------------------------------------


def test_bare_section_takes_the_chapter_of_the_passage_that_mentions_it():
    top = [
        _sr(1, "art_16.pt_a", "compliant with the requirements set out in Section 2;")
    ]
    res = resolve_references("what are the requirements set out in Section 2?", top)
    assert res.from_query == tuple(f"art_{n}" for n in range(8, 16))


def test_bare_section_is_settled_by_the_top_mentioning_passage():
    # the top mentioning passage names the chapter explicitly (Article 3(20) style)
    top = [
        _sr(1, "art_3.pt_20", "requirements set out in Section 2 of Chapter III"),
        _sr(2, "art_75.par_1", "Section 2 applies"),  # Chapter IX, lower ranked
    ]
    assert resolve_references("what is in Section 2?", top).from_query == tuple(
        f"art_{n}" for n in range(8, 16)
    )
    # otherwise the top mentioning passage's own chapter
    top = [
        _sr(1, "art_75.par_1", "Section 2 applies"),
        _sr(2, "art_16.pt_a", "set out in Section 2"),
    ]
    assert resolve_references("what is in Section 2?", top).from_query == ("art_73",)


def test_bare_section_with_no_settling_passage_is_dropped():
    # Section 2 exists in four chapters; nothing retrieved mentions it
    res = resolve_references(
        "what is in Section 2?", [_sr(1, "art_5.par_1", "no pointer")]
    )
    assert res.from_query == () and res.from_pointers == ()
    # every section number in this Act exists in more than one chapter, so a
    # bare one never resolves without a settling passage; a chapter settles it
    assert resolve_references("what is in Section 5?", []).from_query == ()
    # the section resolves through its named chapter; the chapter reference
    # itself also expands (to its section heads), after the section
    res = resolve_references("what is in Section 5 of Chapter III?", [])
    assert res.from_query[:10] == tuple(f"art_{n}" for n in range(40, 50))
    assert res.from_query[10:] == ("art_6", "art_8", "art_16", "art_28")


def test_chapter_expands_to_its_section_heads_and_article_to_itself():
    assert resolve_references("what does Chapter III require?", []).from_query == (
        "art_6",
        "art_8",
        "art_16",
        "art_28",
        "art_40",
    )
    assert resolve_references(
        "the obligations referred to in Article 16", []
    ).from_query == ("art_16",)
    assert resolve_references("Annex III systems", []).from_query == ("anx_III",)
    assert resolve_references("Article 999 says", []).from_query == ()


def test_chunk_pointers_resolve_separately_and_never_a_passages_own_article():
    top = [
        _sr(
            1,
            "art_12.par_1",
            "logging capabilities referred to in Article 19 and Article 12",
        ),
        _sr(2, "art_9.par_1", "shall comply with Article 9"),
    ]
    res = resolve_references("what logging is required?", top)
    assert res.from_query == () and res.from_pointers == ("art_19",)


def test_pointer_sources_are_capped_to_the_top_passages():
    top = [
        _sr(i, f"art_{50 + i}.par_1", f"pursuant to Article {60 + i}")
        for i in range(1, 9)
    ]
    res = resolve_references("see Article 5", top)
    assert res.from_query == ("art_5",)
    assert len(res.from_pointers) == xref.XREF_SOURCE_CHUNKS


# --- selection and insertion -------------------------------------------------------


def test_select_chunks_one_per_target_first_then_round_robin_up_to_cap():
    by_root = {
        "art_9": [
            _sr(91, "art_9.par_1"),
            _sr(92, "art_9.par_2"),
            _sr(93, "art_9.par_3"),
        ],
        "art_10": [_sr(101, "art_10.par_1"), _sr(102, "art_10.par_2")],
        "art_11": [_sr(111, "art_11.par_1")],
    }
    chosen = [r.chunk_id for r in select_chunks(by_root, present=set(), cap=4)]
    assert chosen == [91, 101, 111, 92]
    # already-present chunks are skipped, not re-added
    chosen = [r.chunk_id for r in select_chunks(by_root, present={91, 101}, cap=10)]
    assert chosen == [92, 102, 111, 93]
    assert len(select_chunks(by_root, present=set(), cap=MAX_XREF_CHUNKS)) == 6


def test_apply_xref_expansion_inserts_after_the_top_five_and_never_moves_a_pool_chunk():
    pool = [_fr(i, f"art_{i}") for i in range(1, 11)]
    extra = [_sr(100, "art_9.par_1"), _sr(3, "art_3"), _sr(101, "art_10.par_1")]
    fused, added = apply_xref_expansion(pool, extra)
    ids = [f.result.chunk_id for f in fused]
    assert added == 2
    assert ids[:XREF_POSITION] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]  # top five and the anchor slot untouched
    assert ids[XREF_POSITION : XREF_POSITION + 2] == [100, 101]
    assert ids.count(3) == 1
    assert (
        fused[XREF_POSITION].rrf_score == 0.0
        and fused[XREF_POSITION].vector_rank is None
    )
    assert apply_xref_expansion(pool, []) == (pool, 0)


# --- shared retriever ---------------------------------------------------------------


def _ranked(monkeypatch, *, flag, query, pool, fetched):
    monkeypatch.setenv("XREF_EXPANSION", "1" if flag else "0")
    calls = []

    def fake_fetch(session, cv, roots):
        calls.append(roots)
        return {r: fetched.get(r, []) for r in roots}

    monkeypatch.setattr(answer_module, "fetch_provision_chunks", fake_fetch)
    fused, cfg = answer_module._rank_candidates(
        pool,
        [],
        "hybrid_bm25",
        query,
        dense_anchor_floor=None,
        final_context_size=15,
        session=MagicMock(),
        corpus_version_id=1,
    )
    return fused, cfg, calls


def test_shared_retriever_expands_one_hop_only_when_a_reference_is_present(monkeypatch):
    pool = [
        _fr(1, "art_16.pt_a", "compliant with the requirements set out in Section 2;"),
        _fr(2, "art_16.pt_b"),
    ]
    fetched = {
        f"art_{n}": [_sr(n * 10, f"art_{n}.par_1", "pursuant to Article 99")]
        for n in range(8, 16)
    }
    fused, cfg, calls = _ranked(
        monkeypatch,
        flag=True,
        query="what are the requirements set out in Section 2?",
        pool=pool,
        fetched=fetched,
    )
    assert calls == [
        [f"art_{n}" for n in range(8, 16)]
    ]  # one hop: fetched once, no second resolution
    ids = [f.result.citation_id for f in fused]
    assert ids[:2] == ["art_16.pt_a", "art_16.pt_b"] and set(ids[2:]) == {
        f"art_{n}.par_1" for n in range(8, 16)
    }
    assert cfg == "hybrid_bm25|actor=none|xref=8"
    # no reference: nothing fetched, nothing changed
    _fused2, cfg2, calls2 = _ranked(
        monkeypatch,
        flag=True,
        query="what must providers do?",
        pool=[_fr(1, "art_16.pt_a")],
        fetched=fetched,
    )
    assert calls2 == [] and cfg2 == "hybrid_bm25|actor=provider|factor=0.25"


def test_shared_retriever_is_untouched_when_the_flag_is_off(monkeypatch):
    pool = [_fr(1, "art_16.pt_a", "set out in Section 2;")]
    fused, cfg, calls = _ranked(
        monkeypatch,
        flag=False,
        query="what are the requirements set out in Section 2?",
        pool=pool,
        fetched={},
    )
    assert calls == [] and "xref" not in cfg and fused == pool
    monkeypatch.delenv("XREF_EXPANSION", raising=False)
    assert config.xref_expansion_enabled() is (config.XREF_EXPANSION_DEFAULT == "1")


def test_pointer_regime_is_off_by_default_and_tail_placed_when_enabled(monkeypatch):
    pool = [
        _fr(i, f"art_{i}", "in accordance with Article 48" if i == 1 else "")
        for i in range(1, 16)
    ]
    fetched = {
        "art_48": [
            _sr(481, "art_48.par_1"),
            _sr(482, "art_48.par_2"),
            _sr(483, "art_48.par_3"),
        ]
    }
    # default: a passage pointer adds nothing
    assert answer_module.XREF_POINTER_CHUNKS == 0
    fused, cfg, calls = _ranked(
        monkeypatch,
        flag=True,
        query="what must providers do?",
        pool=pool,
        fetched=fetched,
    )
    assert calls == [["art_48"]] and "xref" not in cfg and fused == pool
    # enabled at two: two chunks at the tail of the slice, first thirteen untouched
    monkeypatch.setattr(answer_module, "XREF_POINTER_CHUNKS", 2)
    fused, cfg, calls = _ranked(
        monkeypatch,
        flag=True,
        query="what must providers do?",
        pool=pool,
        fetched=fetched,
    )
    ids = [f.result.chunk_id for f in fused]
    assert ids[:13] == list(range(1, 14)) and ids[13:15] == [481, 482]
    assert cfg.endswith("|xref=ptr:2")
    # a query reference wins and pointers are ignored
    _fused2, cfg2, calls2 = _ranked(
        monkeypatch,
        flag=True,
        query="see Article 5",
        pool=pool,
        fetched={**fetched, "art_5": [_sr(51, "art_5.par_1")]},
    )
    assert calls2 == [["art_5"]] and cfg2.endswith("|xref=1")


def test_cap_holds_in_the_shared_retriever(monkeypatch):
    pool = [_fr(1, "art_1")]
    fetched = {
        f"art_{n}": [_sr(n * 100 + k, f"art_{n}.par_{k}") for k in range(1, 6)]
        for n in range(6, 16)
    }
    fused, cfg, _ = _ranked(
        monkeypatch,
        flag=True,
        query="what does Chapter III require and Articles 9 to 15?",
        pool=pool,
        fetched=fetched,
    )
    assert len(fused) == 1 + MAX_XREF_CHUNKS and cfg.endswith(
        f"|xref={MAX_XREF_CHUNKS}"
    )


# --- corpus ------------------------------------------------------------------------


def test_every_article_in_the_map_exists_in_the_corpus():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from sqlalchemy import select

    from app.db.models import CorpusVersion, Provision
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        have = set(
            session.execute(
                select(Provision.citation_id).where(
                    Provision.corpus_version_id == cv.id,
                    Provision.unit_type == "article",
                )
            ).scalars()
        )
        wanted = {
            a for c in structure.load_structure()["chapters"] for a in c["articles"]
        }
        assert wanted == have
    finally:
        session.close()
