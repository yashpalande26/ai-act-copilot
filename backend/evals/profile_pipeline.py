"""Latency and cost profile of the grounded-answer pipeline, per turn type and
per node, on the agentic golden set. No judge, nothing persists.

    python evals/profile_pipeline.py --json evals/runs/profile_stage0.json          # AGENTIC_RAG=0
    AGENTIC_RAG=1 python evals/profile_pipeline.py --json evals/runs/profile_full.json
    python evals/profile_pipeline.py --compare evals/runs/profile_stage0.json evals/runs/profile_full.json

Every paid call is attributed to the node that made it by wrapping the node's
own function (rewrite_followup, plan_decomposition, grade_context,
verify_answer, generate_step) and the embeddings call inside retrieval. Token
counts are the ones the API returned (usage); latency is wall time around
each call. Dollar figures multiply those measured tokens by the LIST prices in
PRICES, which are the only estimate here: correct them there if they change.

Turn types are the golden set's buckets: single_hop (simple), multi_turn
(follow-up), unanswerable (off-topic and in-domain ungrounded), multi_hop
(compositional). Per bucket: p50 and p95 turn latency, mean tokens by model,
mean cost, and each node's mean added latency and cost.
"""

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app import config
from app.db.models import AppUser, ChatSession, CorpusVersion, Message
from app.db.session import SessionLocal
from app.generation import answer as answer_module
from app.generation import graph as graph_module
from app.generation.answer import generate_grounded_answer, is_abstention
from app.retrieval import search as search_module

HERE = Path(__file__).resolve().parent
SET_PATH = HERE / "agentic_set.json"
BUCKETS = ("single_hop", "multi_turn", "unanswerable", "multi_hop")
NODES = ("rewrite", "plan", "retrieve", "grade", "generate", "verify")

# USD per 1M tokens, OpenAI list prices as recorded on 22 Sep 2026 (the
# gpt-4o figures are the ones config.py already uses). Input / output.
PRICES = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "text-embedding-3-large": (0.13, 0.0),
}


def cost(model: str, prompt: int, completion: int) -> float:
    pin, pout = PRICES[model]
    return (prompt * pin + completion * pout) / 1_000_000


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class Recorder:
    """Per-turn ledger of calls: node -> list of (model, prompt, completion, ms)."""

    def __init__(self):
        self.calls: dict[str, list[tuple[str, int, int, int]]] = defaultdict(list)

    def add(self, node, model, prompt, completion, ms):
        self.calls[node].append((model, prompt or 0, completion or 0, ms))

    def reset(self):
        self.calls = defaultdict(list)

    def summary(self) -> dict:
        out = {}
        for node in NODES:
            rows = self.calls.get(node, [])
            out[node] = {
                "calls": len(rows),
                "ms": sum(r[3] for r in rows),
                "tokens": sum(r[1] + r[2] for r in rows),
                "usd": sum(cost(r[0], r[1], r[2]) for r in rows),
            }
        by_model = defaultdict(lambda: [0, 0, 0])
        for rows in self.calls.values():
            for model, p, c, _ in rows:
                by_model[model][0] += p
                by_model[model][1] += c
                by_model[model][2] += 1
        out["by_model"] = {
            m: {"prompt": v[0], "completion": v[1], "calls": v[2]}
            for m, v in by_model.items()
        }
        out["usd"] = sum(n["usd"] for k, n in out.items() if k in NODES)
        return out


