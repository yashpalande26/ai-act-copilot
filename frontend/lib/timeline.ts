import type { AssessmentReport, ObligationGroup, ProvisionText } from "@/lib/types";

/**
 * PROTOTYPE: a dated view of a saved assessment's obligations.
 *
 * Every date comes from the quoted Article 113 text the report already
 * attaches to each obligation group (`applies_from`); nothing is hardcoded.
 * A group whose date the corpus does not carry (the Regulation's general
 * application sentence is not captured as a provision) is listed with that
 * fact stated, never with a guessed date.
 */
const MONTHS = [
  "january", "february", "march", "april", "may", "june",
  "july", "august", "september", "october", "november", "december",
];
const DATE_RE = /\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b/g;

export type TimelineDate = { iso: string; label: string };

/**
 * Which high-risk route the record took. Article 113(c) names two dates:
 * (i) for systems high-risk under Article 6(2) and Annex III, (ii) for
 * systems high-risk under Article 6(1) and Annex I. The route is known from
 * the record's own decision, so the timeline can pick the clause that applies
 * instead of listing both (which put an Annex I record eight months early).
 */
export type HighRiskRoute = "annex_iii" | "annex_i" | "unknown";

export function routeOf(report: AssessmentReport): HighRiskRoute {
  const d = report.decision;
  if (d.high_risk_basis && d.high_risk_basis.startsWith("anx_III")) return "annex_iii";
  if (d.product_route) return "annex_i";
  return "unknown";
}

type DatedClause = { date: TimelineDate; clause: string };

/** Each date with the text that follows it up to the next date: the clause
 *  that says which systems the date is for. */
function datedClauses(text: string): DatedClause[] {
  const matches = [...text.matchAll(DATE_RE)];
  const dates = datesIn(text);
  return matches.map((m, i) => {
    const start = (m.index ?? 0) + m[0].length;
    const end = i + 1 < matches.length ? (matches[i + 1].index ?? text.length) : text.length;
    const iso = dates.find((d) => d.label === `${Number(m[1])} ${m[2]} ${m[3]}`)!;
    return { date: iso, clause: text.slice(start, end) };
  });
}

const ANNEX_III = /\bAnnex III\b/;
const ANNEX_I = /\bAnnex I\b(?!I)/;

/**
 * The dates that apply to this record from a quoted applies-from text. With
 * one date, that date. With several, the clause matching the record's route;
 * if the route is unknown or no clause names it, every date is kept and the
 * caller says so rather than guessing.
 */
export function selectDates(text: string, route: HighRiskRoute): { dates: TimelineDate[]; resolved: boolean } {
  const clauses = datedClauses(text);
  const all = clauses.map((c) => c.date);
  if (clauses.length <= 1) return { dates: all, resolved: true };
  const wanted = route === "annex_iii" ? ANNEX_III : route === "annex_i" ? ANNEX_I : null;
  if (!wanted) return { dates: all, resolved: false };
  const picked = clauses.filter((c) => wanted.test(c.clause)).map((c) => c.date);
  return picked.length ? { dates: picked, resolved: true } : { dates: all, resolved: false };
}

export function datesIn(text: string): TimelineDate[] {
  const out: TimelineDate[] = [];
  const seen = new Set<string>();
  for (const m of text.matchAll(DATE_RE)) {
    const day = Number(m[1]);
    const month = MONTHS.indexOf(m[2].toLowerCase()) + 1;
    const year = Number(m[3]);
    const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    if (!seen.has(iso)) {
      seen.add(iso);
      out.push({ iso, label: `${day} ${m[2]} ${year}` });
    }
  }
  return out;
}

export type TimelineEntry = {
  key: string;
  title: string;
  role: string;
  provisions: ProvisionText[];
  appliesFrom: ProvisionText | null;
  /** The dates that apply to this record, ascending. Empty when unknown. */
  dates: TimelineDate[];
  /** False when the quoted text names several dates and the record's route
   *  could not pick one; `dates` then holds all of them. */
  resolved: boolean;
};

export function buildTimeline(report: AssessmentReport): { dated: TimelineEntry[]; undated: TimelineEntry[]; route: HighRiskRoute } {
  const route = routeOf(report);
  const entries: TimelineEntry[] = report.obligations.map((g: ObligationGroup) => {
    const text = g.applies_from ? [g.applies_from.text, ...g.applies_from.children.map((c) => c.text)].join(" ") : "";
    const sel = g.applies_from ? selectDates(text, route) : { dates: [], resolved: true };
    return {
      key: g.key,
      title: g.title,
      role: g.role,
      provisions: g.provisions,
      appliesFrom: g.applies_from,
      dates: [...sel.dates].sort((a, b) => a.iso.localeCompare(b.iso)),
      resolved: sel.resolved,
    };
  });
  const dated = entries.filter((e) => e.dates.length > 0).sort((a, b) => a.dates[0].iso.localeCompare(b.dates[0].iso));
  const undated = entries.filter((e) => e.dates.length === 0);
  return { dated, undated, route };
}

function icsEscape(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

/** One all-day VEVENT per obligation group, on the date selected for the
 *  record's route (the earliest of several only when the route could not
 *  resolve them). RFC 5545 folding kept simple: short lines. */
export function buildIcs(report: AssessmentReport, assessmentId: string, headlineText: string): string {
  const { dated } = buildTimeline(report);
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//AI Act Copilot//assessment timeline (prototype)//EN",
    "CALSCALE:GREGORIAN",
    `X-WR-CALNAME:${icsEscape(`EU AI Act obligations, assessment ${assessmentId.slice(0, 8)}`)}`,
  ];
  for (const e of dated) {
    const d = e.dates[0].iso.replace(/-/g, "");
    const cites = e.provisions.map((p) => p.citation_label).join("; ");
    lines.push(
      "BEGIN:VEVENT",
      `UID:${assessmentId}-${e.key}@ai-act-copilot`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${d}`,
      `SUMMARY:${icsEscape(`EU AI Act: ${e.title} applies from ${e.dates[0].label}`)}`,
      `DESCRIPTION:${icsEscape(
        `${headlineText} Provisions: ${cites}. Date quoted from ${e.appliesFrom?.citation_label ?? "the Act"}. Informational, not legal advice.`,
      )}`,
      "END:VEVENT",
    );
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n") + "\r\n";
}
