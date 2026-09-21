"""Self-contained HTML export of a saved assessment (Phase 3, option C).

One deterministic renderer over the same AssessmentResult the API returns:
provision text goes database -> build_report -> this file, never through the
frontend. The output is a single HTML document with inline CSS, no scripts,
no external assets (fonts fall back to local stacks), a print stylesheet, and
the design tokens copied in as literal values. Same input, same bytes.

Rendered with the standard library only: the layout is a header plus nested
lists, which html.escape handles without a template engine. Every string
that came from the database or the user passes through esc().

Reopened assessments render provision text live from the current corpus;
this export inherits that (known limitation, unchanged).
"""

from datetime import datetime
from html import escape

from app.assessment.schema import (
    AssessmentResult,
    ObligationGroup,
    PenaltyLine,
    ProvisionText,
)

EURLEX = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727"
)

HEADLINE_LABEL = {
    "OUT_OF_SCOPE": "Outside the Regulation's scope",
    "PROHIBITED_FLAG": "Prohibited-practice red flag",
    "HIGH_RISK": "High-risk (Article 6(2))",
    "HIGH_RISK_POSSIBLE": "Possibly high-risk (Article 6(1))",
    "TRANSPARENCY": "Transparency obligations apply",
    "MINIMAL": "No high-risk or transparency category matched",
}
ROLE_LABEL = {
    "provider": "Provider",
    "deployer": "Deployer",
    "importer": "Importer",
    "distributor": "Distributor",
    "authorised_representative": "Authorised representative",
    "all": "All operators",
    "voluntary": "Voluntary",
}

# Light-theme design tokens from frontend/app/globals.css, as literals.
CSS = """
:root{--paper:oklch(0.985 0.004 85);--surface:oklch(1 0 0);--hairline:oklch(0.906 0.006 85);
--ink:oklch(0.215 0.032 258);--ink-soft:oklch(0.468 0.026 258);--ink-faint:oklch(0.498 0.023 258);
--grounded:oklch(0.505 0.113 162);--grounded-soft:oklch(0.962 0.024 162);
--caution:oklch(0.615 0.126 72);--caution-soft:oklch(0.968 0.032 72);}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.68 Geist,system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
main{max-width:46rem;margin:0 auto;padding:2.5rem 1.5rem 4rem}
h1{font:400 2.25rem/1.12 "Instrument Serif",Georgia,serif;letter-spacing:-.018em;margin:.5rem 0 0}
h2{font-size:1.1875rem;line-height:1.4;font-weight:560;margin:2.5rem 0 .75rem}
h3{font-size:1.0625rem;font-weight:560;margin:1.25rem 0 .5rem}
.eyebrow{font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;font-weight:560;color:var(--ink-faint)}
.meta{font-size:.8125rem;color:var(--ink-soft);display:flex;flex-wrap:wrap;gap:.25rem 1.5rem;margin:1rem 0 0}
.meta dt{display:inline}.meta dd{display:inline;margin:0;font-family:"Geist Mono",ui-monospace,monospace}
.card{border:1px solid var(--hairline);background:var(--surface);border-radius:1rem;padding:1.25rem 1.5rem;margin:1rem 0}
.card.tone-HIGH_RISK,.card.tone-HIGH_RISK_POSSIBLE{background:var(--caution-soft);border-color:var(--caution)}
.card.tone-PROHIBITED_FLAG{background:var(--caution-soft);border-color:var(--caution)}
.card.tone-TRANSPARENCY{background:var(--grounded-soft);border-color:var(--grounded)}
.prov{margin:.9rem 0}.prov .head{display:flex;flex-wrap:wrap;align-items:baseline;gap:.25rem .75rem}
.label{font-family:"Geist Mono",ui-monospace,monospace;font-size:.875rem;font-weight:600}
.cid{font-family:"Geist Mono",ui-monospace,monospace;font-size:.8125rem;color:var(--ink-faint)}
.link{font-size:.8125rem;color:var(--grounded);margin-left:auto;text-decoration:none}.link:hover{text-decoration:underline}
blockquote{margin:.4rem 0 0;padding-left:.9rem;border-left:2px solid var(--grounded);color:var(--ink-soft);font-size:.9375rem;line-height:1.58}
.child{margin:.6rem 0 0 .75rem;padding-left:.9rem;border-left:1px solid var(--hairline)}
.commentary{font-size:.8125rem;color:var(--ink-soft);border:1px solid var(--hairline);background:var(--paper);border-radius:.5rem;padding:.5rem .75rem;margin:.75rem 0}
.commentary b{font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);margin-right:.5rem;font-weight:560}
.badge{display:inline-block;font-size:.8125rem;border-radius:999px;padding:.1rem .6rem;background:var(--hairline);color:var(--ink-soft);margin-right:.5rem}
.pen{border:1px solid var(--hairline);background:var(--surface);border-radius:1rem;padding:1rem 1.25rem;margin:.75rem 0}
.pen dl{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem 1rem;margin:.75rem 0 0;font-size:.9375rem}
.pen dt{font-size:.75rem;color:var(--ink-faint)}.pen dd{margin:0;font-family:"Geist Mono",ui-monospace,monospace}
.notice{border:1px solid var(--hairline);border-radius:.75rem;padding:1rem 1.25rem;font-size:.9375rem;color:var(--ink-soft);margin-top:2rem}
footer{font-size:.8125rem;color:var(--ink-faint);margin-top:2rem;border-top:1px solid var(--hairline);padding-top:1rem}
@media print{body{background:#fff;font-size:11pt}main{max-width:none;padding:0}.card,.pen{break-inside:avoid;box-shadow:none}
h2{break-after:avoid}.link{color:var(--ink-soft)}.link::after{content:" (" attr(href) ")";font-size:.7em;word-break:break-all}
@page{margin:18mm 16mm}}
@media (max-width:640px){.pen dl{grid-template-columns:repeat(2,1fr)}}
"""


