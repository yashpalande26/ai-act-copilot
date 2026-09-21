"""Article 99 ceilings, computed from the quoted text and the user's inputs.

No fine amount or percentage is hardcoded here. The caps are parsed from the
live provision text at request time; a test asserts the parse against the
corpus so a future consolidation that changes the numbers fails loudly.

Rules, each quoted in the report:
  par_3   Article 5 breaches      EUR cap or % of turnover, whichever HIGHER
  par_4   listed obligations      EUR cap or %, whichever HIGHER
  par_5   incorrect information   EUR cap or %, whichever HIGHER
  par_6   SMEs and start-ups      each of the above, whichever LOWER
  par_6a  SMCs                    par_4 and par_5 only, whichever LOWER

A personalised ceiling is computed only from a POSITIVE turnover. Missing
(None) and an entered 0 both leave ceiling_eur None: under the "lower" rule
0 % of 0 would print as "EUR 0", which is arithmetic, not a defensible reading
of the Article. The two cases are told apart by turnover_status() so the
report can say which input is needed.
"""

import re
from dataclasses import dataclass
from typing import Literal

TurnoverStatus = Literal["provided", "missing", "zero", "not_needed"]


def turnover_status(*, undertaking: bool, turnover_eur: float | None) -> TurnoverStatus:
    if not undertaking:
        return "not_needed"  # eur_only: the fixed cap applies, no turnover involved
    if turnover_eur is None:
        return "missing"
    if turnover_eur <= 0:
        return "zero"
    return "provided"


_EUR = re.compile(r"EUR\s*((?:\d{1,3}(?:\s\d{3})+)|\d+)")
_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


class CeilingParseError(ValueError):
    pass


def parse_ceiling(text: str) -> tuple[int, float]:
    """(EUR cap, percentage cap) from a paragraph like 'up to EUR 35 000 000
    or ... up to 7 % of its total worldwide annual turnover'."""
    eur = _EUR.search(text)
    pct = _PCT.search(text)
    if not eur or not pct:
        raise CeilingParseError(f"could not parse a fine ceiling from: {text[:80]!r}")
    return int(eur.group(1).replace(" ", "")), float(pct.group(1).replace(",", "."))


@dataclass(frozen=True)
class Ceiling:
    paragraph_id: str
    eur_cap: int
    pct_cap: float
    applicable: bool
    rule: str  # "higher" | "lower" | "eur_only"
    rule_basis: tuple[str, ...]
    ceiling_eur: float | None
    why: str


def compute(
    *,
    par3_text: str,
    par4_text: str,
    par5_text: str,
    art5_flagged: bool,
    obligations_flagged: bool,
    undertaking: bool,
    turnover_eur: float | None,
    sme_or_startup: bool,
    smc: bool,
) -> list[Ceiling]:
    def line(
        pid: str, text: str, applicable: bool, why: str, smc_lower: bool
    ) -> Ceiling:
        eur, pct = parse_ceiling(text)
        if not undertaking:
            return Ceiling(pid, eur, pct, applicable, "eur_only", (), float(eur), why)
        lower = sme_or_startup or (smc and smc_lower)
        basis = tuple(
            b
            for b, on in (
                ("art_99.par_6", sme_or_startup),
                ("art_99.par_6a", smc and smc_lower),
            )
            if on
        )
        if turnover_status(undertaking=True, turnover_eur=turnover_eur) != "provided":
            return Ceiling(
                pid,
                eur,
                pct,
                applicable,
                "lower" if lower else "higher",
                basis,
                None,
                why,
            )
        by_pct = turnover_eur * pct / 100
        value = min(eur, by_pct) if lower else max(eur, by_pct)
        return Ceiling(
            pid, eur, pct, applicable, "lower" if lower else "higher", basis, value, why
        )

    return [
        line(
            "art_99.par_3",
            par3_text,
            art5_flagged,
            "Applies to non-compliance with the Article 5 prohibitions.",
            smc_lower=False,  # par_6a covers paragraphs 4 and 5 only
        ),
        line(
            "art_99.par_4",
            par4_text,
            obligations_flagged,
            "Applies to the operator obligations listed in Article 99(4), "
            "including Articles 16, 22, 23, 24, 26 and 50.",
            smc_lower=True,
        ),
        line(
            "art_99.par_5",
            par5_text,
            True,
            "Applies to supplying incorrect, incomplete or misleading information "
            "to authorities, whatever the system's classification.",
            smc_lower=True,
        ),
    ]
