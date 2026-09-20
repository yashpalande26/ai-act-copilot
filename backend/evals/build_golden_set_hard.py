"""Builds a DISCRIMINATING golden eval set (golden_set_hard.yaml).

The existing golden_set.yaml scores 1.000 on everything, so it cannot separate
vector-only from hybrid retrieval. This builder manufactures candidates from two
sources that are structurally hard for semantic search (near-duplicate sibling
provisions, rare-term provisions), then keeps only the ones that survive a
three-way discrimination screen AND that vector-only actually gets wrong.

Two-phase by design:
  python -m evals.build_golden_set_hard            # propose: prints + writes scratch JSON
  python -m evals.build_golden_set_hard --write    # freeze: scratch JSON -> golden_set_hard.yaml

The scratch file guarantees that what was reviewed is byte-for-byte what gets
written - --write never regenerates anything.
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

from app.db.models import CorpusVersion, Provision
from app.db.session import SessionLocal
from app.generation.answer import CHAT_MODEL
from app.ingestion.chunker import LEAF_UNIT_TYPES
from app.ingestion.embedder import _get_client
from app.retrieval.search import keyword_search, vector_search
from evals.judge import JUDGE_MODEL

EVALS_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = EVALS_DIR / "golden_set_hard.yaml"
SCRATCH_PATH = EVALS_DIR / "_hard_candidates_scratch.json"

MIN_TEXT_LENGTH = 150
SIMILARITY_THRESHOLD = 0.5
MAX_SIBLINGS_PER_TARGET = 3
# 6 exhausts the corpus: the near-duplicate pool tops out at 57 candidates no
# matter how high this goes (measured - raising it to 99 adds nothing).
MAX_TARGETS_PER_PARENT = 6
RARE_WORD_DOC_FREQ = 2
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]{5,}")

# Both set above what the pools can actually supply / need, so neither truncates:
# the near-dup pool is corpus-capped at 57, and rare-term has 535 available.
NEAR_DUP_POOL = 100
RARE_TERM_POOL = 535
CONTROL_POOL = 25

TARGET_NEAR_DUP = 18
TARGET_EXACT_TERM = 25
TARGET_CONTROL = 12

# An eval question must stand on its own as something a user would actually type.
# Two defects seen in the first build, both caught here before anything is kept:
#   - "mentioned in the excerpt" / "according to the excerpt" - the question
#     refers to a document the user cannot see
#   - a leaked structural reference ("paragraph 3, second subparagraph",
#     "requirements of Annex VII") - every generation prompt forbids these, but
#     the model complies only most of the time
# Calibrated against the 34 questions of the first build: these two patterns flag
# exactly the 5 defective ones and produce no false positives on the other 29.
EXCERPT_RE = re.compile(r"\bexcerpt\b", re.IGNORECASE)
STRUCT_REF_RE = re.compile(
    r"\b(article|paragraph|subparagraph|annex|point|section|chapter)\s+"
    r"([0-9IVXivx(]|\W*\b(of|referred)\b)",
    re.IGNORECASE,
)

# Quoted-amendment text (ADR-004 / DECISIONS.md): these articles amend OTHER
# regulations, so their "paragraphs" are quoted foreign text. art_108's
# near-duplicates made two different targets produce the identical question in
# the earlier probe; art_107 additionally has a mangled citation_id
# (art_107.par_'4, with a stray curly quote from the source HTML). Neither is
# sound eval material - the label itself is unreliable.
EXCLUDED_TOP_LEVEL = {"art_107", "art_108"}

NEAR_DUP_SYSTEM_PROMPT = """\
You write natural-language questions for an EU AI Act eval set. You will be
given a TARGET excerpt and one or more SIMILAR excerpts that are easy to
confuse with it.

Write ONE clear, natural-language question that:
- is fully answerable from the TARGET excerpt alone
- is NOT answerable from any of the SIMILAR excerpts
- turns on the specific detail that makes the TARGET different from them
  (a distinct term, number, actor, condition, or cross-reference)

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

# Verbatim from build_golden_set.py - clean, easy questions are exactly what the
# existing prompt already produces, and the control tier wants nothing more.
CONTROL_SYSTEM_PROMPT = (
    "You write natural-language questions for an EU AI Act quiz. Given a short "
    "excerpt from the Act, write ONE clear, natural-language question whose "
    "answer is directly contained in the excerpt. Do not mention article, "
    "paragraph, or point numbers in the question itself. Return ONLY the "
    "question text, nothing else - no quotes, no preamble."
)