def esc(s: object) -> str:
    return escape(str(s), quote=True)


def eurlex(cid: str) -> str:
    return f"{EURLEX}#{cid.split('.')[0]}"


def eur(v: float) -> str:
    return f"EUR {v:,.0f}"


# Shown in place of a personalised ceiling when it could not be computed.
# Never a computed "EUR 0": see penalties.turnover_status.
CEILING_PROMPT = {
    "missing": "enter annual turnover to compute",
    "zero": "turnover entered as 0; enter a positive annual turnover to compute",
}


def ceiling(v: float | None, status: str) -> str:
    if v is not None:
        return eur(v)
    return CEILING_PROMPT.get(status, CEILING_PROMPT["missing"])


def provision(p: ProvisionText, depth: int = 0) -> str:
    link = (
        f'<a class="link" href="{eurlex(p.citation_id)}" rel="noreferrer noopener">EUR-Lex</a>'
        if depth == 0
        else ""
    )
    kids = "".join(
        f'<div class="child">{provision(c, depth + 1)}</div>' for c in p.children
    )
    return (
        f'<div class="prov"><div class="head"><span class="label">{esc(p.citation_label)}</span>'
        f'<span class="cid">{esc(p.citation_id)}</span>{link}</div>'
        f"<blockquote>{esc(p.text)}</blockquote>{kids}</div>"
    )


def commentary(text: str) -> str:
    return f'<p class="commentary"><b>Commentary</b>{esc(text)}</p>'


def group(g: ObligationGroup) -> str:
    parts = [f"<h3>{esc(g.title)}</h3>"]
    parts.append(
        f'<p><span class="badge">{esc(ROLE_LABEL.get(g.role, g.role))}</span>'
        f'<span class="cid">{esc(" · ".join(p.citation_label for p in g.provisions))}</span></p>'
    )
    if g.commentary:
        parts.append(commentary(g.commentary))
    parts.extend(provision(p) for p in g.provisions)
    if g.applies_from:
        parts.append('<p class="eyebrow">Applies from</p>')
        parts.append(provision(g.applies_from))
    return f'<section class="card">{"".join(parts)}</section>'


def penalty(line: PenaltyLine, turnover_status: str) -> str:
    rule = {
        "eur_only": "fixed amount (not an undertaking)",
        "lower": "whichever is lower",
        "higher": "whichever is higher",
    }[line.rule]
    relevance = (
        "relevant to your answers" if line.applicable else "shown for completeness"
    )
    basis = "".join(provision(b) for b in line.rule_basis)
    return (
        f'<div class="pen"><div class="head"><span class="label">{esc(line.paragraph.citation_label)}</span>'
        f'<span class="cid">{esc(relevance)}</span></div>'
        f"<dl><div><dt>Fixed cap</dt><dd>{esc(eur(line.eur_cap))}</dd></div>"
        f"<div><dt>Turnover cap</dt><dd>{esc(line.pct_cap)} %</dd></div>"
        f"<div><dt>Rule</dt><dd>{esc(rule)}</dd></div>"
        f"<div><dt>Maximum ceiling for you</dt><dd>{esc(ceiling(line.ceiling_eur, turnover_status))}</dd></div></dl>"
        f"{commentary(line.why)}{provision(line.paragraph)}{basis}</div>"
    )


