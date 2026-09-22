"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon, CalendarPlusIcon } from "lucide-react";

import { Commentary, Provision } from "@/components/assess/provision";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { buildTimeline, type TimelineEntry } from "@/lib/timeline";
import type { AssessmentReport, SavedAssessment } from "@/lib/types";

const ROLE_LABEL: Record<string, string> = {
  provider: "Provider",
  deployer: "Deployer",
  importer: "Importer",
  distributor: "Distributor",
  authorised_representative: "Authorised representative",
  all: "All operators",
  voluntary: "Voluntary",
};

function Entry({ e }: { e: TimelineEntry }) {
  return (
    <li className="relative pl-8" data-testid="timeline-entry">
      <span className="bg-accent-solid absolute top-2 left-0 size-2.5 rounded-full ring-4 ring-[var(--paper)]" aria-hidden />
      <div className="card-raised rounded-2xl p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h3 className="type-h3 text-ink">{e.title}</h3>
          <span className="type-micro bg-surface-sunken text-ink-soft rounded-full px-2.5 py-0.5">{ROLE_LABEL[e.role] ?? e.role}</span>
        </div>
        {e.dates.length ? (
          <p className="type-meta text-ink mt-2 font-medium">
            {e.resolved ? "Applies from " : "Article names several dates: "}
            {e.dates.map((d) => d.label).join(e.resolved ? ", then " : " or ")}
            <span className="type-micro text-ink-faint ml-2 font-normal">
              {e.resolved ? `as quoted in ${e.appliesFrom?.citation_label}` : `route not determined; read ${e.appliesFrom?.citation_label} below`}
            </span>
          </p>
        ) : (
          <p className="type-meta text-ink-soft mt-2">Application date not captured in this corpus.</p>
        )}
        <p className="type-micro text-ink-faint mt-2 font-mono">{e.provisions.map((p) => p.citation_id).join(" · ")}</p>
        {e.appliesFrom ? (
          <div className="mt-4">
            <Provision p={e.appliesFrom} compact />
          </div>
        ) : null}
      </div>
    </li>
  );
}

/**
 * PROTOTYPE: the saved assessment's obligations on a timeline. Dates are read
 * from the Article 113 text each group already quotes; the ICS download is
 * built from the same data. Nothing generated, nothing hardcoded.
 */
export function AssessmentTimeline({ id, initialReport }: { id: string; initialReport?: AssessmentReport }) {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "missing" } | { kind: "error" } | { kind: "ok"; report: AssessmentReport }>(
    initialReport ? { kind: "ok", report: initialReport } : { kind: "loading" },
  );

  useEffect(() => {
    if (initialReport) return;
    let cancelled = false;
    fetch(`/api/assessments/${encodeURIComponent(id)}`, { cache: "no-store" })
      .then(async (r) => {
        if (cancelled) return;
        if (r.status === 404) return setState({ kind: "missing" });
        if (!r.ok) return setState({ kind: "error" });
        const saved = (await r.json()) as SavedAssessment;
        setState({ kind: "ok", report: saved.report });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [id, initialReport]);

  if (state.kind === "loading") {
    return (
      <div className="space-y-4" role="status" aria-label="Loading timeline">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-32 w-full rounded-2xl" />
      </div>
    );
  }
  if (state.kind === "missing") return <p className="type-body text-ink-soft">That assessment could not be found.</p>;
  if (state.kind === "error") return <p className="type-body text-ink-soft">The timeline could not be loaded right now.</p>;

  const { dated, undated, route } = buildTimeline(state.report);
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/app/assess/${encodeURIComponent(id)}`} className="type-micro text-ink-soft hover:text-ink inline-flex items-center gap-1.5">
          <ArrowLeftIcon className="size-3.5" aria-hidden />
          Back to the record
        </Link>
        {dated.length ? (
          <Button asChild variant="outline" size="sm">
            <a href={`/api/assessments/${encodeURIComponent(id)}/timeline.ics`} data-testid="ics-link">
              <CalendarPlusIcon className="size-4" aria-hidden />
              Add to calendar (.ics)
            </a>
          </Button>
        ) : null}
      </div>
      <Commentary>
        Each date below is read from the Article 113 provision the report quotes for that group
        {route === "annex_iii"
          ? ", taking the Annex III clause because this record is high-risk under Article 6(2)"
          : route === "annex_i"
            ? ", taking the Annex I clause because this record follows the Article 6(1) product route"
            : ""}
        . Where the corpus does not carry the date (the Regulation&apos;s general application sentence is not captured as a
        provision), the group is listed without one rather than with a guess. Informational, not legal advice.
      </Commentary>
      {dated.length ? (
        <ol className="border-hairline relative space-y-5 border-l pl-0 [&>li]:ml-[-1px]">
          {dated.map((e) => (
            <Entry key={e.key} e={e} />
          ))}
        </ol>
      ) : (
        <p className="type-meta text-ink-soft">No obligation group in this report carries a dated provision.</p>
      )}
      {undated.length ? (
        <section>
          <p className="type-eyebrow text-ink-faint mb-3">Without a captured date</p>
          <ol className="space-y-4">
            {undated.map((e) => (
              <Entry key={e.key} e={e} />
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}