ANSWERABLE_SYSTEM_PROMPT = """\
You are checking whether a question can be answered from a single excerpt of
the EU AI Act.

You will be given a QUESTION and one EXCERPT. Decide whether the excerpt on
its own contains the specific information needed to answer that question
fully. Being merely on the same topic is NOT enough - the excerpt must
actually contain the answer.

You do not know where the excerpt came from or whether it is the intended
source. Judge only what is in front of you.

Respond with ONLY strict JSON, no other text, in this exact shape:
{"rationale": "<one sentence>", "answerable": true or false}
"""

ABSTENTION_QUESTIONS = [
    # The 4 already in golden_set.yaml, verbatim.
    "What is the capital of France?",
    "What's the best pizza place in Dublin?",
    "How do I train a dog to sit?",
    "What's the weather like today?",
    # 2 new, same spirit: plainly outside the corpus.
    "How do I bake sourdough bread at home?",
    "Who won the most recent football World Cup?",
]


@dataclass
class Candidate:
    category: str  # "near_duplicate" | "exact_term" | "control"
    provision: Provision
    siblings: list[Provision] = field(default_factory=list)
    rare_terms: list[str] = field(default_factory=list)
    question: str | None = None
    vector_rank: int | None = None  # 1-indexed within top-10, None = absent
    rank1_citation_id: str | None = None
    rank1_heading: str | None = None
    rank1_text: str | None = None
    lexical_result_count: int | None = None
    lexical_found_gold: bool | None = None
    drop_reason: str | None = None


def _chat(client, model: str, system_prompt: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def _generate_question(client, candidate: Candidate) -> str:
    if candidate.category == "near_duplicate":
        similar = "\n\n".join(
            f"SIMILAR excerpt {i}:\n{s.text_content}"
            for i, s in enumerate(candidate.siblings, start=1)
        )
        user_prompt = (
            f"TARGET excerpt:\n{candidate.provision.text_content}\n\n"
            f"{similar}\n\n"
            "Write one question answerable only from the TARGET."
        )
        return _chat(client, CHAT_MODEL, NEAR_DUP_SYSTEM_PROMPT, user_prompt)

    if candidate.category == "exact_term":
        user_prompt = (
            f"Excerpt:\n{candidate.provision.text_content}\n\n"
            f"Distinctive terms: {', '.join(candidate.rare_terms)}\n\n"
            "Write one question answerable from this excerpt that uses at "
            "least one distinctive term verbatim."
        )
        return _chat(client, CHAT_MODEL, RARE_TERM_SYSTEM_PROMPT, user_prompt)

    user_prompt = (
        f"Excerpt ({candidate.provision.citation_id}):\n"
        f"{candidate.provision.text_content}\n\n"
        "Write one question answerable from this excerpt."
    )
    return _chat(client, CHAT_MODEL, CONTROL_SYSTEM_PROMPT, user_prompt)


def _question_quality_issue(question: str) -> str | None:
    """Free, deterministic screen run before any retrieval or judging. Returns a
    drop reason, or None if the question is usable as a standalone user query."""
    if EXCERPT_RE.search(question):
        return "question_refers_to_the_excerpt"
    match = STRUCT_REF_RE.search(question)
    if match:
        return f"question_leaks_structural_reference:{match.group(0).strip()}"
    return None


def _is_answerable(client, question: str, excerpt: str) -> bool | None:
    """Blind binary check. Returns None on a parse failure - callers treat that
    as 'unknown' and drop the candidate rather than admitting something
    unverified into the set."""
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": ANSWERABLE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"QUESTION:\n{question}\n\nEXCERPT:\n{excerpt}",
            },
        ],
    )
    raw = response.choices[0].message.content
    try:
        data = json.loads((raw or "").strip())
        value = data["answerable"]
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() == "true"
        return None
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _load_provisions(session, corpus_version_id: int) -> list[Provision]:
    rows = (
        session.execute(
            select(Provision).where(
                Provision.corpus_version_id == corpus_version_id,
                Provision.unit_type.in_(LEAF_UNIT_TYPES),
            )
        )
        .scalars()
        .all()
    )
    return [
        p
        for p in rows
        if len(p.text_content.strip()) >= MIN_TEXT_LENGTH
        and p.citation_id.split(".")[0] not in EXCLUDED_TOP_LEVEL
    ]


