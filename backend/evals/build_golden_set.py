import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import CorpusVersion, Provision
from app.db.session import SessionLocal
from app.generation.answer import CHAT_MODEL
from app.ingestion.chunker import LEAF_UNIT_TYPES
from app.ingestion.embedder import _get_client

MIN_TEXT_LENGTH = 200  # chars; excludes short stub-like leaf provisions
TARGET_ANSWERABLE = 12

QUESTION_SYSTEM_PROMPT = (
    "You write natural-language questions for an EU AI Act quiz. Given a short "
    "excerpt from the Act, write ONE clear, natural-language question whose "
    "answer is directly contained in the excerpt. Do not mention article, "
    "paragraph, or point numbers in the question itself. Return ONLY the "
    "question text, nothing else - no quotes, no preamble."
)

# Hand-authored, not LLM-generated: built around distinctive multi-word legal
# phrases lifted verbatim from real, DB-verified provision text, so lexical
# search has a fair chance to actually contribute (the 12 semantic questions
# above are LLM-paraphrased, which vector search wins by construction).
LEXICAL_QUESTIONS = [
    {
        "question": (
            "Is it prohibited to place on the market an AI system that deploys "
            "subliminal techniques beyond a person's consciousness to distort "
            "someone's behaviour?"
        ),
        "expected_citation_id": "art_5.par_1.pt_a",
    },
    {
        "question": "What is the definition of a 'biometric categorisation system' under the AI Act?",
        "expected_citation_id": "art_3.pt_40",
    },
    {
        "question": (
            "Can a deployer rely on a previously conducted fundamental rights "
            "impact assessment instead of carrying out a new one for similar cases?"
        ),
        "expected_citation_id": "art_27.par_2",
    },
    {
        "question": "Are providers of high-risk AI systems required to put a quality management system in place?",
        "expected_citation_id": "art_17.par_1",
    },
]

OFF_TOPIC_QUESTIONS = [
    "What is the capital of France?",
    "What's the best pizza place in Dublin?",
    "How do I train a dog to sit?",
    "What's the weather like today?",
]


def _generate_question(client, provision: Provision) -> str:
    user_prompt = (
        f"Excerpt ({provision.citation_id}):\n{provision.text_content}\n\n"
        "Write one question answerable from this excerpt."
    )
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": QUESTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def main() -> None:
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

        rows = (
            session.execute(
                select(Provision).where(
                    Provision.corpus_version_id == latest.id,
                    Provision.unit_type.in_(LEAF_UNIT_TYPES),
                )
            )
            .scalars()
            .all()
        )
        known_ids = {p.citation_id for p in rows}
        for item in LEXICAL_QUESTIONS:
            if item["expected_citation_id"] not in known_ids:
                raise ValueError(
                    f"Lexical question source {item['expected_citation_id']!r} "
                    "not found in this corpus_version"
                )

        lexical_source_ids = {q["expected_citation_id"] for q in LEXICAL_QUESTIONS}
        qualifying = [
            p
            for p in rows
            if len(p.text_content.strip()) >= MIN_TEXT_LENGTH
            and p.citation_id not in lexical_source_ids
        ]

        by_top_level: dict[str, list[Provision]] = defaultdict(list)
        for p in qualifying:
            by_top_level[p.citation_id.split(".")[0]].append(p)

        random.seed(42)  # reproducible sampling if this build script is re-run
        keys = list(by_top_level)
        random.shuffle(keys)
        selected = [random.choice(by_top_level[k]) for k in keys[:TARGET_ANSWERABLE]]

        client = _get_client()
        entries = []
        idx = 1

        for provision in selected:
            question = _generate_question(client, provision)
            entries.append(
                {
                    "id": f"gs_{idx:02d}",
                    "question": question,
                    "expected_citation_id": provision.citation_id,
                    "expected_abstention": False,
                }
            )
            idx += 1

        for item in LEXICAL_QUESTIONS:
            entries.append(
                {
                    "id": f"gs_{idx:02d}",
                    "question": item["question"],
                    "expected_citation_id": item["expected_citation_id"],
                    "expected_abstention": False,
                }
            )
            idx += 1

        for question in OFF_TOPIC_QUESTIONS:
            entries.append(
                {
                    "id": f"gs_{idx:02d}",
                    "question": question,
                    "expected_citation_id": None,
                    "expected_abstention": True,
                }
            )
            idx += 1

        output_path = Path(__file__).resolve().parent / "golden_set.yaml"
        output_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
        print(f"Wrote {len(entries)} entries to {output_path}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