def render_export(
    report: AssessmentResult,
    *,
    assessment_id: str,
    saved_at: datetime,
    engine_version: str,
    environment: str,
) -> str:
    d = report.decision
    roles = ", ".join(ROLE_LABEL.get(r, r) for r in d.roles) or "none selected"
    out: list[str] = []
    out.append(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>AI Act Copilot: assessment record {esc(assessment_id[:8])}</title>"
        f"<style>{CSS}</style></head><body><main>"
    )
    out.append(
        f'<header><p class="eyebrow">AI Act Copilot: assessment record</p>'
        f"<h1>{esc(report.headline_text)}</h1>"
        f'<dl class="meta">'
        f"<div><dt>Assessed on: </dt><dd>{esc(saved_at.strftime('%Y-%m-%d %H:%M UTC'))}</dd></div>"
        f"<div><dt>Engine: </dt><dd>{esc(engine_version)}</dd></div>"
        f"<div><dt>Consolidated text of: </dt><dd>{esc(report.corpus_consolidated_date)}</dd></div>"
        f"<div><dt>Environment: </dt><dd>{esc(environment)}</dd></div>"
        f"<div><dt>Record: </dt><dd>{esc(assessment_id)}</dd></div>"
        f"<div><dt>Roles: </dt><dd>{esc(roles)}</dd></div></dl></header>"
    )
    out.append(
        f'<section class="card tone-{esc(d.headline)}"><p class="eyebrow">Result</p>'
        f"<p><strong>{esc(HEADLINE_LABEL.get(d.headline, d.headline))}</strong></p>"
        f"<p>{esc(report.headline_text)}</p></section>"
    )

    if report.scope:
        out.append("<h2>Scope</h2>" + "".join(provision(p) for p in report.scope))
    if report.prohibited_flags:
        out.append("<h2>Prohibited-practice patterns matched (Article 5(1))</h2>")
        out.append(
            commentary(
                "Each point carries conditions and exceptions. A match here is a red flag "
                "to take to counsel, not a determination that the practice is prohibited."
            )
        )
        out.extend(provision(f.provision) for f in report.prohibited_flags)
    if report.high_risk_basis:
        out.append("<h2>Why it appears high-risk (Article 6(2) and Annex III)</h2>")
        out.append(provision(report.high_risk_basis))
        if report.derogation:
            out.append("<h3>The Article 6(3) derogation</h3>")
            out.append(
                commentary(
                    "You indicated you intend to rely on this derogation. This tool has not "
                    "applied it: the assessment stays high-risk unless the derogation is "
                    "documented as Article 6(4) requires."
                    if d.derogation_claimed
                    else "This tool never applies the derogation itself. It is quoted so you "
                    "can assess whether its conditions could apply."
                )
            )
            out.extend(provision(p) for p in report.derogation)
    if report.product_route:
        out.append("<h2>Product-safety route (Article 6(1))</h2>")
        out.extend(provision(p) for p in report.product_route)
    if report.role_definitions:
        out.append("<h2>Your role, as the Regulation defines it (Article 3)</h2>")
        out.extend(provision(p) for p in report.role_definitions)
        out.extend(provision(p) for p in report.treated_as_provider)
    if report.obligations:
        out.append("<h2>Obligations and their basis, verbatim by article</h2>")
        out.extend(group(g) for g in report.obligations)
    if report.dates:
        out.append(
            "<h2>When these apply (Article 113 and transitional provisions)</h2>"
        )
        out.extend(provision(p) for p in report.dates)

    out.append("<h2>Maximum administrative fine ceilings (Article 99)</h2>")
    out.append(commentary(report.penalties.commentary))
    out.extend(
        penalty(line, report.penalties.turnover_status)
        for line in report.penalties.lines
    )
    out.append("<h3>What authorities weigh</h3>" + provision(report.penalties.factors))

    out.append("<h2>Notes (commentary)</h2><ul>")
    out.extend(f"<li>{esc(c)}</li>" for c in report.commentary)
    out.append("</ul>")
    out.append(
        '<div class="notice"><strong>Informational, not legal advice.</strong> Results are '
        "drawn from the consolidated EU AI Act text and are for orientation only. Only the "
        "version published in the Official Journal is legally authentic. Have anything you "
        "intend to act on reviewed by a qualified professional.</div>"
    )
    out.append(
        f"<footer>Generated by AI Act Copilot on {esc(report.generated_at.strftime('%Y-%m-%d %H:%M UTC'))} "
        f"from the answers saved on {esc(saved_at.strftime('%Y-%m-%d'))}. Provision text is rendered "
        f"from the corpus current at generation time (consolidated text of "
        f"{esc(report.corpus_consolidated_date)}); this record is not an immutable snapshot of "
        f"the quoted text.</footer></main></body></html>"
    )
    return "".join(out)
