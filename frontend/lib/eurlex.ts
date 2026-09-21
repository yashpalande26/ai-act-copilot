/**
 * Deep links into the consolidated EU AI Act on EUR-Lex.
 *
 * The consolidated HTML anchors every article and annex by the same id the
 * backend uses as the first segment of a citation_id ("art_16.pt_a" -> "#art_16",
 * "anx_III.pt_5.sub_b" -> "#anx_III"), so the link is derived, never looked up.
 * Points and paragraphs have no anchors of their own; the reader lands on the
 * article and the quoted text tells them which part.
 */

export const EURLEX_CONSOLIDATED_URL =
  "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727";

export function eurlexHref(citationId: string): string {
  const anchor = citationId.split(".")[0];
  return `${EURLEX_CONSOLIDATED_URL}#${anchor}`;
}