def install(rec: Recorder):
    """Wrap the node functions and the embeddings client. Returns the undo."""
    originals = {}

    def timed(node, model_of, target_module, name, tokens_of):
        original = getattr(target_module, name)
        originals[(target_module, name)] = original

        def wrapper(*a, **kw):
            t0 = time.monotonic()
            res = original(*a, **kw)
            ms = int((time.monotonic() - t0) * 1000)
            p, c = tokens_of(res)
            rec.add(node, model_of(res), p, c, ms)
            return res

        setattr(target_module, name, wrapper)

    def mini(_res):
        return "gpt-4o-mini"

    timed(
        "rewrite",
        lambda r: (r.model or "openai:gpt-4o-mini").split(":")[-1],
        graph_module,
        "rewrite_followup",
        lambda r: (r.prompt_tokens, r.completion_tokens),
    )
    timed(
        "plan",
        lambda r: (r.model or "openai:gpt-4o-mini").split(":")[-1],
        graph_module,
        "plan_decomposition",
        lambda r: (r.prompt_tokens, r.completion_tokens),
    )
    timed(
        "grade",
        lambda r: (r.model or "openai:gpt-4o-mini").split(":")[-1],
        graph_module,
        "grade_context",
        lambda r: (r.prompt_tokens, r.completion_tokens),
    )
    timed(
        "verify",
        lambda r: (r.model or "openai:gpt-4o-mini").split(":")[-1],
        graph_module,
        "verify_answer",
        lambda r: (r.prompt_tokens, r.completion_tokens),
    )
    timed(
        "generate",
        lambda r: answer_module.CHAT_MODEL,
        answer_module,
        "generate_step",
        lambda r: (r.prompt_tokens, r.completion_tokens),
    )

    # retrieval: wall time of retrieve_step, tokens from the embeddings call
    original_retrieve = answer_module.retrieve_step
    originals[(answer_module, "retrieve_step")] = original_retrieve
    original_get_client = search_module._get_client
    originals[(search_module, "_get_client")] = original_get_client
    embed_tokens = {"n": 0, "calls": 0}

    def counting_client():
        client = original_get_client()
        real_create = client.embeddings.create

        def create(**kw):
            resp = real_create(**kw)
            embed_tokens["n"] += resp.usage.total_tokens if resp.usage else 0
            embed_tokens["calls"] += 1
            return resp

        client.embeddings.create = create
        return client

    def retrieve_wrapper(*a, **kw):
        embed_tokens["n"] = 0
        embed_tokens["calls"] = 0
        t0 = time.monotonic()
        res = original_retrieve(*a, **kw)
        ms = int((time.monotonic() - t0) * 1000)
        rec.add("retrieve", "text-embedding-3-large", embed_tokens["n"], 0, ms)
        return res

    search_module._get_client = counting_client
    answer_module.retrieve_step = retrieve_wrapper

    def undo():
        for (mod, name), fn in originals.items():
            setattr(mod, name, fn)

    return undo


def run(args) -> dict:
    items = json.loads(args.set.read_text())
    rec = Recorder()
    undo = install(rec)
    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush
    flags = {
        "AGENTIC_RAG": config.agentic_rag_enabled(),
        "rewrite": config.agentic_rewrite_enabled(),
        "grade": config.agentic_grade_enabled(),
        "verify": config.agentic_verify_enabled(),
        "decompose": config.agentic_decompose_enabled(),
    }
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        user = AppUser(email=f"profile-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        print(
            f"profile: {len(items)} items, corpus {cv.consolidated_date}, flags {flags}, env {os.environ.get('APP_ENV', 'dev')}"
        )
        turns = []
        for it in items:
            chat = ChatSession(
                user_id=user.id, corpus_version_id=cv.id, title="profile"
            )
            session.add(chat)
            session.flush()
            for role, content in it.get("history", []):
                session.add(Message(session_id=chat.id, role=role, content=content))
            session.flush()
            rec.reset()
            t0 = time.monotonic()
            res = generate_grounded_answer(
                session, it["question"], cv.id, chat.id, max_output_tokens=800
            )
            total_ms = int((time.monotonic() - t0) * 1000)
            s = rec.summary()
            turns.append(
                {
                    "id": it["id"],
                    "bucket": it["bucket"],
                    "abstained": is_abstention(res.answer),
                    "total_ms": total_ms,
                    "usd": s["usd"],
                    "nodes": {n: s[n] for n in NODES},
                    "by_model": s["by_model"],
                }
            )
            nodes = " ".join(
                f"{n}={s[n]['ms']}ms/{s[n]['calls']}" for n in NODES if s[n]["calls"]
            )
            print(
                f"  {it['id']} {it['bucket']:<12} {total_ms:>6}ms ${s['usd']:.4f} {'ABSTAIN' if turns[-1]['abstained'] else 'answer '} | {nodes}"
            )
        return {"flags": flags, "prices": PRICES, "turns": turns}
    finally:
        undo()
        session.commit = real_commit
        session.rollback()
        session.close()


