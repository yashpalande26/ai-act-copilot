"""The misgrounding probe set: does the Stage 3 verifier catch answers that
cite the wrong, an absent or an insufficient provision (true positives)
without flagging faithful answers (false positives)?

    python evals/run_verify_probes.py --model openai:gpt-4o
    python evals/run_verify_probes.py --model openai:gpt-4o-mini

Each probe is an authored answer plus the citation ids of its context; the
passages are the real chunk texts of corpus 1, fetched at run time. Reported
per kind and pooled: flagged / expected, the deterministic reference check's
own catches, tokens and latency. Nothing is generated and nothing persists.

VALIDITY: probes written by the person who wrote the verifier prompt, against
provisions they had just read (24 in Stage 3; 22 added for ADR-25: twelve
valid paraphrases, seven of them the real withheld answers from the ADR-20 and
ADR-24 runs, and ten false-accept traps). They prove the verifier can catch
the listed KINDS of misgrounding and accept the listed kinds of paraphrase,
not how often real answers misground; that is what the agentic eval's verify
outcomes measure. --repeats N runs every probe N times because gpt-4o-mini at
temperature 0 is not deterministic; an item counts as correct only if every
draw is.
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
from app.generation import verify as verify_module
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
        # The heading the retriever attaches (app.retrieval.search): the
        # chunk's parent provision, an Article or an Annex.
        heading = (
            session.get(Provision, chunk.parent_provision_id).heading
            if chunk.parent_provision_id is not None
            else None
        )
        out.append(
            FusedResult(
                result=SearchResult(
                    chunk_id=chunk.id,
                    citation_id=cid,
                    citation_label=label,
                    chunk_text=chunk.chunk_text,
                    similarity=0.5,
                    article_heading=heading,
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
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument(
        "--prompt-file",
        type=Path,
        help="A/B: replace the verifier system prompt for this run only",
    )
    ap.add_argument(
        "--no-headings",
        action="store_true",
        help="A/B: hide the Article or Annex heading from the passage blocks",
    )
    ap.add_argument(
        "--headings",
        action="store_true",
        help="A/B: show the Article or Annex heading after each passage label",
    )
    ap.add_argument("--only", help="comma-separated probe ids")
    args = ap.parse_args()
    probes = json.loads(PROBES.read_text())
    if args.only:
        only = set(args.only.split(","))
        probes = [p for p in probes if p["id"] in only]
    if args.prompt_file:
        verify_module.SYSTEM_PROMPT = args.prompt_file.read_text().strip()
    if args.no_headings:
        real_block = verify_module.passage_block

        def bare_block(index, f):
            f.result.article_heading = None
            return real_block(index, f)

        verify_module.passage_block = bare_block
    if args.headings:

        def headed_block(index, f):
            head = f"[{index}] {f.result.citation_label}"
            if f.result.article_heading:
                head += f" ({f.result.article_heading})"
            return f"{head}\n{f.result.chunk_text}"

        verify_module.passage_block = headed_block
    ex = get_extractor(args.model)
    session = SessionLocal()
    rows = []
    try:
        print(
            f"verifier model {args.model}  probes {len(probes)}  repeats {args.repeats}"
            f"  prompt {args.prompt_file.name if args.prompt_file else 'module'}"
            f"  headings {'on' if args.headings else 'off'}"
        )
        for p in probes:
            fused = load_context(session, p["context_ids"])
            det = missing_references(p["answer"], fused)
            draws = []
            for _ in range(args.repeats):
                res = verify_answer(p["answer"], fused, extractor=ex)
                draws.append(res)
            flags = [r.misgrounded for r in draws]
            flagged_n = sum(flags)
            # flagged: the majority view, kept for the per-kind counts;
            # correct: every draw agrees with the expectation.
            flagged = flagged_n * 2 > len(flags)
            ok = all(f == p["expected_misgrounded"] for f in flags)
            unsupported = [list(r.unsupported_claims) for r in draws]
            rows.append(
                {
                    "id": p["id"],
                    "kind": p["kind"],
                    "expected_misgrounded": p["expected_misgrounded"],
                    "flagged": flagged,
                    "flagged_draws": f"{flagged_n}/{len(flags)}",
                    "correct": ok,
                    "deterministic_missing": det,
                    "unsupported_claims": unsupported[0],
                    "unsupported_by_draw": unsupported,
                    "claims_checked": draws[0].claims_checked,
                    "verifier_ok": all(r.ok for r in draws),
                    "tokens": sum(
                        (r.prompt_tokens or 0) + (r.completion_tokens or 0)
                        for r in draws
                    )
                    // len(draws),
                    "latency_ms": sum(r.latency_ms for r in draws) // len(draws),
                }
            )
            print(
                f"  {p['id']} {p['kind']:<24} expect={'MIS' if p['expected_misgrounded'] else 'ok '} flagged={flagged_n}/{len(flags)}"
                f" {'PASS' if ok else 'FAIL'} det_missing={det} unsupported={len(unsupported[0])}/{draws[0].claims_checked} {rows[-1]['latency_ms']}ms"
            )
            if not ok:
                for u in unsupported:
                    if u:
                        print(f"      withheld: {u[0][:160]!r}")
                        break
        mis = [r for r in rows if r["expected_misgrounded"]]
        val = [r for r in rows if not r["expected_misgrounded"]]
        tp = sum(r["correct"] for r in mis)  # caught on every draw
        fp = sum(not r["correct"] for r in val)  # withheld on any draw
        by_kind = defaultdict(lambda: [0, 0])
        for r in rows:
            by_kind[r["kind"]][0] += r["correct"]
            by_kind[r["kind"]][1] += 1
        print("\n== PROBES ==")
        print(f"  true positives (misgrounded caught on every draw): {tp}/{len(mis)}")
        print(f"  false positives (valid withheld on any draw):      {fp}/{len(val)}")
        print(
            f"  false accepts, any draw (must be 0): {[r['id'] for r in mis if not r['correct']]}"
        )
        print(
            f"  false abstentions, any draw: {[r['id'] for r in val if not r['correct']]}"
        )
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
                        "repeats": args.repeats,
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
