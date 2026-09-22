import { ArrowUpRightIcon } from "lucide-react";

import { Mark } from "@/components/site-header";

import { eurlexHref } from "@/lib/eurlex";
import report from "@/lib/fixtures/assessment-report.json";
import type { AssessmentReport, ProvisionText } from "@/lib/types";

/**
 * The hero visual: an excerpt of a REAL assessment report.
 *
 * `lib/fixtures/assessment-report.json` was produced by the backend's own
 * code path (an HR-tech recruitment system, provider and deployer). Every
 * quoted line below is corpus text pulled from that fixture by citation id;
 * nothing is written for marketing. Counts are computed from the fixture.
 */
const fixture = report as unknown as AssessmentReport;

const basis = fixture.high_risk_basis;
const core = fixture.obligations.find((g) => g.key === "provider_core");
const article16 = core?.provisions[0];
const shown: ProvisionText[] = article16?.children.slice(0, 2) ?? [];
const remainingPoints = (article16?.children.length ?? 0) - shown.length;
const otherGroups = fixture.obligations.length - (core ? 1 : 0);

function Quote({ p }: { p: ProvisionText }) {
  return (
    <a
      href={eurlexHref(p.citation_id)}
      target="_blank"
      rel="noreferrer noopener"
      className="border-hairline bg-paper hover:border-grounded/45 focus-visible:ring-ring group block rounded-xl border p-3.5 transition-colors focus-visible:ring-2 focus-visible:outline-none sm:p-4"
    >
      <span className="flex items-center gap-2">
        <span className="type-mono text-ink font-medium">{p.citation_label}</span>
        <span className="type-micro text-ink-faint font-mono">{p.citation_id}</span>
        <ArrowUpRightIcon
          className="text-ink-faint group-hover:text-grounded ml-auto size-3.5 shrink-0 transition-colors"
          aria-hidden
        />
      </span>
      <span className="border-grounded/30 text-ink-soft type-meta mt-2.5 block border-l-2 pl-3.5">
        {p.text}
      </span>
    </a>
  );
}

export function AssessmentCard() {
  if (!basis || !article16) return null;
  return (
    <figure className="border-hairline bg-surface overflow-hidden rounded-2xl border shadow-[var(--shadow-xl)]">
      <div className="border-hairline flex items-center justify-between gap-4 border-b px-5 py-2.5 sm:px-7">
        <span className="flex items-center gap-2">
          <Mark className="size-5 text-[0.8rem]" />
          <span className="type-micro text-ink-faint font-mono">assessment record</span>
        </span>
        <span className="type-micro text-ink-faint font-mono">
          consolidated text {fixture.corpus_consolidated_date}
        </span>
      </div>
      <div className="border-hairline bg-surface-sunken/60 border-b px-5 py-4 sm:px-7 sm:py-5">
        <p className="type-eyebrow text-ink-faint">Result, from a real report</p>
        <p className="type-body text-ink mt-2 font-medium">{fixture.headline_text}</p>
      </div>

      <div className="px-5 py-6 sm:px-7 sm:py-7">
        <div className="flex gap-3.5">
          <span className="bg-accent-soft text-accent-solid mt-0.5 hidden size-7 shrink-0 items-center justify-center rounded-lg sm:flex">
            <span className="font-display text-[0.95rem] leading-none" aria-hidden>&sect;</span>
          </span>
          <div className="min-w-0 flex-1">
            <p className="type-eyebrow text-ink-faint">Why</p>
            <div className="mt-3">
              <Quote p={basis} />
            </div>
          </div>
        </div>

        <div className="mt-6 sm:pl-[2.625rem]">
          <p className="type-eyebrow text-ink-faint">Obligations quoted, provider</p>
          <ul className="mt-3 space-y-2.5">
            {shown.map((p) => (
              <li key={p.citation_id}>
                <Quote p={p} />
              </li>
            ))}
          </ul>
          <p className="type-micro text-ink-faint mt-4">
            {remainingPoints} more points of Article 16 and {otherGroups} further groups in the
            full report, each quoted with the date it applies from. Consolidated text of{" "}
            {fixture.corpus_consolidated_date}. Informational, not legal advice.
          </p>
        </div>
      </div>
    </figure>
  );
}
