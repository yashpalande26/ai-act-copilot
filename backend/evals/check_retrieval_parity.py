"""Parity check for the egress fix: retrieval and the /act and /assess
responses must be byte-identical before and after a change. No LLM.

    python evals/check_retrieval_parity.py --record data/parity/before.json
    python evals/check_retrieval_parity.py --compare data/parity/before.json

--record runs on the unchanged code. It makes ONE OpenAI embedding call per
distinct query string and stores the vectors in the snapshot (with
--reuse-embeddings OLD.json it takes the vectors from an earlier snapshot and
makes none). --compare replays those vectors through
app.retrieval.search.embed_query and makes no API call at all (every OpenAI
client getter is replaced by one that raises). Both passes therefore retrieve
from the same vectors, which removes embedding nondeterminism.

What is snapshotted:
  retrieval  retrieve_step at breadth 25 and 50 (the grader's widen) for every
             question in the golden, agentic and broad sets, with AGENTIC_RAG,
             RECITAL_MAP and XREF_EXPANSION on so the recital-map and xref
             paths (fetch_provision_chunks) run; the dual path for every
             follow-up that stores both the raw follow-up and its standalone
             rewrite (followup_set.json); and vector_search, bm25_search
             (exclude_recitals off and on) and fetch_provision_chunks called
             directly. Every SearchResult field is recorded.
  api        GET /act/definitions (q empty and a few filters), GET
             /act/provisions/{cid} for every citation_id, GET
             /assess/questionnaire, POST /assess for the answer fixtures of
             tests/test_assessment.py (generated_at dropped: it is the clock),
             and the /assess/extract system prompt and its version (built
             from the corpus; the paid extraction call itself is not made).
             Each request gets its own session, closed afterwards, as
             production's get_db does, and the whole API section runs twice
             in one process (cold, then warm): a process cache must give the
             warm pass exactly the cold pass's answers.

What it cannot see (invariant 2): real production queries, LLM-generated
query strings (rewrite, understanding, decomposition), and the LLM nodes. The
local DB holds one corpus_version, so a cache keyed or invalidated wrongly
across versions is invisible here (unit tests cover that). Every chunk in
this corpus has a parent with a heading, so article_heading None never occurs
(a unit test covers it). For a column-projection or caching change the rows
are unchanged by construction; this replay checks that argument, it does not
replace it.

Refuses to run unless the DATABASE_URL host is localhost or 127.0.0.1.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

LOCAL_HOSTS = {"localhost", "127.0.0.1"}
BREADTHS = (25, 50)
FIXED_SECRET = "parity-check-local-only-not-a-real-secret"  # in-process signing

# Answer fixtures from tests/test_assessment.py, copied as literals.
HR_TECH = {
    "roles": ["provider", "deployer"],
    "annex_iii_point": "anx_III.pt_4.sub_a",
    "interacts_with_persons": True,
    "undertaking": True,
    "turnover_eur": 2_000_000,
    "sme_or_startup": True,
}
ANSWER_FIXTURES = {
    "hr_tech": HR_TECH,
    "hr_tech_no_annex": {**HR_TECH, "annex_iii_point": None},
    "hr_tech_minimal": {
        **HR_TECH,
        "annex_iii_point": None,
        "interacts_with_persons": False,
    },
    "hr_tech_prohibited_f": {**HR_TECH, "prohibited_patterns": ["f"]},
    "hr_tech_relies_6_3": {**HR_TECH, "relies_on_6_3": True},
    "hr_tech_personal": {**HR_TECH, "personal_non_professional": True},
    "hr_tech_open_source": {**HR_TECH, "open_source": True},
    "hr_tech_no_turnover": {**HR_TECH, "turnover_eur": None},
    "deployer_substantial_mod": {
        "roles": ["deployer"],
        "substantial_modification": True,
    },
    "provider_open_source": {"roles": ["provider"], "open_source": True},
}
DEFINITION_QUERIES = ("", "provider", "deep fake", "biometric", "zzzz-no-match")


def _guard_local() -> None:
    url = os.environ.get("DATABASE_URL")
    host = make_url(url).host if url else None
    print(f"DATABASE_URL host: {host}")
    if host not in LOCAL_HOSTS:
        sys.exit("refusing: DATABASE_URL host is not localhost/127.0.0.1")


def _questions() -> tuple[list[str], list[tuple[str, str]]]:
    """(single questions, (raw follow-up, standalone rewrite) pairs), each
    deduplicated in first-seen order."""
    singles: list[str] = []
    for name in (
        "golden_set.yaml",
        "golden_set_hard.yaml",
        "golden_set_realistic.yaml",
        "agentic_set.json",
        "broad_set.json",
    ):
        singles += [item["question"] for item in json.loads((HERE / name).read_text())]
    pairs = [
        (item["followup"], item["gold_standalone"])
        for item in json.loads((HERE / "followup_set.json").read_text())
        if item.get("gold_standalone")
    ]
    return list(dict.fromkeys(singles)), list(dict.fromkeys(pairs))


def _sr(r) -> dict:
    return r.model_dump()


def _fr(f) -> dict:
    return {
        "result": _sr(f.result),
        "rrf_score": f.rrf_score,
        "vector_rank": f.vector_rank,
        "lexical_rank": f.lexical_rank,
    }


def _step(step) -> dict:
    return {
        "all_fused": [_fr(f) for f in step.all_fused],
        "fused_len": len(step.fused),
        "retrieval_config": step.retrieval_config,
    }


def _install_embeddings(
    vectors: dict[str, list[float]], allow_calls: bool
) -> list[int]:
    """Route every query embedding through `vectors`. When calls are allowed
    a miss makes the one real call for that string; otherwise a miss is an
    error and every OpenAI client getter is disabled. Returns a one-element
    counter of real calls made."""
    from app.generation import answer
    from app.ingestion import embedder
    from app.retrieval import search

    real = search.embed_query
    calls = [0]

    def replay(text: str) -> list[float]:
        if text not in vectors:
            if not allow_calls:
                raise KeyError(f"no recorded embedding for query {text!r}")
            vectors[text] = real(text)
            calls[0] += 1
        return vectors[text]

    search.embed_query = replay
    if not allow_calls:

        def no_client():
            raise RuntimeError("this run must make no OpenAI call")

        embedder._get_client = no_client
        search._get_client = no_client
        answer._get_client = no_client
    return calls


def snapshot_retrieval(session, version_id: int) -> dict:
    from app.generation.answer import retrieve_step
    from app.retrieval.search import (
        bm25_search,
        fetch_provision_chunks,
        vector_search,
    )

    singles, pairs = _questions()
    out: dict = {"single": {}, "dual": {}, "legs": {}, "provision_chunks": {}}
    for q in singles:
        out["single"][q] = {
            str(b): _step(retrieve_step(session, q, version_id, breadth=b))
            for b in BREADTHS
        }
        out["legs"][q] = {
            f"{leg}|exclude_recitals={ex}": [
                _sr(r)
                for r in fn(session, q, version_id, top_k=25, exclude_recitals=ex)
            ]
            for leg, fn in (("vector", vector_search), ("bm25", bm25_search))
            for ex in (False, True)
        }
    for raw, rewritten in pairs:
        out["dual"][f"{raw} || {rewritten}"] = {
            str(b): _step(
                retrieve_step(session, rewritten, version_id, raw_query=raw, breadth=b)
            )
            for b in BREADTHS
        }

    # Every top-level provision root, in batches, through the xref/recital
    # fetch called directly.
    from sqlalchemy import select

    from app.db.models import Provision

    cids = session.execute(
        select(Provision.citation_id).where(Provision.corpus_version_id == version_id)
    ).scalars()
    roots = sorted({c.split(".")[0] for c in cids})
    for i in range(0, len(roots), 10):
        batch = roots[i : i + 10]
        got = fetch_provision_chunks(session, version_id, batch)
        for root, rows in got.items():
            out["provision_chunks"][root] = [_sr(r) for r in rows]
    return out


def snapshot_api() -> dict:
    import jwt
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.api import deps as deps_module
    from app.assessment.report import _Corpus
    from app.config import SERVICE_TOKEN_ALGORITHM
    from app.db.models import CorpusVersion, Provision
    from app.db.session import SessionLocal
    from app.extraction.extraction import build_system_prompt, prompt_version
    from app.main import app
    from app.rate_limit import limiter

    os.environ["INTERNAL_API_SECRET"] = FIXED_SECRET
    limiter.enabled = False

    def per_request_session():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[deps_module.get_db] = per_request_session

    def headers() -> dict:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "parity",
                "email": "parity@example.com",
                "iat": now,
                "exp": now + timedelta(seconds=60),
            },
            FIXED_SECRET,
            algorithm=SERVICE_TOKEN_ALGORITHM,
        )
        return {"Authorization": f"Bearer {token}"}

    client = TestClient(app, raise_server_exceptions=True)

    def get(path: str, **kw) -> dict:
        r = client.get(path, headers=headers(), **kw)
        body = r.json()
        if isinstance(body.get("error"), dict):
            body["error"].pop("request_id", None)  # random per request
        return {"status": r.status_code, "body": body}

    with SessionLocal() as session:
        version_id = session.execute(
            select(CorpusVersion.id).order_by(CorpusVersion.id.desc())
        ).scalar()
        cids = (
            session.execute(
                select(Provision.citation_id)
                .where(Provision.corpus_version_id == version_id)
                .order_by(Provision.id)
            )
            .scalars()
            .all()
        )

    out: dict = {"definitions": {}, "provisions": {}, "assess": {}}
    for q in DEFINITION_QUERIES:
        out["definitions"][q] = get("/act/definitions", params={"q": q})
    for cid in cids:
        out["provisions"][cid] = get(f"/act/provisions/{cid}")
    out["provisions"]["__missing__"] = get("/act/provisions/art_99999")
    out["questionnaire"] = get("/assess/questionnaire")
    for name, answers in ANSWER_FIXTURES.items():
        r = client.post("/assess", json=answers, headers=headers())
        body = r.json()
        body.pop("generated_at", None)
        out["assess"][name] = {"status": r.status_code, "body": body}
    with SessionLocal() as session:
        corpus = _Corpus(session)
        prompt = build_system_prompt(lambda cid: corpus.node(cid, "self"))
    out["extract_prompt"] = {"prompt": prompt, "version": prompt_version(prompt)}

    app.dependency_overrides.clear()
    return out


def _diff(a, b, path: str = "") -> list[str]:
    """Paths where two JSON values differ, exact comparison (floats by ==)."""
    if type(a) is not type(b):
        return [f"{path}: type {type(a).__name__} != {type(b).__name__}"]
    if isinstance(a, dict):
        out = [f"{path}/{k}: missing after" for k in a.keys() - b.keys()]
        out += [f"{path}/{k}: new after" for k in b.keys() - a.keys()]
        for k in a.keys() & b.keys():
            out += _diff(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [
            d for i, (x, y) in enumerate(zip(a, b)) for d in _diff(x, y, f"{path}[{i}]")
        ]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", type=Path, metavar="OUT.json")
    mode.add_argument("--compare", type=Path, metavar="SNAPSHOT.json")
    parser.add_argument(
        "--reuse-embeddings",
        type=Path,
        metavar="OLD.json",
        help="with --record: take the vectors from an earlier snapshot, no calls",
    )
    args = parser.parse_args()

    _guard_local()
    # Production retrieval paths, set before any flag is read: the graph flag
    # gates the recital map; xref is on by default but pinned here too.
    os.environ.update({"AGENTIC_RAG": "1", "RECITAL_MAP": "1", "XREF_EXPANSION": "1"})

    from sqlalchemy import select

    from app.db.models import CorpusVersion
    from app.db.session import SessionLocal

    before = None if args.record else json.loads(args.compare.read_text())
    if args.compare:
        vectors: dict[str, list[float]] = before["embeddings"]
    elif args.reuse_embeddings:
        vectors = json.loads(args.reuse_embeddings.read_text())["embeddings"]
    else:
        vectors = {}
    allow_calls = bool(args.record) and not args.reuse_embeddings
    calls = _install_embeddings(vectors, allow_calls=allow_calls)

    session = SessionLocal()
    try:
        version_id = session.execute(
            select(CorpusVersion.id).order_by(CorpusVersion.id.desc())
        ).scalar()
        snap = {
            "corpus_version_id": version_id,
            "retrieval": snapshot_retrieval(session, version_id),
        }
    finally:
        session.rollback()
        session.close()
    snap["api"] = snapshot_api()
    warm = snapshot_api()
    warm_diffs = _diff(snap["api"], warm, "api(cold vs warm)")
    print(f"api cold vs warm: {'EXACT MATCH' if not warm_diffs else 'DIFFS'}")
    for d in warm_diffs[:20]:
        print(f"  {d}")
    if warm_diffs:
        sys.exit(1)

    r = snap["retrieval"]
    print(
        f"corpus_version {version_id}: {len(r['single'])} single questions, "
        f"{len(r['dual'])} dual pairs, x{len(BREADTHS)} breadths; "
        f"{len(r['provision_chunks'])} provision roots; "
        f"{len(snap['api']['provisions'])} provision views, "
        f"{len(snap['api']['assess'])} reports"
    )
    print(f"OpenAI embedding calls made: {calls[0]}")

    if args.record:
        snap["embeddings"] = vectors
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(snap, sort_keys=True))
        print(f"recorded -> {args.record}")
        return

    failed = False
    for section in ("corpus_version_id", "retrieval", "api"):
        diffs = _diff(before[section], snap[section], section)
        print(f"{section}: {'EXACT MATCH' if not diffs else f'{len(diffs)} DIFFS'}")
        for d in diffs[:20]:
            print(f"  {d}")
        failed |= bool(diffs)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