def _build_near_dup_pool(rows: list[Provision]) -> list[Candidate]:
    by_parent: dict[int | None, list[Provision]] = defaultdict(list)
    for p in rows:
        by_parent[p.parent_id].append(p)

    pool: list[Candidate] = []
    for sibs in by_parent.values():
        if len(sibs) < 3:
            continue
        per_parent: list[Candidate] = []
        for target in sibs:
            scored = []
            for other in sibs:
                if other.id == target.id:
                    continue
                ratio = SequenceMatcher(
                    None, target.text_content[:300], other.text_content[:300]
                ).ratio()
                if ratio > SIMILARITY_THRESHOLD:
                    scored.append((ratio, other))
            if not scored:
                continue
            scored.sort(key=lambda t: t[0], reverse=True)
            per_parent.append(
                Candidate(
                    category="near_duplicate",
                    provision=target,
                    siblings=[p for _, p in scored[:MAX_SIBLINGS_PER_TARGET]],
                )
            )
        pool.extend(per_parent[:MAX_TARGETS_PER_PARENT])
    return pool


def _build_rare_term_pool(rows: list[Provision]) -> list[Candidate]:
    doc_freq: Counter = Counter()
    words_by_id: dict[str, set[str]] = {}
    for p in rows:
        words = {w.lower() for w in WORD_RE.findall(p.text_content)}
        words_by_id[p.citation_id] = words
        doc_freq.update(words)

    rare = {w for w, c in doc_freq.items() if c <= RARE_WORD_DOC_FREQ}

    scored: list[tuple[int, Provision, list[str]]] = []
    for p in rows:
        hits = sorted(words_by_id[p.citation_id] & rare)
        if hits:
            scored.append((len(hits), p, hits[:5]))
    scored.sort(key=lambda t: t[0], reverse=True)

    return [
        Candidate(category="exact_term", provision=p, rare_terms=terms)
        for _, p, terms in scored
    ]


def _build_control_pool(rows: list[Provision], used: set[str]) -> list[Candidate]:
    by_top_level: dict[str, list[Provision]] = defaultdict(list)
    for p in rows:
        if p.citation_id not in used:
            by_top_level[p.citation_id.split(".")[0]].append(p)

    pool = []
    for key in sorted(by_top_level):
        pool.append(
            Candidate(category="control", provision=random.choice(by_top_level[key]))
        )
    random.shuffle(pool)
    return pool


def _screen_vector(session, candidate: Candidate, corpus_version_id: int) -> None:
    hits = vector_search(
        session, candidate.question, corpus_version_id, top_k=10, min_similarity=0.0
    )
    gold = candidate.provision.citation_id
    candidate.vector_rank = next(
        (i for i, r in enumerate(hits, start=1) if r.citation_id == gold), None
    )
    if hits:
        candidate.rank1_citation_id = hits[0].citation_id
        candidate.rank1_heading = hits[0].article_heading
        candidate.rank1_text = hits[0].chunk_text


def _record_lexical_baseline(
    session, candidate: Candidate, corpus_version_id: int
) -> None:
    hits = keyword_search(session, candidate.question, corpus_version_id, top_k=10)
    candidate.lexical_result_count = len(hits)
    candidate.lexical_found_gold = any(
        r.citation_id == candidate.provision.citation_id for r in hits
    )


def _passes_rank_filter(candidate: Candidate) -> bool:
    """Hard tiers want vector-only to get it wrong: gold at rank 2+ or outside
    the top 5. Control tier wants the opposite - gold at rank 1."""
    if candidate.category == "control":
        return candidate.vector_rank == 1
    return candidate.vector_rank is None or candidate.vector_rank >= 2


def _passes_discrimination(client, candidate: Candidate) -> bool:
    """Three blind checks. Any None (parse failure) drops the candidate."""
    target_ok = _is_answerable(
        client, candidate.question, candidate.provision.text_content
    )
    if target_ok is not True:
        candidate.drop_reason = (
            "target_not_answerable"
            if target_ok is False
            else "target_check_unparseable"
        )
        return False

    for sibling in candidate.siblings:
        sibling_ok = _is_answerable(client, candidate.question, sibling.text_content)
        if sibling_ok is not False:
            candidate.drop_reason = (
                f"sibling_also_answers:{sibling.citation_id}"
                if sibling_ok is True
                else "sibling_check_unparseable"
            )
            return False

    # The sharpest filter: test the question against what actually beat it.
    if candidate.category != "control" and candidate.rank1_text is not None:
        distractor_ok = _is_answerable(client, candidate.question, candidate.rank1_text)
        if distractor_ok is not False:
            candidate.drop_reason = (
                f"rank1_also_answers:{candidate.rank1_citation_id}"
                if distractor_ok is True
                else "rank1_check_unparseable"
            )
            return False

    return True


