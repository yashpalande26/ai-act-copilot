"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon, DownloadIcon, FileTextIcon } from "lucide-react";

import { Commentary } from "@/components/assess/provision";
import { AssessmentReport } from "@/components/assess/report";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { SavedAssessment } from "@/lib/types";

/** Reopens a saved assessment: stored answers, report re-rendered live. */
export function SavedAssessmentView({ id }: { id: string }) {
  const [state, setState] = useState<
    { kind: "loading" } | { kind: "missing" } | { kind: "error" } | { kind: "ok"; saved: SavedAssessment }
  >({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/assessments/${encodeURIComponent(id)}`, { cache: "no-store" })
      .then(async (r) => {
        if (cancelled) return;
        if (r.status === 404) return setState({ kind: "missing" });
        if (!r.ok) return setState({ kind: "error" });
        setState({ kind: "ok", saved: (await r.json()) as SavedAssessment });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state.kind === "loading") {
    return (
      <div className="space-y-4" role="status" aria-label="Loading assessment">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (state.kind === "missing") {
    return <p className="type-body text-ink-soft">That assessment could not be found.</p>;
  }
  if (state.kind === "error") {
    return <p className="type-body text-ink-soft">That assessment could not be loaded right now.</p>;
  }

  const { saved } = state;
  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/app/assess"
          className="type-micro text-ink-soft hover:text-ink inline-flex items-center gap-1.5"
        >
          <ArrowLeftIcon className="size-3.5" aria-hidden />
          New assessment
        </Link>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm">
            <a href={`/api/assessments/${saved.id}/export`} target="_blank" rel="noreferrer noopener">
              <FileTextIcon className="size-4" aria-hidden />
              Open the record
            </a>
          </Button>
          <Button asChild variant="ghost" size="sm">
            <a href={`/api/assessments/${saved.id}/export?download=1`}>
              <DownloadIcon className="size-4" aria-hidden />
              Download HTML
            </a>
          </Button>
        </div>
        <dl className="type-micro text-ink-soft mt-3 flex flex-wrap gap-x-6 gap-y-1">
          <div>
            <dt className="inline">Saved: </dt>
            <dd className="inline font-mono">{new Date(saved.created_at).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="inline">Engine: </dt>
            <dd className="inline font-mono">{saved.engine_version}</dd>
          </div>
          <div>
            <dt className="inline">Corpus consolidated: </dt>
            <dd className="inline font-mono">{saved.corpus_consolidated_date}</dd>
          </div>
          <div>
            <dt className="inline">Answers: </dt>
            <dd className="inline">
              {saved.source === "extracted"
                ? "pre-filled from a description, then reviewed and confirmed by you"
                : "entered by hand"}
            </dd>
          </div>
        </dl>
        <Commentary>{saved.known_limitation}</Commentary>
      </div>
      <AssessmentReport report={saved.report} />
    </div>
  );
}
