"""BM25 index build/load for the AI Act corpus, backed by bm25s.

Why BM25 at all: Stage 1 measured an OR-joined native-FTS lexical leg and
reverted it. It lifted hard-case ranking (MRR 0.335 -> 0.590) but regressed
top-5 precision (control Recall@5 1.000 -> 0.917), because ts_rank_cd has no
IDF term - it cannot know "sandbox" is common in this corpus while "duration"
is rare. BM25's IDF is exactly that missing mechanism. See ADR-7.

The index is a rebuildable file artifact under backend/data/ (gitignored), not
a DB table: it is derived data, binary, and must never drift from the
corpus_version it was built for. The DB stays the source of truth.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import bm25s
import Stemmer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk

INDEX_ROOT = Path(__file__).resolve().parents[2] / "data" / "bm25_index"

# bm25s's default token pattern already drops single characters ((?u)\b\w\w+\b).
STOPWORDS = "en"
TOKEN_PATTERN = r"(?u)\b\w\w+\b"

# Snowball has no "aggressiveness" dial - it is one algorithm - so "light
# stemming" is implemented as Snowball PLUS this passthrough. Each entry was
# chosen from a measured stem-collision analysis over the corpus vocabulary,
# NOT guessed: only terms where stemming fuses two legally DISTINCT AI Act
# concepts are protected. Plain plural folding (model/models, risk/risks,
# importer/importers) is left alone - that is stemming doing its job.
#
# Measured groups that justified each entry (occurrence counts in the corpus):
#   'system'  <- system(408), systems(322), systemic(35)
#       'systemic risk' is a general-purpose-AI-model concept with nothing to
#       do with an 'AI system'; its signal is otherwise swamped 21:1.
#   'notifi'  <- notified(100), notifying(46), notify(20)
#       a 'notified body' (conformity assessment org) and a 'notifying
#       authority' (the member state body that designates it) are different
#       legal entities.
#   'oper'    <- operator(35), operators(21), operation(20), operational(10), ...
#       'operator' is the defined collective role (provider/deployer/importer/
#       distributor); 'operation'/'operational' are ordinary words.
#   'provid'  <- provider(197), providers(111), provided(68), provide(62), ...
#       the highest-frequency case in the Act: the defined role would otherwise
#       match every "information provided" in the corpus.
#   'deploy'  <- deployers(61), deployer(49), deployment(4), ...
#       least contaminated of the four roles, protected for consistency so the
#       defined operator roles behave alike.
#
# Mapped surface -> canonical so singular and plural stay TOGETHER; protecting
# only the singular would split provider/providers, which is worse than the
# merge it was meant to fix.
PROTECTED_TERMS = {
    "systemic": "systemic",
    "notified": "notified",
    "notifying": "notifying",
    "operator": "operator",
    "operators": "operator",
    "provider": "provider",
    "providers": "provider",
    "deployer": "deployer",
    "deployers": "deployer",
}

TOKENIZER_CONFIG = {
    "stemmer": "snowball-english",
    "stopwords": STOPWORDS,
    "token_pattern": TOKEN_PATTERN,
    "lowercase": True,
    "protected_terms": PROTECTED_TERMS,
}


class StaleIndexError(RuntimeError):
    """The on-disk index was built for a different corpus_version.

    Raised rather than tolerated: doc indices would resolve against the wrong
    chunk_id mapping and return confident, WRONG citations - the worst possible
    failure mode for an audit-focused product. A merely absent index is a
    different case and is handled by returning no results.
    """


@dataclass
class LoadedIndex:
    retriever: bm25s.BM25
    chunk_ids: list[int]  # doc_index -> chunk_id
    corpus_version_id: int
    tokenizer_config: dict


_CACHE: dict[int, LoadedIndex] = {}


def index_dir(corpus_version_id: int) -> Path:
    return INDEX_ROOT / f"v{corpus_version_id}"


def _manifest_path(corpus_version_id: int) -> Path:
    return index_dir(corpus_version_id) / "manifest.json"


def make_stemmer():
    """Snowball stemmer with the protected-term passthrough applied.

    bm25s calls this on the unique vocabulary, so the lookup runs once per
    distinct token rather than per occurrence.
    """
    stemmer = Stemmer.Stemmer("english")

    def stem_words(words: list[str]) -> list[str]:
        return [
            PROTECTED_TERMS[w] if w in PROTECTED_TERMS else stemmer.stemWord(w)
            for w in words
        ]

    return stem_words


def tokenize_corpus(texts: list[str]):
    return bm25s.tokenize(
        texts,
        lower=True,
        token_pattern=TOKEN_PATTERN,
        stopwords=STOPWORDS,
        stemmer=make_stemmer(),
        show_progress=False,
    )


def tokenize_query(query: str) -> list[list[str]]:
    """Tokenize with the SAME config the documents used.

    return_ids=False yields plain token strings, which sidesteps the vocab
    mismatch you get from building a fresh id-space for a single query.
    """
    return bm25s.tokenize(
        query,
        lower=True,
        token_pattern=TOKEN_PATTERN,
        stopwords=STOPWORDS,
        stemmer=make_stemmer(),
        return_ids=False,
        show_progress=False,
    )


def fetch_indexable_chunks(
    session: Session, corpus_version_id: int
) -> list[tuple[int, str]]:
    """The chunks BM25 indexes - deliberately the same universe vector_search
    can reach, over the same TEXT vector_search embeds.

    Indexes index_text (contextual prefix + body), NOT chunk_text. This follows
    contextual retrieval (Anthropic, 2024), which prepends context to a chunk
    "before embedding it and before creating the BM25 index" - both indexes, not
    just the dense one. embedder.py already embeds index_text; indexing
    chunk_text here left the sparse leg blind to the article heading.

    That blindness was a measured production bug, not a theoretical one. For
    "What obligations apply to providers of high-risk AI systems?", the gold
    provision art_16.pt_a has a body reading only "ensure that their high-risk
    AI systems are compliant with the requirements set out in Section 2;" - the
    query's two discriminating terms, "obligations" and "providers", appear ONLY
    in the heading "Obligations of providers of high-risk AI systems". BM25 over
    chunk_text ranked it nowhere in its top 50, so RRF dropped it from the fused
    top-5 and the copilot abstained on a question vector-only answered. Over
    index_text it ranks 2nd.

    Measured on a heading-aware eval set: heading-dependent Recall@5 0.867 ->
    1.000 for the sparse leg, with sibling discrimination unchanged (the prefix
    is identical across an article's siblings, so IDF makes it near-inert
    WITHIN an article while still discriminating BETWEEN articles).

    vector_search filters only on corpus_version_id, but a NULL embedding gives
    a NULL cosine distance and Postgres sorts NULLs last, so un-embedded chunks
    are unreachable in practice. Filtering on embedding IS NOT NULL here makes
    both legs draw from an identical candidate set STRUCTURALLY.

    Ordered by id so a rebuild over unchanged data produces an identical index.
    """
    rows = session.execute(
        select(Chunk.id, Chunk.index_text)
        .where(
            Chunk.corpus_version_id == corpus_version_id,
            Chunk.embedding.isnot(None),
        )
        .order_by(Chunk.id)
    ).all()
    return [(r.id, r.index_text) for r in rows]


def build_index(session: Session, corpus_version_id: int) -> dict:
    """Build and persist the index. Idempotent - replaces any existing index
    for this corpus_version."""
    rows = fetch_indexable_chunks(session, corpus_version_id)
    if not rows:
        raise ValueError(f"No indexable chunks for corpus_version {corpus_version_id}")

    chunk_ids = [cid for cid, _ in rows]
    texts = [text for _, text in rows]

    retriever = bm25s.BM25()
    retriever.index(tokenize_corpus(texts), show_progress=False)

    target = index_dir(corpus_version_id)
    if target.exists():
        for child in sorted(target.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        target.rmdir()
    target.mkdir(parents=True)

    retriever.save(str(target), show_progress=False)

    manifest = {
        "corpus_version_id": corpus_version_id,
        "doc_count": len(chunk_ids),
        "chunk_ids": chunk_ids,
        "tokenizer_config": TOKENIZER_CONFIG,
        "bm25s_version": bm25s.__version__,
        "built_at": datetime.now(UTC).isoformat(),
    }
    _manifest_path(corpus_version_id).write_text(json.dumps(manifest, indent=2) + "\n")
    _CACHE.pop(corpus_version_id, None)
    return manifest


def load_index(corpus_version_id: int) -> LoadedIndex | None:
    """Load (and cache) the index. Returns None when absent; raises
    StaleIndexError when the manifest is for a different corpus_version."""
    cached = _CACHE.get(corpus_version_id)
    if cached is not None:
        return cached

    manifest_path = _manifest_path(corpus_version_id)
    if not manifest_path.exists():
        return None

    manifest = json.loads(manifest_path.read_text())
    if manifest["corpus_version_id"] != corpus_version_id:
        raise StaleIndexError(
            f"Index at {index_dir(corpus_version_id)} was built for "
            f"corpus_version {manifest['corpus_version_id']}, not "
            f"{corpus_version_id}. Its chunk_id mapping would resolve to the "
            "wrong rows - rebuild with scripts/build_bm25_index.py."
        )

    loaded = LoadedIndex(
        retriever=bm25s.BM25.load(
            str(index_dir(corpus_version_id)), show_progress=False
        ),
        chunk_ids=manifest["chunk_ids"],
        corpus_version_id=corpus_version_id,
        tokenizer_config=manifest["tokenizer_config"],
    )
    _CACHE[corpus_version_id] = loaded
    return loaded