def _to_entry(candidate: Candidate, index: int) -> dict:
    return {
        "id": f"gh_{index:02d}",
        "question": candidate.question,
        "expected_citation_id": candidate.provision.citation_id,
        "expected_abstention": False,
        "category": candidate.category,
        "confusable_sibling_ids": [s.citation_id for s in candidate.siblings],
        "build_provenance": {
            "vector_only_rank": candidate.vector_rank,
            "vector_only_rank1_citation_id": candidate.rank1_citation_id,
            "lexical_result_count": candidate.lexical_result_count,
            "lexical_found_gold": candidate.lexical_found_gold,
        },
    }


def _print_proposal(
    entries: list[dict], candidates_by_id: dict[str, Candidate], funnel: dict
) -> None:
    print(
        "=== Funnel (pool -> generated -> quality -> rank filter -> discrimination -> kept) ==="
    )
    print(
        f"{'category':<16}{'pool':<7}{'gen':<7}{'qual':<7}"
        f"{'vec@1':<7}{'rank':<7}{'disc':<7}kept"
    )
    for category in ("near_duplicate", "exact_term", "control"):
        f = funnel[category]
        print(
            f"{category:<16}{f['pool']:<7}{f['generated']:<7}{f['quality']:<7}"
            f"{f['vector_rank1']:<7}{f['rank_filter']:<7}{f['discrimination']:<7}{f['kept']}"
        )
    print(
        "\nvec@1 = candidates where vector-only already ranked gold #1. For the hard\n"
        "tiers that is the negative finding, not a pass: a sibling-aware question that\n"
        "names the distinguishing detail is one semantic search handles correctly."
    )

    print("\n=== Drop reasons (discrimination screen) ===")
    reasons = funnel["drop_reasons"]
    if reasons:
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>3}  {reason}")
    else:
        print("  (none)")

    for category in ("near_duplicate", "exact_term", "control", "abstention"):
        rows = [e for e in entries if e["category"] == category]
        print(f"\n=== {category} ({len(rows)} entries) ===")
        if not rows:
            f = funnel.get(category, {})
            # Denominator is the quality-passing count, NOT `generated`: vec@1 is
            # only measured on candidates that actually reached the vector screen.
            print(
                "  DECLARED EMPTY - the category is retained deliberately, not deleted.\n"
                f"  Of {f.get('generated', 0)} candidates generated, {f.get('quality', 0)} passed the question-quality\n"
                f"  screen and were put to vector-only retrieval. {f.get('vector_rank1', 0)} of those {f.get('quality', 0)} were\n"
                "  already ranked #1 - once the question names the detail distinguishing the\n"
                "  target from its near-twin, semantic search finds it. The rest failed the\n"
                "  discrimination screen. Evidence against the 'near-duplicates break vector\n"
                "  search' hypothesis, recorded here rather than papered over."
            )
        for entry in rows:
            print(f"\n{entry['id']}  [{entry['category']}]")
            print(f'  question: "{entry["question"]}"')
            if entry["expected_abstention"]:
                print("  expected: ABSTENTION (no citation)")
                continue
            print(f"  expected_citation_id: {entry['expected_citation_id']}")
            prov = entry["build_provenance"]
            rank = prov["vector_only_rank"]
            print(f"  vector_only_rank: {rank if rank else 'missed (not in top 10)'}")
            candidate = candidates_by_id[entry["id"]]
            if entry["confusable_sibling_ids"]:
                print(
                    f"  must beat sibling(s): {', '.join(entry['confusable_sibling_ids'])}"
                )
            if prov["vector_only_rank1_citation_id"] and rank != 1:
                heading = (
                    f" [{candidate.rank1_heading}]" if candidate.rank1_heading else ""
                )
                snippet = (candidate.rank1_text or "")[:140].replace("\n", " ")
                print(
                    f"  vector rank 1 instead: {prov['vector_only_rank1_citation_id']}{heading}"
                )
                print(f'    "{snippet}..."')
            print(
                f"  lexical baseline: {prov['lexical_result_count']} results, "
                f"gold found: {prov['lexical_found_gold']}"
            )


