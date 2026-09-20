"use client";

import { useState } from "react";
import { ChevronDownIcon, QuoteIcon } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { AskCitation } from "@/lib/types";

/**
 * A clickable citation. Collapsed it shows the article label. Expanded it
 * reveals the provision text word for word.
 *
 * The quoted text is what was actually retrieved and fed to the model, not a
 * paraphrase, which is the whole point of showing it.
 */
export function CitationCard({ citation }: { citation: AskCitation }) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger
        className="border-border/70 bg-card hover:border-grounded/45 hover:bg-grounded/[0.05] focus-visible:ring-ring group flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
        aria-label={`${open ? "Hide" : "Show"} the text of ${citation.citation_label}`}
      >
        <QuoteIcon className="text-grounded size-4 shrink-0" aria-hidden />
        <span className="type-meta flex-1 font-mono font-medium">
          {citation.citation_label}
        </span>
        <ChevronDownIcon
          className={`text-muted-foreground size-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <blockquote className="border-grounded/35 text-muted-foreground type-body mt-2.5 ml-4 border-l-2 py-1 pl-5">
          {citation.quoted_text}
          <footer className="text-muted-foreground/60 type-micro mt-2.5 font-mono">
            {citation.citation_id}
          </footer>
        </blockquote>
      </CollapsibleContent>
    </Collapsible>
  );
}
