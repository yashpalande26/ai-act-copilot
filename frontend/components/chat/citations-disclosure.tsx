"use client";

import { useState } from "react";
import { ArrowUpRightIcon, ChevronDownIcon, QuoteIcon } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { isRecital, splitCitations } from "@/lib/citations";
import { eurlexHref } from "@/lib/eurlex";
import type { AskCitation } from "@/lib/types";

/**
 * The provisions an answer grounds on, behind one collapsed-by-default
 * disclosure, inside the answer card.
 *
 * The backend returns the whole served context (15 to 17 passages), not only
 * what the answer used, and it carries no "used" flag. The answer names every
 * provision it relies on inline, so lib/citations reads those labels back and
 * the panel shows those first (24 Sep 2026: it listed all of them, including
 * passages the answer never touched and the occasional loosely linked
 * recital). The rest stay one more click away under "Other retrieved
 * provisions", labelled as context the answer does not rely on. An answer
 * that names nothing (rare: the honest not-listed answer with no general
 * obligation in context) shows the served context under the primary heading
 * rather than hiding the evidence.
 *
 * Each row: the human label, the machine id, an explanatory tag on a recital
 * (ADR-32: never the rule), the passage text word for word, and the EUR-Lex
 * link. Radix Collapsible renders real buttons with aria-expanded and
 * aria-controls, so keyboard and screen-reader behaviour come from the
 * primitive.
 */
export function CitationsDisclosure({
  answer,
  citations,
}: {
  answer: string;
  citations: AskCitation[];
}) {
  const [open, setOpen] = useState(false);
  const [othersOpen, setOthersOpen] = useState(false);
  if (citations.length === 0) return null;

  const split = splitCitations(answer, citations);
  const primary = split.used.length > 0 ? split.used : citations;
  const other = split.used.length > 0 ? split.other : [];
  const heading = split.used.length > 0 ? "Cited provisions" : "Retrieved provisions";

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-hairline border-t">
      <CollapsibleTrigger className="group hover:bg-surface-sunken/60 focus-visible:ring-ring flex w-full items-center gap-3 px-5 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset sm:px-6">
        <QuoteIcon className="text-grounded size-4 shrink-0" aria-hidden />
        <span className="type-micro text-ink-soft font-medium tracking-[0.07em] uppercase">
          {heading}
        </span>
        <span
          className="type-micro bg-grounded/10 text-grounded rounded-full px-2 py-0.5 font-mono font-medium tabular-nums"
          data-testid="citations-count"
        >
          {primary.length}
        </span>
        {other.length > 0 ? (
          <span className="type-micro text-ink-faint hidden sm:inline" data-testid="citations-other-count">
            + {other.length} retrieved
          </span>
        ) : null}
        <span className="type-micro text-ink-faint ml-auto hidden sm:inline">
          {open ? "Hide" : "Show"}
        </span>
        <ChevronDownIcon
          className="text-ink-faint size-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180 max-sm:ml-auto"
          aria-hidden
        />
      </CollapsibleTrigger>

      <CollapsibleContent className="disclosure-content overflow-hidden">
        <div className="border-hairline bg-surface-sunken/40 border-t px-5 pb-4 sm:px-6">
          <ol className="sm:space-y-2.5 sm:pt-4" data-testid="citations-used">
            {primary.map((citation) => (
              <CitationRow key={citation.citation_id} citation={citation} />
            ))}
          </ol>

          {other.length > 0 ? (
            <Collapsible open={othersOpen} onOpenChange={setOthersOpen} className="mt-3">
              <CollapsibleTrigger className="group/other type-micro text-ink-faint hover:text-ink-soft focus-visible:ring-ring -mx-1 inline-flex items-center gap-1.5 rounded-md px-1 py-1 transition-colors focus-visible:ring-2 focus-visible:outline-none">
                <ChevronDownIcon
                  className="size-3.5 transition-transform duration-200 group-data-[state=open]/other:rotate-180"
                  aria-hidden
                />
                Other retrieved provisions ({other.length})
              </CollapsibleTrigger>
              <CollapsibleContent className="disclosure-content overflow-hidden">
                <p className="type-micro text-ink-faint mt-2 mb-1">
                  Retrieved for context and shown to the model; the answer does not rely on them.
                </p>
                <ol className="sm:space-y-2.5 sm:pt-2" data-testid="citations-other">
                  {other.map((citation) => (
                    <CitationRow key={citation.citation_id} citation={citation} muted />
                  ))}
                </ol>
              </CollapsibleContent>
            </Collapsible>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

/* Below sm the rows give up their own border and padding and become
   hairline-divided rows: at 390px three nested insets would leave the quoted
   text under 230px wide. */
function CitationRow({ citation, muted = false }: { citation: AskCitation; muted?: boolean }) {
  const recital = isRecital(citation.citation_id);
  return (
    <li
      className={`border-hairline py-3.5 not-last:border-b sm:rounded-xl sm:border sm:p-4 ${
        muted ? "sm:bg-surface-sunken/50" : "sm:bg-card"
      }`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className={`type-mono font-medium ${muted ? "text-ink-soft" : "text-ink"}`}>
          {citation.citation_label}
        </span>
        <span className="type-micro text-ink-faint font-mono">{citation.citation_id}</span>
        {recital ? (
          <span className="type-micro bg-caution/10 text-caution rounded-full px-2 py-0.5">
            Explanatory, non-binding
          </span>
        ) : null}
        <a
          href={eurlexHref(citation.citation_id)}
          target="_blank"
          rel="noreferrer noopener"
          // Negative margins cancel the padding in the layout, so the hit
          // area grows past 24px without moving anything around it.
          className="type-micro text-grounded focus-visible:ring-ring -mx-1 -my-1.5 ml-auto inline-flex items-center gap-1 rounded-sm px-1 py-1.5 hover:underline focus-visible:ring-2 focus-visible:outline-none"
        >
          EUR-Lex
          <ArrowUpRightIcon className="size-3.5" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      </div>
      <blockquote
        className={`type-meta mt-2.5 border-l-2 pl-3.5 ${
          recital ? "border-caution/40 text-ink-soft" : "border-grounded/30 text-ink-soft"
        }`}
      >
        {citation.quoted_text}
      </blockquote>
    </li>
  );
}
