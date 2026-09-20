"""Builds golden_set_realistic.yaml - an eval set that CAN see heading-dependent failures.

Why this exists: both existing golden sets generate their questions from
provision.text_content (build_golden_set.py:68, build_golden_set_hard.py:184).
text_content is exactly what chunk_text holds, so every question in those sets
is guaranteed answerable from chunk_text alone. A retrieval failure that
depends on the article HEADING - the art_16.pt_a case, where "obligations" and
"providers" live only in the heading - is therefore structurally invisible to
them. They cannot help but overstate a chunk_text-only BM25 leg.

Two deliberate differences from golden_set_hard.yaml:
  1. A heading_dependent category whose questions are VERIFIED to carry terms
     that appear in the article heading but NOT in the chunk body.
  2. NO adversarial screening. The hard set kept only questions vector-only got
     wrong, which biased it toward any non-vector retriever. This set samples
     naturally and keeps whatever the screens allow, so the measurement is fair
     in both directions.

Labels stay source-grounded: the citation is always the provision we drew from,
never something the LLM chose.
"""

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.db.models import Chunk, CorpusVersion, Provision
from app.db.session import SessionLocal
from app.generation.answer import CHAT_MODEL
from app.ingestion.embedder import _get_client
from app.retrieval.bm25_index import tokenize_corpus
from evals.build_golden_set_hard import (
    EXCLUDED_TOP_LEVEL,
    _is_answerable,
    _question_quality_issue,
)
from evals.judge import JUDGE_MODEL  # noqa: F401  (re-exported for parity)

OUTPUT_PATH = Path(__file__).resolve().parent / "golden_set_realistic.yaml"

MIN_TEXT_LENGTH = 150
TARGETS = {
    "heading_dependent": 15,
    "body_dependent": 15,
    "exact_term": 10,
    "near_duplicate": 8,
    "control": 8,
}
POOL_MULTIPLIER = 4  # generate this many candidates per kept entry, at most

HEADING_SYSTEM_PROMPT = """\
You write natural-language questions for an EU AI Act eval set.

You are given an article HEADING and one excerpt of text from under it. Write
ONE natural question that a compliance professional would actually type, which:
- is answered by the EXCERPT, and
- names the subject matter using wording from the HEADING (for example the
  actor, duty, or topic the heading identifies), because that is how a real
  user would refer to this material

Do not mention article, paragraph, or point numbers in the question itself.
Return ONLY the question text, nothing else - no quotes, no preamble.
"""

BODY_SYSTEM_PROMPT = """\
You write natural-language questions for an EU AI Act eval set. Given a short
excerpt from the Act, write ONE clear, natural-language question whose answer
is directly contained in the excerpt, using the excerpt's own distinctive
wording.

Do not mention article, paragraph, or point numbers in the question itself.
Return ONLY the question text, nothing else - no quotes, no preamble.
"""

RARE_TERM_SYSTEM_PROMPT = """\
You write natural-language questions for an EU AI Act eval set. Given a short
excerpt from the Act and a list of DISTINCTIVE TERMS that appear in it, write
ONE clear, natural-language question whose answer is directly contained in the
excerpt, and which uses at least one of the distinctive terms verbatim.

Do not mention article, paragraph, or point numbers in the question itself.
Return ONLY the question text, nothing else - no quotes, no preamble.
"""

NEAR_DUP_SYSTEM_PROMPT = """\
You write natural-language questions for an EU AI Act eval set. You will be
given a TARGET excerpt and one or more SIMILAR excerpts that are easy to
confuse with it.

Write ONE clear, natural-language question that is fully answerable from the
TARGET alone, NOT answerable from any SIMILAR excerpt, and turns on the
specific detail that distinguishes them.

Do not mention article, paragraph, or point numbers in the question itself.
Return ONLY the question text, nothing else - no quotes, no preamble.
"""

CONTROL_SYSTEM_PROMPT = (
    "You write natural-language questions for an EU AI Act quiz. Given a short "
    "excerpt from the Act, write ONE clear, natural-language question whose "
    "answer is directly contained in the excerpt. Do not mention article, "
    "paragraph, or point numbers in the question itself. Return ONLY the "
    "question text, nothing else - no quotes, no preamble."
)

ABSTENTION_QUESTIONS = [
    "What is the capital of France?",
    "What's the best pizza place in Dublin?",
    "How do I train a dog to sit?",
    "What's the weather like today?",
    "How do I bake sourdough bread at home?",
    "Who won the most recent football World Cup?",
]

WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]{5,}")


