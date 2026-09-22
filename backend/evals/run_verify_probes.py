"""The misgrounding probe set: does the Stage 3 verifier catch answers that
cite the wrong, an absent or an insufficient provision (true positives)
without flagging faithful answers (false positives)?

    python evals/run_verify_probes.py --model openai:gpt-4o
    python evals/run_verify_probes.py --model openai:gpt-4o-mini

Each probe is an authored answer plus the citation ids of its context; the
passages are the real chunk texts of corpus 1, fetched at run time. Reported
per kind and pooled: flagged / expected, the deterministic reference check's
own catches, tokens and latency. Nothing is generated and nothing persists.

VALIDITY: 24 probes written by the person who wrote the verifier prompt,
against provisions they had just read. They prove the verifier can catch the
listed KINDS of misgrounding, not how often real answers misground; that is
what the agentic eval's verify outcomes measure.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.models import Chunk, Provision
from app.db.session import SessionLocal
from app.extraction.llm import get_extractor
from app.generation.verify import missing_references, verify_answer
from app.retrieval.search import FusedResult, SearchResult

PROBES = Path(__file__).resolve().parent / "misgrounding_probes.json"


def load_context(session, citation_ids: list[str]) -> list[FusedResult]:
    out = []
    for cid in citation_ids:
        row = session.execute(
            select(Provision, Chunk)
            .join(Chunk, Chunk.provision_id == Provision.id)
            .where(Provision.corpus_version_id == 1, Provision.citation_id == cid)
        ).first()
        if row is None:
            raise SystemExit(f"probe context {cid} not in corpus 1")
        _prov, chunk = row
        from app.assessment.report import _Corpus

        label = _Corpus(session).node(cid, "self").citation_label
        out.append(
            FusedResult(
                result=SearchResult(
                    chunk_id=chunk.id,
                    citation_id=cid,
                    citation_label=label,
                    chunk_text=chunk.chunk_text,
                    similarity=0.5,
                    article_heading=None,
                ),
                rrf_score=0.01,
                vector_rank=0,
                lexical_rank=None,
            )
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="openai:gpt-4o")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    probes = json.loads(PROBES.read_text())
    ex = get_extractor(args.model)
    session = SessionLocal()
    rows = []
    try:
        print(f"verifier model {args.model}  probes {len(probes)}")
        for p in probes:
            fused = load_context(session, p["context_ids"])
            det = missing_references(p["answer"], fused)
            res = verify_answer(p["answer"], fused, extractor=ex)
            flagged = res.misgrounded
            ok = flagged == p["expected_misgrounded"]
            rows.append(
                {
                    "id": p["id"],
                    "kind": p["kind"],
                    "expected_misgrounded": p["expected_misgrounded"],
                    "flagged": flagged,
                    "correct": ok,
                    "deterministic_missing": det,
                    "unsupported_claims": list(res.unsupported_claims),
                    "claims_checked": res.claims_checked,
                    "verifier_ok": res.ok,
                    "tokens": (res.prompt_tokens or 0) + (res.completion_tokens or 0),
                    "latency_ms": res.latency_ms,
                }
            )
            print(
                f"  {p['id']} {p['kind']:<26} expect={'MIS' if p['expected_misgrounded'] else 'ok '} flagged={'Y' if flagged else 'n'}"
                f" {'PASS' if ok else 'FAIL'} det_missing={det} unsupported={len(res.unsupported_claims)}/{res.claims_checked} {res.latency_ms}ms"
            )
        mis = [r for r in rows if r["expected_misgrounded"]]
        val = [r for r in rows if not r["expected_misgrounded"]]
        tp = sum(r["flagged"] for r in mis)
        fp = sum(r["flagged"] for r in val)
        by_kind = defaultdict(lambda: [0, 0])
        for r in mis:
            by_kind[r["kind"]][0] += r["flagged"]
            by_kind[r["kind"]][1] += 1
        print("\n== PROBES ==")
        print(f"  true positives (misgrounded flagged): {tp}/{len(mis)}")
        print(f"  false positives (valid flagged):      {fp}/{len(val)}")
        print(
            "  by kind: "
            + "  ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(by_kind.items()))
        )
        print(
            f"  deterministic reference check alone caught: {sum(bool(r['deterministic_missing']) for r in mis)}/{len(mis)} misgrounded, flagged {sum(bool(r['deterministic_missing']) for r in val)}/{len(val)} valid"
        )
        print(
            f"  verifier failures: {sum(not r['verifier_ok'] for r in rows)}  mean tokens {sum(r['tokens'] for r in rows) // len(rows)}  mean latency {sum(r['latency_ms'] for r in rows) // len(rows)}ms"
        )
        if args.json:
            args.json.write_text(
                json.dumps(
                    {
                        "model": args.model,
                        "tp": tp,
                        "n_mis": len(mis),
                        "fp": fp,
                        "n_valid": len(val),
                        "rows": rows,
                    },
                    indent=1,
                )
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()
