"""ENGINE_VERSION: "assess-1.<rules_hash>".

The "1" is bumped by hand for a change in the engine's *logic* (engine.py).
The hash is computed from the rule DATA in code, so any change to a rule row
changes the version automatically and a saved assessment can always say
which rules produced it. The serialisation is canonical (sorted keys, sorted
sets, fixed separators, ASCII) so the hash reproduces across machines and
Python versions regardless of dict or set iteration order.

The corpus consolidated date is stored next to the version by the caller: the
TEXT a report quotes depends on the corpus, not on these rules.
"""

import hashlib
import json

from app.assessment import engine, obligations, questionnaire
from app.assessment.schema import PROHIBITED_KEYS

ENGINE_MAJOR = 1


def rules_payload() -> dict:
    """Everything that decides a result, as plain sorted data."""
    return {
        "annex_iii_points": sorted(engine.ANNEX_III_POINTS),
        "authority_gated": sorted(engine.AUTHORITY_GATED),
        "art_25_basis": sorted(list(pair) for pair in engine.ART_25_BASIS),
        "scope_exclusions": sorted(list(pair) for pair in engine.SCOPE_EXCLUSIONS),
        "prohibited_keys": sorted(PROHIBITED_KEYS),
        "obligation_groups": sorted(
            (
                {
                    "key": s.key,
                    "role": s.role,
                    "ids": list(s.ids),
                    "mode": s.mode,
                    "applies_from": s.applies_from,
                }
                for s in obligations.ALL_SPECS
            ),
            key=lambda g: g["key"],
        ),
        "transparency_role": dict(sorted(obligations.TRANSPARENCY_ROLE.items())),
        "gpai": sorted(obligations.GPAI_TITLES),
        "questions": sorted(
            (
                {"id": qid, "kind": kind, "basis": sorted(basis)}
                for _, _, qs in questionnaire._RAW
                for qid, kind, _, _, basis in qs
            ),
            key=lambda q: q["id"],
        ),
        "penalty_paragraphs": ["art_99.par_3", "art_99.par_4", "art_99.par_5"],
    }


def _sorted_default(o):
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(type(o).__name__)


def rules_hash() -> str:
    canonical = json.dumps(
        rules_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_sorted_default,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


ENGINE_VERSION = f"assess-{ENGINE_MAJOR}.{rules_hash()[:12]}"
