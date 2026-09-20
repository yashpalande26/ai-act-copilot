"""Stage 5 investigation: which sparse-leg text, which weight, which breadth, router?

Builds THROWAWAY BM25 index variants in a temp dir (never touches the
production index at backend/data/bm25_index) and measures each against three
eval sets.

Variants:
  chunk_text     body only - what production indexes today (Stage 2 choice)
  index_text     heading-prefixed body - what vector_search already embeds.
                 This is what Anthropic's Contextual Retrieval prescribes:
                 prepend context "before embedding it and before creating the
                 BM25 index". Our codebase does the first but not the second.
  heading_boost  heading repeated N times + body. bm25s has NO BM25F/
                 multi-field support (verified: no field/fields/BM25F methods
                 on bm25s.BM25), so true field weighting is unavailable. Term
                 repetition raises heading term frequency within the single
                 field, which is the closest single-field equivalent - it is an
                 APPROXIMATION of field weighting, not BM25F.

    python -m evals.experiment_retrieval
"""

import math
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.db.models import Chunk, CorpusVersion, Provision
from app.db.session import SessionLocal
from app.retrieval import bm25_index as bi
from app.retrieval.search import SearchResult, rrf_rank_and_fuse, vector_search
from evals.run_eval import (
    GOLDEN_SET_HARD_PATH,
    GOLDEN_SET_PATH,
    load_golden_set,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

REALISTIC_PATH = Path(__file__).resolve().parent / "golden_set_realistic.yaml"
VARIANTS = ["chunk_text", "index_text", "heading_boost"]
HEADING_REPEATS = 3
MAX_BREADTH = 50
DEFAULT_BREADTH = 10
WEIGHTS = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0]
MIN_SIMILARITY = 0.3
CUTOFF = 5


def corpus_rows(session, cv_id):
    A = aliased(Provision)
    rows = session.execute(
        select(Chunk, Provision, A)
        .join(Provision, Chunk.provision_id == Provision.id)
        .outerjoin(A, Chunk.parent_provision_id == A.id)
        .where(Chunk.corpus_version_id == cv_id, Chunk.embedding.isnot(None))
        .order_by(Chunk.id)
    ).all()
    out = []
    for c, _p, a in rows:
        heading = (a.heading if a is not None else None) or ""
        out.append(
            {
                "id": c.id,
                "chunk_text": c.chunk_text,
                "index_text": c.index_text,
                "heading_boost": ((heading + " ") * HEADING_REPEATS) + c.chunk_text,
            }
        )
    return out


def build_variants(session, cv_id, root: Path) -> dict[str, Path]:
    dirs = {}
    original_root, original_fetch = bi.INDEX_ROOT, bi.fetch_indexable_chunks
    rows = corpus_rows(session, cv_id)
    try:
        for variant in VARIANTS:
            bi.INDEX_ROOT = root / variant
            bi.fetch_indexable_chunks = lambda _s, _c, v=variant: [
                (r["id"], r[v]) for r in rows
            ]
            bi._CACHE.clear()
            m = bi.build_index(session, cv_id)
            dirs[variant] = root / variant
            print(f"  built {variant:<14} docs={m['doc_count']}")
    finally:
        bi.INDEX_ROOT, bi.fetch_indexable_chunks = original_root, original_fetch
        bi._CACHE.clear()
    return dirs


def bm25_ids(root: Path, cv_id: int, query: str, k: int) -> list[tuple[int, float]]:
    """Raw (chunk_id, score) - no DB hydration needed for rank metrics."""
    bi.INDEX_ROOT = root
    bi._CACHE.clear()
    loaded = bi.load_index(cv_id)
    idx, scores = loaded.retriever.retrieve(
        bi.tokenize_query(query), k=min(k, len(loaded.chunk_ids)), show_progress=False
    )
    return [
        (loaded.chunk_ids[int(i)], float(s))
        for i, s in zip(idx[0], scores[0], strict=True)
    ]


def _sr(chunk_id: int, citation_id: str) -> SearchResult:
    """Minimal SearchResult so rrf_rank_and_fuse can fuse raw ids. Only
    chunk_id (the fusion key) and citation_id (the metric key) matter here."""
    return SearchResult(
        chunk_id=chunk_id,
        citation_id=citation_id,
        citation_label=citation_id,
        chunk_text="",
        similarity=0.0,
        article_heading=None,
    )


def metrics(ids: list[str], expected: str):
    return (
        recall_at_k(ids[:CUTOFF], expected),
        reciprocal_rank(ids[:CUTOFF], expected),
        ndcg_at_k(ids, expected, k=10),
    )


def mean(rows):
    if not rows:
        return 0.0, 0.0, 0.0
    n = len(rows)
    return tuple(sum(r[i] for r in rows) / n for i in range(3))