def propose() -> None:
    session = SessionLocal()
    try:
        latest = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        if latest is None:
            print("No corpus_version found. Run ingest.py first.", file=sys.stderr)
            sys.exit(1)

        rows = _load_provisions(session, latest.id)
        random.seed(42)

        near_dup_pool = _build_near_dup_pool(rows)
        rare_term_pool = _build_rare_term_pool(rows)
        random.shuffle(near_dup_pool)

        hard_ids = {c.provision.citation_id for c in near_dup_pool[:NEAR_DUP_POOL]}
        hard_ids |= {c.provision.citation_id for c in rare_term_pool[:RARE_TERM_POOL]}
        control_pool = _build_control_pool(rows, hard_ids)

        pools = {
            "near_duplicate": near_dup_pool[:NEAR_DUP_POOL],
            "exact_term": rare_term_pool[:RARE_TERM_POOL],
            "control": control_pool[:CONTROL_POOL],
        }
        targets = {
            "near_duplicate": TARGET_NEAR_DUP,
            "exact_term": TARGET_EXACT_TERM,
            "control": TARGET_CONTROL,
        }

        client = _get_client()
        funnel: dict = {
            c: {
                "pool": len(pools[c]),
                "generated": 0,
                "quality": 0,
                "vector_rank1": 0,
                "rank_filter": 0,
                "discrimination": 0,
                "kept": 0,
            }
            for c in pools
        }
        funnel["drop_reasons"] = Counter()

        kept: dict[str, list[Candidate]] = {c: [] for c in pools}
        seen_citation_ids: set[str] = set()

        for category, pool in pools.items():
            for candidate in pool:
                if len(kept[category]) >= targets[category]:
                    break
                if candidate.provision.citation_id in seen_citation_ids:
                    continue

                candidate.question = _generate_question(client, candidate)
                funnel[category]["generated"] += 1

                if category == "exact_term" and not any(
                    t in candidate.question.lower() for t in candidate.rare_terms
                ):
                    funnel["drop_reasons"]["distinctive_term_not_used"] += 1
                    continue

                issue = _question_quality_issue(candidate.question)
                if issue is not None:
                    funnel["drop_reasons"][issue] += 1
                    continue
                funnel[category]["quality"] += 1

                _screen_vector(session, candidate, latest.id)
                if candidate.vector_rank == 1:
                    funnel[category]["vector_rank1"] += 1
                if not _passes_rank_filter(candidate):
                    continue
                funnel[category]["rank_filter"] += 1

                if not _passes_discrimination(client, candidate):
                    funnel["drop_reasons"][candidate.drop_reason] += 1
                    continue
                funnel[category]["discrimination"] += 1

                _record_lexical_baseline(session, candidate, latest.id)
                kept[category].append(candidate)
                seen_citation_ids.add(candidate.provision.citation_id)
                funnel[category]["kept"] += 1

        entries: list[dict] = []
        candidates_by_id: dict[str, Candidate] = {}
        index = 1
        for category in ("near_duplicate", "exact_term", "control"):
            for candidate in kept[category]:
                entry = _to_entry(candidate, index)
                entries.append(entry)
                candidates_by_id[entry["id"]] = candidate
                index += 1

        for question in ABSTENTION_QUESTIONS:
            entries.append(
                {
                    "id": f"gh_{index:02d}",
                    "question": question,
                    "expected_citation_id": None,
                    "expected_abstention": True,
                    "category": "abstention",
                    "confusable_sibling_ids": [],
                    "build_provenance": {},
                }
            )
            index += 1

        _print_proposal(entries, candidates_by_id, funnel)

        # The scratch file carries the full build record - funnel included - so the
        # near_duplicate negative finding survives alongside the entries it explains.
        # The emitted yaml stays a flat list, which is what run_eval's json.loads
        # iterates over.
        record = {
            "funnel": {
                c: funnel[c] for c in ("near_duplicate", "exact_term", "control")
            },
            "drop_reasons": dict(funnel["drop_reasons"]),
            "entries": entries,
        }
        SCRATCH_PATH.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print(
            f"\n--- {len(entries)} proposed entries written to {SCRATCH_PATH.name} ---"
        )
        print(
            "Nothing written to golden_set_hard.yaml yet. Review, then re-run with --write."
        )
    finally:
        session.close()


def write_from_scratch() -> None:
    if not SCRATCH_PATH.exists():
        print(
            f"No scratch file at {SCRATCH_PATH}. Run without --write first.",
            file=sys.stderr,
        )
        sys.exit(1)
    entries = json.loads(SCRATCH_PATH.read_text())["entries"]
    OUTPUT_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(entries)} entries to {OUTPUT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Emit golden_set_hard.yaml verbatim from the reviewed scratch file.",
    )
    args = parser.parse_args()
    if args.write:
        write_from_scratch()
    else:
        propose()


if __name__ == "__main__":
    main()
