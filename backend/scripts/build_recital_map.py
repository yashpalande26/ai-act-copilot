"""Build the recital-to-provision map (ADR-33) into provision_reference.

    python scripts/build_recital_map.py                # dry run: prints every edge, writes nothing
    python scripts/build_recital_map.py --execute      # writes the edges (replacing any recital_map edges)
    python scripts/build_recital_map.py --json out.json

Explicit edges come from the recital text (verifier reference parser, resolved
to the most specific citation id in the corpus). Semantic edges come from the
recital chunk's nearest operative chunks by cosine (pgvector), one per recital
at most, under app.retrieval.recital_map.semantic_choice. Nothing is embedded
here; the chunk embeddings already exist.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select, text

from app.db.models import CorpusVersion, Provision, ProvisionReference
from app.db.session import SessionLocal
from app.generation.verify import references_in
from app.retrieval.recital_map import (
    EDGE_PREFIX,
    SEMANTIC_MIN_MARGIN,
    SEMANTIC_MIN_SIMILARITY,
    resolve_to_corpus,
    semantic_choice,
)

NEIGHBOURS_SQL = """
with rec as (
  select p.id pid, p.citation_id rec, c.embedding emb
  from chunk c join provision p on p.id = c.provision_id
  where p.unit_type = 'recital' and c.corpus_version_id = :cv
)
select rec.pid, rec.rec, nn.citation_id, nn.sim
from rec
join lateral (
  select p2.citation_id, 1 - (c2.embedding <=> rec.emb) as sim
  from chunk c2 join provision p2 on p2.id = c2.provision_id
  where p2.unit_type <> 'recital' and c2.embedding is not null and c2.corpus_version_id = :cv
  order by c2.embedding <=> rec.emb
  limit 3
) nn on true
order by rec.rec, nn.sim desc
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    session = SessionLocal()
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        provs = session.execute(
            select(
                Provision.id,
                Provision.citation_id,
                Provision.unit_type,
                Provision.text_content,
            ).where(Provision.corpus_version_id == cv.id)
        ).all()
        ids = {p.citation_id for p in provs}
        row_id = {p.citation_id: p.id for p in provs}
        recitals = sorted(
            (p for p in provs if p.unit_type == "recital"),
            key=lambda p: int(p.citation_id.split("_")[1]),
        )
        # explicit
        edges = []  # (rec, target, kind, score, note)
        explicit_by_rec = {}
        for p in recitals:
            targets = sorted(
                {
                    t
                    for t in (
                        resolve_to_corpus(r, ids)
                        for r in references_in(p.text_content)
                        if not r.startswith("rec_")
                    )
                    if t
                }
            )
            explicit_by_rec[p.citation_id] = targets
            for t in targets:
                edges.append((p.citation_id, t, "explicit", None, ""))
        # semantic, only for recitals with no explicit edge
        nn = defaultdict(list)
        for pid, rec, cid, sim in session.execute(
            text(NEIGHBOURS_SQL), {"cv": cv.id}
        ).all():
            nn[rec].append((cid, float(sim)))
        skipped = []
        for p in recitals:
            if explicit_by_rec[p.citation_id]:
                continue
            choice = semantic_choice(nn.get(p.citation_id, []))
            if choice is None:
                skipped.append((p.citation_id, nn.get(p.citation_id, [])[:2]))
                continue
            target, sim = choice
            margin = (
                (nn[p.citation_id][0][1] - nn[p.citation_id][1][1])
                if len(nn[p.citation_id]) > 1
                else None
            )
            edges.append(
                (
                    p.citation_id,
                    target,
                    "semantic",
                    round(sim, 3),
                    f"margin={margin:.3f}" if margin is not None else "",
                )
            )
        kinds = Counter(k for _, _, k, _, _ in edges)
        linked = {r for r, *_ in edges}
        print(
            f"corpus_version {cv.id}  recitals {len(recitals)}  edges {len(edges)} (explicit {kinds['explicit']}, semantic {kinds['semantic']})"
        )
        print(
            f"recitals linked {len(linked)}/{len(recitals)}; with explicit {sum(1 for v in explicit_by_rec.values() if v)}; semantic-only {kinds['semantic']}; unlinked (ambiguous or below threshold) {len(skipped)}"
        )
        print(
            f"semantic rule: similarity >= {SEMANTIC_MIN_SIMILARITY}, margin >= {SEMANTIC_MIN_MARGIN} or sibling/parent merge"
        )
        print("\n== edges ==")
        for rec, t, k, sc, note in edges:
            print(
                f"  {rec:<8} -> {t:<22} {k:<9} {sc if sc is not None else '':<6} {note}"
            )
        print("\n== unlinked recitals (top two neighbours) ==")
        for rec, top in skipped:
            print(f"  {rec:<8} {[(c, round(s, 3)) for c, s in top]}")
        if args.json:
            args.json.write_text(
                json.dumps(
                    {
                        "edges": edges,
                        "unlinked": skipped,
                        "explicit_by_recital": explicit_by_rec,
                    },
                    indent=1,
                )
            )
        if not args.execute:
            print("\ndry run: nothing written. Re-run with --execute.")
            return
        session.execute(
            delete(ProvisionReference).where(
                ProvisionReference.corpus_version_id == cv.id,
                ProvisionReference.raw_text.like(f"{EDGE_PREFIX}%"),
            )
        )
        for rec, t, k, sc, note in edges:
            session.add(
                ProvisionReference(
                    corpus_version_id=cv.id,
                    from_provision_id=row_id[rec],
                    to_citation_id=t,
                    to_provision_id=row_id.get(t),
                    raw_text=f"{EDGE_PREFIX}{k}" + (f":{sc}" if sc is not None else ""),
                )
            )
        session.commit()
        print(f"\nwritten: {len(edges)} edges")
    finally:
        session.close()


if __name__ == "__main__":
    main()