@dataclass
class Cand:
    category: str
    chunk_id: int
    citation_id: str
    chunk_text: str
    heading: str | None
    siblings: list = field(default_factory=list)
    rare_terms: list[str] = field(default_factory=list)
    question: str | None = None
    heading_only_terms: list[str] = field(default_factory=list)


def _toks(text: str) -> set[str]:
    return set(tokenize_corpus([text]).vocab) if text and text.strip() else set()


def _chat(client, system_prompt: str, user_prompt: str) -> str:
    r = client.chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return r.choices[0].message.content.strip()


def load_rows(session, cv_id: int):
    A = aliased(Provision)
    rows = session.execute(
        select(Chunk, Provision, A)
        .join(Provision, Chunk.provision_id == Provision.id)
        .outerjoin(A, Chunk.parent_provision_id == A.id)
        .where(Chunk.corpus_version_id == cv_id, Chunk.embedding.isnot(None))
        .order_by(Chunk.id)
    ).all()
    return [
        (c, p, a)
        for c, p, a in rows
        if len(c.chunk_text.strip()) >= MIN_TEXT_LENGTH
        and p.citation_id.split(".")[0] not in EXCLUDED_TOP_LEVEL
    ]


def build_pools(rows) -> dict[str, list[Cand]]:
    pools: dict[str, list[Cand]] = defaultdict(list)

    # heading_dependent: heading contributes terms the body lacks
    for c, p, a in rows:
        if a is None or not a.heading:
            continue
        only = sorted(_toks(a.heading) - _toks(c.chunk_text))
        if len(only) >= 2:
            pools["heading_dependent"].append(
                Cand(
                    "heading_dependent",
                    c.id,
                    p.citation_id,
                    c.chunk_text,
                    a.heading,
                    heading_only_terms=only,
                )
            )

    # body_dependent / control: any qualifying chunk
    for c, p, a in rows:
        heading = a.heading if a is not None else None
        pools["body_dependent"].append(
            Cand("body_dependent", c.id, p.citation_id, c.chunk_text, heading)
        )
        pools["control"].append(
            Cand("control", c.id, p.citation_id, c.chunk_text, heading)
        )

    # exact_term: rare corpus-wide terms
    df: Counter = Counter()
    words_by_chunk = {}
    for c, p, a in rows:
        w = {x.lower() for x in WORD_RE.findall(c.chunk_text)}
        words_by_chunk[c.id] = w
        df.update(w)
    rare = {w for w, n in df.items() if n <= 2}
    for c, p, a in rows:
        hits = sorted(words_by_chunk[c.id] & rare)
        if hits:
            pools["exact_term"].append(
                Cand(
                    "exact_term",
                    c.id,
                    p.citation_id,
                    c.chunk_text,
                    a.heading if a else None,
                    rare_terms=hits[:5],
                )
            )

    # near_duplicate: confusable siblings under one parent
    by_parent = defaultdict(list)
    for c, p, a in rows:
        by_parent[p.parent_id].append((c, p, a))
    for sibs in by_parent.values():
        if len(sibs) < 3:
            continue
        for c, p, a in sibs:
            scored = []
            for c2, p2, _ in sibs:
                if c2.id == c.id:
                    continue
                ratio = SequenceMatcher(
                    None, c.chunk_text[:300], c2.chunk_text[:300]
                ).ratio()
                if ratio > 0.5:
                    scored.append((ratio, c2, p2))
            if scored:
                scored.sort(key=lambda t: -t[0])
                pools["near_duplicate"].append(
                    Cand(
                        "near_duplicate",
                        c.id,
                        p.citation_id,
                        c.chunk_text,
                        a.heading if a else None,
                        siblings=[
                            (c2.chunk_text, p2.citation_id) for _, c2, p2 in scored[:3]
                        ],
                    )
                )
    return pools


def generate(client, cand: Cand) -> str:
    if cand.category == "heading_dependent":
        return _chat(
            client,
            HEADING_SYSTEM_PROMPT,
            f"HEADING: {cand.heading}\n\nEXCERPT:\n{cand.chunk_text}\n\n"
            "Write one question.",
        )
    if cand.category == "exact_term":
        return _chat(
            client,
            RARE_TERM_SYSTEM_PROMPT,
            f"Excerpt:\n{cand.chunk_text}\n\n"
            f"Distinctive terms: {', '.join(cand.rare_terms)}\n\nWrite one question.",
        )
    if cand.category == "near_duplicate":
        sim = "\n\n".join(
            f"SIMILAR excerpt {i}:\n{t}" for i, (t, _) in enumerate(cand.siblings, 1)
        )
        return _chat(
            client,
            NEAR_DUP_SYSTEM_PROMPT,
            f"TARGET excerpt:\n{cand.chunk_text}\n\n{sim}\n\nWrite one question.",
        )
    if cand.category == "body_dependent":
        return _chat(
            client,
            BODY_SYSTEM_PROMPT,
            f"Excerpt:\n{cand.chunk_text}\n\nWrite one question.",
        )
    return _chat(
        client,
        CONTROL_SYSTEM_PROMPT,
        f"Excerpt:\n{cand.chunk_text}\n\nWrite one question.",
    )


