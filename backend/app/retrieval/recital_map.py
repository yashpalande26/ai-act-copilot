"""Recital-to-provision map (ADR-33, 23 Sep 2026).

A recital is the reason behind a rule, never the rule (ADR-32). This module
knows which operative provision a recital explains, so retrieval can bring
the recital in as explanation exactly when its provision is in the context,
instead of letting recitals compete in the fused pool.

Edges live in provision_reference with from_provision_id = the recital row
and raw_text prefixed "recital_map:", of two kinds:

  explicit   the recital's own text names the provision ("Article 6(2)",
             "Annex III"): parsed by the verifier's reference parser and
             resolved to the most specific citation id the corpus has. High
             precision, no model.
  semantic   for a recital that names nothing: its chunk embedding's nearest
             operative chunk, kept only when the similarity clears
             SEMANTIC_MIN_SIMILARITY and the choice is unambiguous: either
             the runner-up is at least SEMANTIC_MIN_MARGIN behind, or the
             top two are siblings (or child and parent) under one provision,
             in which case the edge goes to that common parent, because a
             recital that sits between two sub-points of Annex III point 5
             explains point 5. Two close candidates from different articles
             give no edge: a wrong "reason for the rule" is worse than none.
             At most one semantic edge per recital.

Selection at retrieval time (recitals_for_context): the operative ids in the
slice are matched against edge targets (a target matches an id that equals
it, descends from it, or is its direct parent), explicit edges rank before
semantic, earlier context positions before later, one recital once, capped.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Provision, ProvisionReference

EDGE_PREFIX = "recital_map:"
SEMANTIC_MIN_SIMILARITY = 0.75
SEMANTIC_MIN_MARGIN = 0.02
MAX_RECITALS_IN_CONTEXT = 2


@dataclass(frozen=True)
class Edge:
    recital: str  # rec_N
    target: str  # citation id of the operative provision
    kind: str  # explicit | semantic
    score: float | None  # cosine similarity for semantic edges


def resolve_to_corpus(ref: str, corpus_ids: set[str]) -> str | None:
    """The most specific existing ancestor-or-self of a parsed reference:
    art_6.par_2.pt_a -> art_6.par_2 when the point is not a row."""
    parts = ref.split(".")
    while parts:
        cid = ".".join(parts)
        if cid in corpus_ids:
            return cid
        parts.pop()
    return None


def _parent(cid: str) -> str | None:
    return cid.rsplit(".", 1)[0] if "." in cid else None


def semantic_choice(
    neighbours: list[tuple[str, float]],
    *,
    min_similarity: float = SEMANTIC_MIN_SIMILARITY,
    min_margin: float = SEMANTIC_MIN_MARGIN,
) -> tuple[str, float] | None:
    """One target from the nearest operative chunks, or None. `neighbours`
    are (citation_id, similarity) best first."""
    if not neighbours or neighbours[0][1] < min_similarity:
        return None
    first, s1 = neighbours[0]
    if len(neighbours) == 1:
        return first, s1
    second, s2 = neighbours[1]
    if s1 - s2 >= min_margin:
        return first, s1
    # close call: allowed only when both point at the same provision family
    if _parent(first) and _parent(first) == _parent(second):
        return _parent(first), s1  # siblings: the parent explains both
    if second == _parent(first) or first == _parent(second):
        return (second if second == _parent(first) else first), s1  # child and parent
    return None


def _matches(target: str, cid: str) -> bool:
    return (
        cid == target
        or cid.startswith(target + ".")
        or _parent(cid) == target
        or _parent(target) == cid
    )


def load_edges(session: Session, corpus_version_id: int) -> list[Edge]:
    """All recital-map edges of a corpus version, from provision_reference."""
    rows = session.execute(
        select(ProvisionReference, Provision.citation_id)
        .join(Provision, Provision.id == ProvisionReference.from_provision_id)
        .where(
            ProvisionReference.corpus_version_id == corpus_version_id,
            ProvisionReference.raw_text.like(f"{EDGE_PREFIX}%"),
            Provision.unit_type == "recital",
        )
    ).all()
    edges = []
    for ref, rec in rows:
        parts = ref.raw_text[len(EDGE_PREFIX) :].split(":")
        kind = parts[0]
        score = float(parts[1]) if kind == "semantic" and len(parts) > 1 else None
        edges.append(
            Edge(recital=rec, target=ref.to_citation_id, kind=kind, score=score)
        )
    return edges


_EDGE_CACHE: dict[int, list[Edge]] = {}


def edges_for(session: Session, corpus_version_id: int) -> list[Edge]:
    """Process-level cache: the map changes only by re-running the build
    script, which is a deploy-time step."""
    cached = _EDGE_CACHE.get(corpus_version_id)
    if cached is None:
        cached = load_edges(session, corpus_version_id)
        _EDGE_CACHE[corpus_version_id] = cached
    return cached


def clear_cache() -> None:
    _EDGE_CACHE.clear()


def _is_root(cid: str) -> bool:
    return "." not in cid


def _match_strength(target: str, cid: str) -> int:
    """How specifically an edge target names a context provision: 3 the same
    id; 2 the context id sits under a paragraph- or point-level target, or
    the target sits directly under the context id; 1 the target is a bare
    Article or Annex root (Recital 3 citing "Article 16" explains all of it,
    weakly); 0 no match."""
    if cid == target:
        return 3
    if cid.startswith(target + "."):
        return 1 if _is_root(target) else 2
    if _parent(target) == cid:
        return 2
    return 0


MAX_EXPLICIT_TARGETS = (
    4  # a recital citing more provisions is cross-cutting, not an explanation of one
)


def recitals_for_context(
    edges: list[Edge], context_ids: list[str], *, cap: int = MAX_RECITALS_IN_CONTEXT
) -> list[tuple[str, Edge]]:
    """(recital, edge) pairs to add for a context, best first. Ranking, in
    order: specific matches before bare-root matches, then the provision's
    position in the context (earlier first), then the more specific match,
    then explicit before semantic. Recitals whose explicit edges fan out over more
    than MAX_EXPLICIT_TARGETS provisions are skipped: they survey the Act
    rather than explain a rule (measured: Recitals 40 and 41, four targets
    each including Article 5(1), outranked Recital 58 on a creditworthiness
    question under explicit-first ordering). Each recital at most once; only
    recitals whose provision is present."""
    fan_out: dict[str, int] = {}
    for e in edges:
        if e.kind == "explicit":
            fan_out[e.recital] = fan_out.get(e.recital, 0) + 1
    ranked: list[tuple[int, int, int, str, Edge]] = []
    for pos, cid in enumerate(context_ids):
        if cid.startswith("rec_"):
            continue
        for e in edges:
            if fan_out.get(e.recital, 0) > MAX_EXPLICIT_TARGETS:
                continue
            strength = _match_strength(e.target, cid)
            if strength:
                # Two bands: a specific match (the provision itself, its
                # point-level parent, or its child) and a bare-root match.
                # Inside a band the context position decides, because the
                # top-ranked provision is what the question is about
                # (measured: with strength first, the social-scoring recital
                # attached to a creditworthiness question through Article
                # 5(1)(c) at position 1, ahead of Recital 58 at position 0,
                # and two Article 25(3) recitals at position 4 outranked
                # Recital 50 at position 2 on the lift question).
                band = 0 if strength >= 2 else 1
                ranked.append(
                    (
                        band,
                        pos,
                        -strength,
                        0 if e.kind == "explicit" else 1,
                        e.recital,
                        e,
                    )
                )
    # same band, same provision: the more specific edge first (Recital 31 names
    # Article 5(1)(c) itself; Recitals 40 and 41 name Article 5(1)), then explicit
    ranked.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    out: list[tuple[str, Edge]] = []
    seen: set[str] = set()
    for _, _, _, _, rec, e in ranked:
        if rec in seen:
            continue
        seen.add(rec)
        out.append((rec, e))
        if len(out) >= cap:
            break
    return out
