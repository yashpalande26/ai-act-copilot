"""PROTOTYPE (22 Sep 2026): the Act navigator. Read-only, deterministic, free.

  GET /act/definitions?q=   the Article 3 definitions, verbatim, filtered
  GET /act/provisions/{id}  one provision with its verbatim text and the
                            cross-references derived from the text itself

Cross-references are parsed from the provision wording ("Article 6(2)",
"Annex III") and resolved against citation ids that exist in the corpus; the
provision_reference table is empty in this corpus version, so nothing is
read from it. No LLM, no writes, no quota. Same service-token gate and
per-minute limit as every other endpoint. Sits alongside the core flows and
can be removed by deleting this file and its include in main.py.
"""

import re
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import Caller, DbSession, ServiceToken
from app.assessment.report import _Corpus
from app.assessment.schema import ProvisionText
from app.config import PER_MINUTE_LIMIT
from app.rate_limit import limiter

router = APIRouter(prefix="/act")

_TERM = re.compile(r"^[‘'\"“]([^’'\"”]+)[’'\"”]\s+means\b", re.IGNORECASE)
_ARTICLE_REF = re.compile(
    r"\bArticles?\s+(\d+[a-z]?)(?:\((\d+[a-z]?)\))?(?:\s*(?:,|and|to)\s*(\d+[a-z]?)(?:\((\d+[a-z]?)\))?)*",
    re.IGNORECASE,
)
_ANNEX_REF = re.compile(r"\bAnnex(?:es)?\s+([IVXLC]+)\b")


class Definition(BaseModel):
    citation_id: str
    citation_label: str
    term: str
    text: str


class DefinitionList(BaseModel):
    corpus_consolidated_date: str
    total: int
    definitions: list[Definition]


class Reference(BaseModel):
    citation_id: str
    citation_label: str
    snippet: str  # the sentence fragment that carries the reference, verbatim


class ProvisionView(BaseModel):
    provision: ProvisionText
    parent: ProvisionText | None
    references: list[Reference]  # what this provision points at
    referenced_by: list[Reference]  # provisions whose text points here
    corpus_consolidated_date: str


def _term_of(text: str) -> str | None:
    m = _TERM.match(text.strip())
    return m.group(1).strip() if m else None


def _article_root(cid: str) -> str:
    return cid.split(".")[0]


def _refs_in(text: str) -> set[str]:
    """Citation roots a passage refers to: art_N and anx_X, resolved later."""
    out: set[str] = set()
    for m in _ARTICLE_REF.finditer(text):
        for g in (m.group(1), m.group(3)):
            if g:
                out.add(f"art_{g.lower()}")
    for m in _ANNEX_REF.finditer(text):
        out.add(f"anx_{m.group(1)}")
    return out


def _snippet(text: str, needle: re.Pattern[str], width: int = 140) -> str:
    m = needle.search(text)
    if not m:
        return text[:width]
    start = max(0, m.start() - width // 2)
    end = min(len(text), m.end() + width // 2)
    return (
        ("..." if start else "")
        + text[start:end].strip()
        + ("..." if end < len(text) else "")
    )


@lru_cache(maxsize=4)
def _reference_index(corpus_key: tuple[int, int]) -> dict[str, list[tuple[str, str]]]:
    """root citation -> [(referring citation_id, verbatim snippet)]. Keyed by
    (corpus_version_id, provision count) so a re-ingest invalidates it."""
    return {}


def _build_index(corpus: _Corpus) -> dict[str, list[tuple[str, str]]]:
    key = (corpus.version.id, len(corpus.by_id))
    cached = _reference_index(key)
    if cached:
        return cached
    index: dict[str, list[tuple[str, str]]] = {}
    for cid, row in corpus.by_id.items():
        text = row.text_content or ""
        for root in _refs_in(text):
            if root not in corpus.by_id or root == _article_root(cid):
                continue  # unknown target, or a provision citing its own article
            pat = re.compile(
                (r"\bArticles?\s+" + re.escape(root[4:]) + r"\b")
                if root.startswith("art_")
                else (r"\bAnnex(?:es)?\s+" + re.escape(root[4:]) + r"\b")
            )
            index.setdefault(root, []).append((cid, _snippet(text, pat)))
    cached.update(index)
    return cached


@router.get("/definitions", response_model=DefinitionList)
@limiter.limit(PER_MINUTE_LIMIT)
def definitions(
    request: Request,  # required by slowapi to key the limiter
    q: str = "",
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> DefinitionList:
    try:
        corpus = _Corpus(session)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        ) from exc
    needle = q.strip().lower()
    out: list[Definition] = []
    for cid, row in sorted(corpus.by_id.items(), key=lambda kv: kv[1].ordinal or 0):
        if not re.fullmatch(r"art_3\.pt_[0-9a-z]+", cid):
            continue
        text = row.text_content or ""
        term = _term_of(text)
        if term is None:
            continue
        if needle and needle not in term.lower() and needle not in text.lower():
            continue
        node = corpus.node(cid, "self")
        out.append(
            Definition(
                citation_id=cid,
                citation_label=node.citation_label,
                term=term,
                text=text,
            )
        )
    return DefinitionList(
        corpus_consolidated_date=str(corpus.version.consolidated_date),
        total=len(out),
        definitions=out,
    )


@router.get("/provisions/{citation_id}", response_model=ProvisionView)
@limiter.limit(PER_MINUTE_LIMIT)
def provision(
    request: Request,  # required by slowapi to key the limiter
    citation_id: str,
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> ProvisionView:
    try:
        corpus = _Corpus(session)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        ) from exc
    row = corpus.by_id.get(citation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="provision_not_found"
        )
    node = corpus.node(citation_id, "full")
    parent_id = ".".join(citation_id.split(".")[:-1]) if "." in citation_id else None
    parent = (
        corpus.node(parent_id, "self")
        if parent_id and parent_id in corpus.by_id
        else None
    )

    own_text = " ".join(
        [row.text_content or ""]
        + [
            corpus.by_id[c].text_content or ""
            for c in corpus.by_id
            if c.startswith(citation_id + ".")
        ]
    )
    references: list[Reference] = []
    for root in sorted(_refs_in(own_text)):
        if root in corpus.by_id and root != _article_root(citation_id):
            n = corpus.node(root, "self")
            pat = re.compile(
                (r"\bArticles?\s+" + re.escape(root[4:]) + r"\b")
                if root.startswith("art_")
                else (r"\bAnnex(?:es)?\s+" + re.escape(root[4:]) + r"\b")
            )
            references.append(
                Reference(
                    citation_id=root,
                    citation_label=n.citation_label,
                    snippet=_snippet(own_text, pat),
                )
            )

    index = _build_index(corpus)
    referenced_by = [
        Reference(
            citation_id=cid,
            citation_label=corpus.node(cid, "self").citation_label,
            snippet=snip,
        )
        for cid, snip in index.get(_article_root(citation_id), [])[:60]
    ]
    return ProvisionView(
        provision=node,
        parent=parent,
        references=references,
        referenced_by=referenced_by,
        corpus_consolidated_date=str(corpus.version.consolidated_date),
    )
