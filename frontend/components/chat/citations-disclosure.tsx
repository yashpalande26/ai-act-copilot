"use client";

import { useState } from "react";
import { ArrowUpRightIcon, ChevronDownIcon, QuoteIcon } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { eurlexHref } from "@/lib/eurlex";
import type { AskCitation } from "@/lib/types";

/**
 * All of an answer's citations behind one collapsed-by-default disclosure.
 *
 * The answer stays the focus of the turn; the evidence is one click away and
 * announced by count, so a twelve-citation answer costs one row of vertical
 * space until the reader asks for more. Inside, every citation shows the
 * human label, the machine id, the provision text word for word (what was
 * actually retrieved and fed to the model, not a paraphrase) and a link to
 * the article on EUR-Lex.
 *
 * Radix Collapsible renders the trigger as a real <button> and wires
 * aria-expanded / aria-controls to the content region, so keyboard and screen
 * reader behaviour come from the primitive rather than from this file.
 */
export function CitationsDisclosure({ citations }: { citations: AskCitation[] }) {
  const [open, setOpen] = useState(false);
  const count = citations.length;
  if (count === 0) return null;

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="border-hairline bg-card [box-shadow:var(--shadow-xs)] rounded-2xl border"
    >
      <CollapsibleTrigger className="group hover:bg-grounded/[0.05] focus-visible:ring-ring flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none data-[state=open]:rounded-b-none sm:px-4.5">
        <QuoteIcon className="text-grounded size-4 shrink-0" aria-hidden />
        <span className="type-micro text-ink-soft font-medium tracking-[0.07em] uppercase">
          Cited provisions
        </span>
        <span className="type-micro bg-grounded/10 text-grounded rounded-full px-2 py-0.5 font-mono font-medium tabular-nums">
          {count}
        </span>
        <span className="type-micro text-ink-faint ml-auto hidden sm:inline">
          {open ? "Hide" : "Show"}
        </span>
        <ChevronDownIcon
          className="text-ink-faint size-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180 max-sm:ml-auto"
          aria-hidden
        />
      </CollapsibleTrigger>

      <CollapsibleContent className="disclosure-content overflow-hidden">
        {/* Below sm the cards give up their own border and padding and become
            hairline-divided rows: at 390px three nested insets would leave the
            quoted text under 230px wide. */}
        <ol className="border-hairline border-t px-4 sm:space-y-2.5 sm:p-4">
          {citations.map((citation) => (
            <li
              key={citation.citation_id}
              className="border-hairline py-3.5 not-last:border-b sm:rounded-xl sm:border sm:bg-paper sm:p-4"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="type-mono text-ink font-medium">
                  {citation.citation_label}
                </span>
                <span className="type-micro text-ink-faint font-mono">
                  {citation.citation_id}
                </span>
                <a
                  href={eurlexHref(citation.citation_id)}
                  target="_blank"
                  rel="noreferrer noopener"
                  // Negative margins cancel the padding in the layout, so the
                  // hit area grows past 24px without moving anything around it.
                  className="type-micro text-grounded focus-visible:ring-ring -mx-1 -my-1.5 ml-auto inline-flex items-center gap-1 rounded-sm px-1 py-1.5 hover:underline focus-visible:ring-2 focus-visible:outline-none"
                >
                  EUR-Lex
                  <ArrowUpRightIcon className="size-3.5" aria-hidden />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              </div>
              <blockquote className="border-grounded/30 text-ink-soft type-meta mt-2.5 border-l-2 pl-3.5">
                {citation.quoted_text}
              </blockquote>
            </li>
          ))}
        </ol>
      </CollapsibleContent>
    </Collapsible>
  );
}
