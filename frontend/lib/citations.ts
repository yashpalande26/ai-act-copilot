/**
 * Which of an answer's citations the answer actually grounds on.
 *
 * The backend returns every provision it served to the model (the 15 to 17
 * passage context), not only the ones the answer cites. It does not flag
 * which were used, but the answer names each provision it relies on inline,
 * by its label ("Article 50, paragraph 1", "Annex III, point 5(b)", "Recital
 * 58"). This module reads those labels back into citation ids, the same
 * grammar the backend's verifier uses (verify.references_in), and splits the
 * citation list into the provisions the answer cites and the rest.
 *
 * A cited reference covers a citation when it is the same provision, an
 * ancestor of it ("Article 16" covers "art_16.pt_a") or a descendant of it
 * ("Article 6, paragraph 2" covers a citation for "art_6"). Order is the
 * server's order in both lists.
 */

import type { AskCitation } from "@/lib/types";

const ARTICLE =
  /\bArticles?\s+(\d+[a-z]?)(?:\s*\((\d+[a-z]?)\)|,?\s+paragraph\s+(\d+[a-z]?))?(?:,?\s+point\s+\(([a-z]{1,2}|\d+)\)|\s*\(([a-z]{1,2})\))?/gi;
const ANNEX = /\bAnnex\s+([IVXLC]+)\b(?:,?\s+Section\s+([A-Z0-9]+)\b)?(?:,?\s+points?\s+(\d+)(?:\s*\(([a-z])\))?)?/g;
const RECITAL = /\bRecitals?\s+(\d+)\b/gi;

/** Citation ids the answer names, most specific form, deduplicated. */
export function referencesIn(answer: string): string[] {
  const out = new Set<string>();
  for (const m of answer.matchAll(ARTICLE)) {
    const [, art, parA, parB, ptA, ptB] = m;
    let id = `art_${art.toLowerCase()}`;
    const par = parA ?? parB;
    const pt = ptA ?? ptB;
    if (par) id += `.par_${par.toLowerCase()}`;
    if (pt) id += `.pt_${pt.toLowerCase()}`;
    out.add(id);
  }
  for (const m of answer.matchAll(ANNEX)) {
    const [, roman, sec, pt, sub] = m;
    let id = `anx_${roman}`;
    if (sec) id += `.sec_${sec}`;
    if (pt) id += `.pt_${pt}`;
    if (sub) id += `.sub_${sub}`;
    out.add(id);
  }
  for (const m of answer.matchAll(RECITAL)) out.add(`rec_${m[1]}`);
  return [...out].sort();
}

/** True when `ref` and `citationId` name the same provision or one contains the other. */
export function covers(ref: string, citationId: string): boolean {
  return ref === citationId || citationId.startsWith(`${ref}.`) || ref.startsWith(`${citationId}.`);
}

export function isRecital(citationId: string): boolean {
  return citationId.startsWith("rec_");
}

export type SplitCitations = {
  /** Provisions the answer names inline, in the server's order. */
  used: AskCitation[];
  /** Served to the model but not named by the answer. */
  other: AskCitation[];
};

/**
 * A bare root reference ("Annex III", "Article 6") is satisfied by a more
 * specific reference under it in the same answer ("Annex III, point 5(b)"):
 * the prose says "the Annex III entry" about the point it already named, not
 * about every Annex III point in the context. Only a root with nothing more
 * specific under it keeps its wide reach.
 */
export function effectiveReferences(refs: string[]): string[] {
  return refs.filter((r) => !refs.some((other) => other !== r && other.startsWith(`${r}.`)));
}

export function splitCitations(answer: string, citations: AskCitation[]): SplitCitations {
  const refs = effectiveReferences(referencesIn(answer));
  const used: AskCitation[] = [];
  const other: AskCitation[] = [];
  for (const c of citations) {
    (refs.some((r) => covers(r, c.citation_id)) ? used : other).push(c);
  }
  return { used, other };
}