def summarise(profile: dict) -> dict:
    out = {}
    turns = profile["turns"]
    for bucket in (*BUCKETS, "all"):
        rows = [t for t in turns if bucket == "all" or t["bucket"] == bucket]
        if not rows:
            continue
        lat = [t["total_ms"] for t in rows]
        by_model = defaultdict(lambda: [0, 0])
        for t in rows:
            for m, v in t["by_model"].items():
                by_model[m][0] += v["prompt"]
                by_model[m][1] += v["completion"]
        out[bucket] = {
            "n": len(rows),
            "p50_ms": pct(lat, 0.5),
            "p95_ms": pct(lat, 0.95),
            "mean_ms": statistics.mean(lat),
            "mean_usd": statistics.mean(t["usd"] for t in rows),
            "tokens_per_turn": {
                m: (v[0] + v[1]) / len(rows) for m, v in by_model.items()
            },
            "nodes": {
                n: {
                    "mean_ms": statistics.mean(t["nodes"][n]["ms"] for t in rows),
                    "mean_usd": statistics.mean(t["nodes"][n]["usd"] for t in rows),
                    "mean_calls": statistics.mean(t["nodes"][n]["calls"] for t in rows),
                }
                for n in NODES
            },
            "abstained": sum(t["abstained"] for t in rows),
        }
    return out


def print_compare(base: dict, full: dict) -> None:
    b, f = summarise(base), summarise(full)
    print(
        f"{'turn type':<13}{'n':>3}{'p50 ms':>16}{'p95 ms':>16}{'$/turn':>20}{'gpt-4o tok':>14}{'mini tok':>12}{'embed tok':>12}"
    )
    for bucket in (*BUCKETS, "all"):
        x, y = b[bucket], f[bucket]
        tok = lambda s, m: s["tokens_per_turn"].get(m, 0)
        print(
            f"{bucket:<13}{x['n']:>3}{x['p50_ms']:>7.0f}>{y['p50_ms']:<8.0f}{x['p95_ms']:>7.0f}>{y['p95_ms']:<8.0f}"
            f"{x['mean_usd']:>9.4f}>{y['mean_usd']:<10.4f}{tok(x, 'gpt-4o'):>6.0f}>{tok(y, 'gpt-4o'):<7.0f}"
            f"{tok(x, 'gpt-4o-mini'):>5.0f}>{tok(y, 'gpt-4o-mini'):<6.0f}{tok(x, 'text-embedding-3-large'):>5.0f}>{tok(y, 'text-embedding-3-large'):<6.0f}"
        )
    print(
        "\nadded per node with the full pipeline (mean per turn, full minus baseline):"
    )
    print(f"{'turn type':<13}" + "".join(f"{n:>18}" for n in NODES) + f"{'total':>18}")
    for bucket in (*BUCKETS, "all"):
        x, y = b[bucket], f[bucket]
        cells = []
        for n in NODES:
            dms = y["nodes"][n]["mean_ms"] - x["nodes"][n]["mean_ms"]
            dusd = y["nodes"][n]["mean_usd"] - x["nodes"][n]["mean_usd"]
            cells.append(f"{dms:>+7.0f}ms {dusd:>+8.4f}")
        cells.append(
            f"{y['mean_ms'] - x['mean_ms']:>+7.0f}ms {y['mean_usd'] - x['mean_usd']:>+8.4f}"
        )
        print(f"{bucket:<13}" + "".join(f"{c:>18}" for c in cells))
    print(
        "\nabstained per bucket, baseline > full:",
        {k: f"{b[k]['abstained']}>{f[k]['abstained']}" for k in BUCKETS},
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", type=Path, default=SET_PATH)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("BASELINE", "FULL"))
    args = ap.parse_args()
    if args.compare:
        print_compare(
            json.loads(args.compare[0].read_text()),
            json.loads(args.compare[1].read_text()),
        )
        return
    profile = run(args)
    s = summarise(profile)
    print("\n== per turn type ==")
    for bucket, v in s.items():
        print(
            f"  {bucket:<13} n={v['n']:<3} p50={v['p50_ms']:.0f}ms p95={v['p95_ms']:.0f}ms mean=${v['mean_usd']:.4f} abstained={v['abstained']}"
        )
    if args.json:
        args.json.write_text(json.dumps(profile, indent=1))
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