def category_specific_issue(cand: Cand) -> str | None:
    """The screen that makes each category mean what it claims."""
    q = _toks(cand.question)
    body = _toks(cand.chunk_text)
    # MUST carry >=1 term from the heading that the body does not have -
    # otherwise it is not actually heading-dependent.
    if cand.category == "heading_dependent" and not (q & set(cand.heading_only_terms)):
        return "no_heading_only_term_in_question"
    if cand.category == "body_dependent":
        head_only = set(cand.heading_only_terms) if cand.heading_only_terms else set()
        if cand.heading:
            head_only = _toks(cand.heading) - body
        if not (q & body):
            return "no_body_term_in_question"
        if q & head_only:
            return "leaks_heading_only_term"  # keep the two categories disjoint
    if cand.category == "exact_term" and not any(
        t in cand.question.lower() for t in cand.rare_terms
    ):
        return "distinctive_term_not_used"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    session = SessionLocal()
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        rows = load_rows(session, cv.id)
        pools = build_pools(rows)
        random.seed(42)

        client = _get_client()
        kept: dict[str, list[Cand]] = defaultdict(list)
        drops: Counter = Counter()
        used_citations: set[str] = set()

        for category, target in TARGETS.items():
            pool = pools[category][:]
            random.shuffle(pool)
            budget = target * POOL_MULTIPLIER
            for cand in pool[:budget]:
                if len(kept[category]) >= target:
                    break
                if cand.citation_id in used_citations:
                    continue
                cand.question = generate(client, cand)

                issue = category_specific_issue(cand)
                if issue:
                    drops[f"{category}:{issue}"] += 1
                    continue
                issue = _question_quality_issue(cand.question)
                if issue:
                    drops[f"{category}:{issue}"] += 1
                    continue
                if _is_answerable(client, cand.question, cand.chunk_text) is not True:
                    drops[f"{category}:target_not_answerable"] += 1
                    continue
                if cand.category == "near_duplicate":
                    bad = False
                    for sib_text, sib_cid in cand.siblings:
                        if _is_answerable(client, cand.question, sib_text) is not False:
                            drops[f"near_duplicate:sibling_also_answers:{sib_cid}"] += 1
                            bad = True
                            break
                    if bad:
                        continue

                kept[category].append(cand)
                used_citations.add(cand.citation_id)

        entries = []
        idx = 1
        for category in TARGETS:
            for cand in kept[category]:
                entries.append(
                    {
                        "id": f"gr_{idx:02d}",
                        "question": cand.question,
                        "expected_citation_id": cand.citation_id,
                        "expected_abstention": False,
                        "category": category,
                        "heading": cand.heading,
                        "heading_only_terms": cand.heading_only_terms[:8],
                        "confusable_sibling_ids": [cid for _, cid in cand.siblings],
                    }
                )
                idx += 1
        for q in ABSTENTION_QUESTIONS:
            entries.append(
                {
                    "id": f"gr_{idx:02d}",
                    "question": q,
                    "expected_citation_id": None,
                    "expected_abstention": True,
                    "category": "abstention",
                    "heading": None,
                    "heading_only_terms": [],
                    "confusable_sibling_ids": [],
                }
            )
            idx += 1

        print("=== funnel (kept / target) ===")
        for category, target in TARGETS.items():
            print(
                f"  {category:<20}{len(kept[category])}/{target}   pool={len(pools[category])}"
            )
        print(
            f"  {'abstention':<20}{len(ABSTENTION_QUESTIONS)}/{len(ABSTENTION_QUESTIONS)}"
        )
        print(f"  TOTAL: {len(entries)}")
        print("\n=== drop reasons ===")
        for r, n in drops.most_common(15):
            print(f"  {n:>3}  {r}")

        if args.write:
            OUTPUT_PATH.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False) + "\n"
            )
            print(f"\nwrote {len(entries)} entries -> {OUTPUT_PATH.name}")
        else:
            print("\n(dry run - pass --write to emit the yaml)")
    finally:
        session.close()


if __name__ == "__main__":
    main()