def fuse(vec, lex, weight, breadth):
    fused = rrf_rank_and_fuse(
        [_sr(c, i) for c, i in vec[:breadth]],
        [_sr(c, i) for c, i in lex[:breadth]],
        vector_weight=1.0 - weight,
        lexical_weight=weight,
        top_k=breadth,
    )
    return [f.result.citation_id for f in fused]


def main() -> None:
    session = SessionLocal()
    tmp = Path(tempfile.mkdtemp(prefix="bm25_experiment_"))
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        id_to_citation = dict(
            session.execute(
                select(Chunk.id, Provision.citation_id).join(
                    Provision, Chunk.provision_id == Provision.id
                )
            ).all()
        )

        print("building throwaway index variants (production index untouched):")
        dirs = build_variants(session, cv.id, tmp)

        sets = {
            "realistic": REALISTIC_PATH,
            "hard": GOLDEN_SET_HARD_PATH,
            "easy": GOLDEN_SET_PATH,
        }

        # --- retrieve once per query, reuse for every config ---
        data = {}
        for name, path in sets.items():
            items = [g for g in load_golden_set(path) if not g["expected_abstention"]]
            rows = []
            for item in items:
                vec = [
                    (r.chunk_id, r.citation_id)
                    for r in vector_search(
                        session,
                        item["question"],
                        cv.id,
                        top_k=MAX_BREADTH,
                        min_similarity=MIN_SIMILARITY,
                    )
                ]
                lex = {
                    v: [
                        (cid, s)
                        for cid, s in bm25_ids(
                            dirs[v], cv.id, item["question"], MAX_BREADTH
                        )
                    ]
                    for v in VARIANTS
                }
                lex = {
                    v: [(cid, id_to_citation[cid]) for cid, _ in pairs]
                    for v, pairs in lex.items()
                }
                rows.append((item, vec, lex))
            data[name] = rows
            print(f"  retrieved {name}: {len(rows)} queries")

        def report(name, config_fn, label):
            rows = data[name]
            by_cat = defaultdict(list)
            allrows = []
            for item, vec, lex in rows:
                ids = config_fn(item, vec, lex)
                m = metrics(ids, item["expected_citation_id"])
                by_cat[item.get("category", "all")].append(m)
                allrows.append(m)
            cats = sorted(by_cat)
            cells = " ".join(
                f"{c[:9]}={mean(by_cat[c])[0]:.3f}/{mean(by_cat[c])[1]:.3f}"
                for c in cats
            )
            r, mr, nd = mean(allrows)
            print(f"  {label:<26} ALL={r:.3f}/{mr:.3f}/{nd:.3f}  {cells}")

        print("\n(numbers are Recall@5/MRR; ALL adds nDCG@10. breadth=10, k=60)")
        for name in sets:
            print(f"\n=== {name} set ===")
            report(name, lambda it, v, l: [c for _, c in v[:10]], "vector_only")
            for variant in VARIANTS:
                report(
                    name,
                    lambda it, v, l, x=variant: [c for _, c in l[x][:10]],
                    f"bm25_only[{variant}]",
                )
            for variant in VARIANTS:
                report(
                    name,
                    lambda it, v, l, x=variant: fuse(v, l[x], 0.5, DEFAULT_BREADTH),
                    f"hybrid@0.5[{variant}]",
                )

        # --- weight sweep for the best variant, on the realistic set ---
        print("\n=== weight sweep (realistic set) ===")
        for variant in VARIANTS:
            print(f"  -- {variant} --")
            for w in WEIGHTS:
                report(
                    "realistic",
                    lambda it, v, l, x=variant, ww=w: fuse(
                        v, l[x], ww, DEFAULT_BREADTH
                    ),
                    f"w={w}",
                )

        # --- breadth for index_text ---
        print("\n=== breadth sweep, index_text @ w=0.5 (realistic set) ===")
        for b in (10, 20, 30, 50):
            report(
                "realistic",
                lambda it, v, l, bb=b: fuse(v, l["index_text"], 0.5, bb),
                f"breadth={b}",
            )

        # --- simple query router ---
        print("\n=== query router: max-IDF gate (realistic set, in-sample) ===")
        rows_all = corpus_rows(session, cv.id)
        df: Counter = Counter()
        for r in rows_all:
            df.update(set(bi.tokenize_corpus([r["chunk_text"]]).vocab))
        N = len(rows_all)

        def max_idf(q: str) -> float:
            toks = bi.tokenize_query(q)[0]
            if not toks:
                return 0.0
            return max(math.log((N + 1) / (df.get(t, 0) + 1)) for t in toks)

        for thresh in (0.0, 3.0, 4.0, 5.0, 6.0, 99.0):
            report(
                "realistic",
                lambda it, v, l, t=thresh: (
                    fuse(v, l["index_text"], 0.5, DEFAULT_BREADTH)
                    if max_idf(it["question"]) >= t
                    else [c for _, c in v[:10]]
                ),
                f"hybrid if maxIDF>={thresh}",
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        bi._CACHE.clear()
        session.close()


if __name__ == "__main__":
    main()
