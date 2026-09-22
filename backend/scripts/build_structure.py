"""Derive the Act's container structure (chapters, sections, their articles,
annexes) from the cached consolidated HTML the corpus was ingested from, and
write it as JSON next to the retriever. Deterministic; re-run after a
re-ingest. The corpus tables record provisions only (no chapter or section
rows), so this file is the retriever's only source for "Section 2 of
Chapter III means Articles 8 to 15".

    python scripts/build_structure.py [data/aiact_02024R1689-20260727.html]
"""

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = ROOT / "data" / "aiact_02024R1689-20260727.html"
OUT = ROOT / "app" / "retrieval" / "structure" / "02024R1689-20260727.json"


def _heading(div) -> str:
    p = div.find("p", class_="title-division-2")
    return " ".join(p.get_text(" ", strip=True).split()) if p else ""


def _articles(div) -> list[str]:
    return [
        d["id"]
        for d in div.find_all("div", class_="eli-subdivision")
        if re.fullmatch(r"art_\d+[a-z]?", d.get("id", ""))
    ]


def build(html_path: Path) -> dict:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "lxml")
    chapters = []
    for cdiv in soup.find_all("div", id=re.compile(r"^cpt_[IVXLC]+$")):
        number = cdiv["id"].split("_")[1]
        sections = []
        for sdiv in cdiv.find_all("div", id=re.compile(rf"^cpt_{number}\.sct_\d+$")):
            sections.append(
                {
                    "id": sdiv["id"],
                    "number": sdiv["id"].split(".sct_")[1],
                    "heading": _heading(sdiv),
                    "articles": _articles(sdiv),
                }
            )
        chapters.append(
            {
                "id": cdiv["id"],
                "number": number,
                "heading": _heading(cdiv),
                "sections": sections,
                "articles": _articles(cdiv),
            }
        )
    annexes = [d["id"] for d in soup.find_all("div", id=re.compile(r"^anx_[IVXLC]+$"))]
    return {
        "source": html_path.name,
        "celex": "02024R1689",
        "consolidated_date": "2026-07-27",
        "chapters": chapters,
        "annexes": annexes,
    }


def main() -> None:
    html_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HTML
    data = build(html_path)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    n_art = sum(len(c["articles"]) for c in data["chapters"])
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(data['chapters'])} chapters, "
        f"{sum(len(c['sections']) for c in data['chapters'])} sections, {n_art} articles, "
        f"{len(data['annexes'])} annexes"
    )


if __name__ == "__main__":
    main()
