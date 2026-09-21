"""Deterministic actor labels and the advisory actor prior.

Problem this solves: "obligations of providers" and "obligations of deployers"
are near-identical in both embedding space and BM25 space, so a provider
question pulls deployer provisions into context and vice versa. Measured on the
enumeration tier as 6 wrong-actor citations that neither breadth nor slice
could move (ADR-8).

Three pieces, all pure functions, no LLM, no network:

  actor_for(citation_id)        the label for a provision, from ACTOR_MAP
  detect_query_actor(query)     which single actor a question names, or None
  apply_actor_prior(...)        re-sort fused candidates, down-weighting
                                chunks whose label contradicts the query

The label is DATA: ACTOR_MAP is a reviewed literal, one comment per row citing
the corpus text that justifies it. Semantics, stated once so rows stay
consistent: actor = the operator role whose obligations the provision governs,
not the grammatical subject of the sentence. Article 25 lets a deployer become
a provider by modifying a system, so the label describes the provision's
addressee, never the real-world entity, which is exactly why this stays
advisory: it re-orders retrieval candidates and nothing else. It is not
imported by the classification engine and has no part in the
APPROVE / REFER / DECLINE decision.

Enumerated from corpus_version 1 (119 articles, 537 paragraph-level
provisions) on 2026-09-21. Rows deliberately ABSENT, and why, so nobody
"fixes" them later:
  art_13   heading says "information to deployers" but the obligor is the
           provider (design + instructions for use). A heading-keyword rule
           would tag it deployer and suppress it for provider questions.
  art_4    par_1 binds "Providers and deployers" jointly.
  art_25   value-chain reclassification names every actor in one article.
  art_62   "Measures for providers and deployers" bind Member States.
  art_8-15 Section 2 requirements are system-level ("High-risk AI systems
           shall..."); no operator is named.
  art_80, art_88, art_101   enforcement / fines about providers; the obligor
           is the authority.
  Notified bodies and authorities are out of scope: no query asks about them.
GPAI-model providers are plain "provider": the contamination is provider vs
deployer, and a high-risk vs GPAI scope axis is a different problem.
"""

import re

from app.retrieval.search import FusedResult

# Chosen from a measured sweep over {1.0, 0.75, 0.5, 0.25, 0.0} on identical
# retrieval: 0.25 was the first factor to clear all 6 contaminants (recall
# 0.817 -> 0.867) and 0.0 added nothing on top of it, so the softer value keeps
# the property that a mislabelled chunk ranked highly by BOTH legs can still
# surface. Guard sets (easy/hard/realistic, 107 queries) did not regress at
# any factor and no gold chunk was ever down-weighted.
ACTOR_MISMATCH_FACTOR = 0.25

# Tier A: article-level, every descendant inherits (art_16.pt_a -> provider).
# Tier B: paragraph-level, for the two articles that split by paragraph.
ACTOR_MAP: dict[str, str] = {
    # ---- Tier A ---------------------------------------------------------
    "art_16": "provider",  # heading "Obligations of providers of high-risk AI systems"
    "art_17": "provider",  # par_1, par_3 "Providers of high-risk AI systems shall"
    "art_18": "provider",  # par_1 "The provider shall, for a period ending 10 years"
    "art_19": "provider",  # both paragraphs open "Providers"
    "art_20": "provider",  # par_1 "Providers ... which consider or have reason to consider"
    "art_21": "provider",  # par_1 "Providers ... shall, upon a reasoned request"
    "art_22": "authorised_representative",  # heading; par_3/4 "The authorised representative shall"
    "art_23": "importer",  # heading; 5 of 7 paragraphs open "Importers shall"
    "art_24": "distributor",  # heading; par_3/6 "Distributors shall"
    "art_26": "deployer",  # heading "Obligations of deployers of high-risk AI systems"
    "art_27": "deployer",  # par_1 "deployers ... shall perform an assessment" (FRIA)
    "art_47": "provider",  # par_1 "The provider shall draw up a written ... declaration"
    "art_53": "provider",  # heading "Obligations for providers of general-purpose AI models"
    "art_54": "authorised_representative",  # heading; par_3/5 "The authorised representative shall"
    "art_55": "provider",  # heading "Obligations of providers of GPAI models with systemic risk"
    "art_72": "provider",  # heading "Post-market monitoring by providers"; par_1 "Providers shall"
    # ---- Tier B ---------------------------------------------------------
    "art_50.par_1": "provider",  # "Providers shall ensure that AI systems intended to interact"
    "art_50.par_2": "provider",  # "Providers of AI systems ... generating synthetic ... content"
    "art_50.par_3": "deployer",  # "Deployers of an emotion recognition system or a biometric"
    "art_50.par_4": "deployer",  # "Deployers of an AI system that generates ... a deep fake"
    # art_50.par_5-7: applies to both / savings clause / Commission -> absent
    "art_49.par_1": "provider",  # "the provider or ... authorised representative shall register"
    "art_49.par_2": "provider",  # same, for systems the provider classed as not high-risk
    "art_49.par_3": "deployer",  # "deployers that are public authorities ... shall register"
    # art_49.par_4-5: database mechanics / national registration -> absent
}


def actor_for(citation_id: str) -> str | None:
    """Exact match first, then strip trailing segments until a hit or None.
    art_16.pt_a -> art_16 -> provider; art_50.par_5 -> art_50 -> None."""
    parts = citation_id.split(".")
    while parts:
        hit = ACTOR_MAP.get(".".join(parts))
        if hit is not None:
            return hit
        parts.pop()
    return None


# Word-boundary matches only. No synonyms: "user" (the old Act's term for
# deployer), "operator", "company" are all ambiguous and would be guesses.
_ACTOR_PATTERNS: dict[str, re.Pattern[str]] = {
    "provider": re.compile(r"\bproviders?\b", re.IGNORECASE),
    "deployer": re.compile(r"\bdeployers?\b", re.IGNORECASE),
    "importer": re.compile(r"\bimporters?\b", re.IGNORECASE),
    "distributor": re.compile(r"\bdistributors?\b", re.IGNORECASE),
    "authorised_representative": re.compile(
        r"\bauthori[sz]ed representatives?\b", re.IGNORECASE
    ),
}


def detect_query_actor(query: str) -> str | None:
    """The one actor a question names, or None.

    Conservative by construction: fires only when EXACTLY one actor family is
    present. Zero ("which practices are prohibited?") and two or more ("what
    must providers give deployers?") both return None, and None makes the
    prior a no-op, so uncertainty can never cost a correct citation.
    """
    hits = [name for name, pattern in _ACTOR_PATTERNS.items() if pattern.search(query)]
    return hits[0] if len(hits) == 1 else None


def apply_actor_prior(
    fused: list[FusedResult], query_actor: str | None, factor: float
) -> list[FusedResult]:
    """Re-sort fused candidates so chunks whose label contradicts the query
    sink. Returns a new list of the SAME FusedResult objects: rrf_score is
    left raw so a trace row stays reproducible from (raw score, ACTOR_MAP,
    factor), and nothing is ever removed, so a mislabelled chunk that both
    legs rank highly can still reach the context.

    Untouched: every chunk when query_actor is None; chunks with no label;
    chunks whose label matches. The sort is stable, so ties keep their
    original order.
    """
    if query_actor is None or factor == 1.0:
        return list(fused)

    def adjusted(f: FusedResult) -> float:
        actor = actor_for(f.result.citation_id)
        if actor is not None and actor != query_actor:
            return f.rrf_score * factor
        return f.rrf_score

    return sorted(fused, key=adjusted, reverse=True)
