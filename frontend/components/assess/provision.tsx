import { ArrowUpRightIcon } from "lucide-react";

import { eurlexHref } from "@/lib/eurlex";
import type { ProvisionText } from "@/lib/types";

/**
 * One provision, verbatim, with its label, id and EUR-Lex link, and its
 * children nested beneath. This is the only way legal text reaches the
 * report: quoted, never paraphrased.
 */
export function Provision({
  p,
  depth = 0,
  compact = false,
}: {
  p: ProvisionText;
  depth?: number;
  compact?: boolean;
}) {
  const isHeading = p.children.length > 0 && p.text.length < 160 && depth === 0;
  return (
    <div className={depth === 0 ? "" : "border-hairline mt-2.5 ml-3 border-l pl-3.5"}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className={`type-mono font-medium ${isHeading ? "text-ink" : "text-ink"}`}>
          {p.citation_label}
        </span>
        <span className="type-micro text-ink-faint font-mono">{p.citation_id}</span>
        {depth === 0 ? (
          <a
            href={eurlexHref(p.citation_id)}
            target="_blank"
            rel="noreferrer noopener"
            className="type-micro text-grounded focus-visible:ring-ring -mx-1 -my-1.5 ml-auto inline-flex items-center gap-1 rounded-sm px-1 py-1.5 hover:underline focus-visible:ring-2 focus-visible:outline-none"
          >
            EUR-Lex
            <ArrowUpRightIcon className="size-3.5" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : null}
      </div>
      <blockquote
        className={`border-grounded/30 text-ink-soft mt-1.5 border-l-2 pl-3.5 ${
          compact ? "type-micro" : "type-meta"
        } ${isHeading ? "font-medium" : ""}`}
      >
        {p.text}
      </blockquote>
      {p.children.map((c) => (
        <Provision key={c.citation_id} p={c} depth={depth + 1} compact={compact} />
      ))}
    </div>
  );
}

/** A short "Commentary" label so the tool's own words are never mistaken for the Act's. */
export function Commentary({ children }: { children: React.ReactNode }) {
  return (
    <p className="type-micro text-ink-soft border-hairline bg-muted/40 mt-3 rounded-lg border px-3 py-2">
      <span className="type-eyebrow text-ink-faint mr-2">Commentary</span>
      {children}
    </p>
  );
}
