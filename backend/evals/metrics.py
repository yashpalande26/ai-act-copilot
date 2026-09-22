"""Per-trace metrics for the agentic-RAG evals. Pure functions, no I/O, unit
tested with literal oracles in tests/test_metrics.py.

Gold is a list of provision citation ids ("gold provision spans": in this
corpus a chunk is a provision, so a citation id is the span). A retrieved or
cited id MATCHES a gold id when it is the gold id itself or a descendant of it
(gold "art_16" is satisfied by "art_16.pt_b"; gold "art_16.pt_b" is NOT
satisfied by "art_16").

  context_recall      gold ids covered by the context slice / gold ids
  context_precision   average precision of the context slice against gold:
                      mean, over the ranks where a gold-matching chunk sits,
                      of precision at that rank. 1.0 when every gold-matching
                      chunk is ranked above every other chunk; 0.0 when none
                      is in the slice. Rank-aware, unlike a plain fraction,
                      which would be capped at (gold count / 15) by design.
  citation_accuracy   gold ids covered by the citations RETURNED with the
                      answer / gold ids. Today the returned citations are the
                      whole context slice of an answered turn, so on a
                      single-gold question this equals run_eval's citation hit.
  inline_mention      whether the answer text names a gold provision's
                      article or annex ("Article 16", "Annex III"). Stricter
                      and deterministic; reported, not gated.
  abstention_f1       two F1 scores over the (expected, predicted) refusal
                      labels: F1_ans treats "answered" as the positive class,
                      F1_ref treats "refused" as the positive class. A score
                      is None when its class has no expected and no predicted
                      members (undefined, not zero); macro averages the ones
                      that are defined.
"""

import re
from dataclasses import dataclass


def matches(citation_id: str, gold_id: str) -> bool:
    return citation_id == gold_id or citation_id.startswith(gold_id + ".")


def covered_gold(ids: list[str], gold_ids: list[str]) -> list[str]:
    return [g for g in gold_ids if any(matches(c, g) for c in ids)]


def context_recall(context_ids: list[str], gold_ids: list[str]) -> float | None:
    if not gold_ids:
        return None
    return len(covered_gold(context_ids, gold_ids)) / len(gold_ids)


def context_precision(context_ids: list[str], gold_ids: list[str]) -> float | None:
    if not gold_ids:
        return None
    hits = 0
    precisions: list[float] = []
    for rank, cid in enumerate(context_ids, start=1):
        if any(matches(cid, g) for g in gold_ids):
            hits += 1
            precisions.append(hits / rank)
    return sum(precisions) / len(precisions) if precisions else 0.0


def citation_accuracy(cited_ids: list[str], gold_ids: list[str]) -> float | None:
    if not gold_ids:
        return None
    return len(covered_gold(cited_ids, gold_ids)) / len(gold_ids)


_ROMAN = re.compile(r"^anx_([IVXLC]+)")
_ART = re.compile(r"^art_(\d+[a-z]?)")


def _label_pattern(gold_id: str) -> re.Pattern[str] | None:
    m = _ART.match(gold_id)
    if m:
        return re.compile(
            r"\bArticle\s+" + re.escape(m.group(1)) + r"\b", re.IGNORECASE
        )
    m = _ROMAN.match(gold_id)
    if m:
        return re.compile(r"\bAnnex\s+" + re.escape(m.group(1)) + r"\b")
    return None


def inline_mention(answer: str, gold_ids: list[str]) -> bool | None:
    if not gold_ids:
        return None
    for g in gold_ids:
        pat = _label_pattern(g)
        if pat is not None and pat.search(answer):
            return True
    return False


@dataclass
class F1:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None

    @property
    def f1(self) -> float | None:
        if self.tp + self.fp + self.fn == 0:
            return None
        return 2 * self.tp / (2 * self.tp + self.fp + self.fn)


@dataclass
class AbstentionF1:
    answered: F1
    refused: F1

    @property
    def f1_ans(self) -> float | None:
        return self.answered.f1

    @property
    def f1_ref(self) -> float | None:
        return self.refused.f1

    @property
    def macro(self) -> float | None:
        defined = [x for x in (self.f1_ans, self.f1_ref) if x is not None]
        return sum(defined) / len(defined) if defined else None


def abstention_f1(rows: list[tuple[bool, bool]]) -> AbstentionF1:
    """rows: (expected_abstention, predicted_abstention) per trace."""
    ans = F1(0, 0, 0)
    ref = F1(0, 0, 0)
    for expected_abstain, predicted_abstain in rows:
        if expected_abstain and predicted_abstain:
            ref.tp += 1
        elif expected_abstain and not predicted_abstain:
            ref.fn += 1
            ans.fp += 1
        elif not expected_abstain and predicted_abstain:
            ref.fp += 1
            ans.fn += 1
        else:
            ans.tp += 1
    return AbstentionF1(answered=ans, refused=ref)


def mean(values: list[float | None]) -> float | None:
    defined = [v for v in values if v is not None]
    return sum(defined) / len(defined) if defined else None
