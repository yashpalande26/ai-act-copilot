"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import type { SavedAssessmentSummary } from "@/lib/types";

const HEADLINE_SHORT: Record<string, string> = {
  OUT_OF_SCOPE: "Out of scope",
  PROHIBITED_FLAG: "Art. 5 red flag",
  HIGH_RISK: "High-risk",
  HIGH_RISK_POSSIBLE: "Possibly high-risk",
  TRANSPARENCY: "Transparency",
  MINIMAL: "Minimal",
};

/** "Your assessments": the signed-in user's saved assessments, newest first. */
export function AssessmentsRail() {
  const [rows, setRows] = useState<SavedAssessmentSummary[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/assessments", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const body = (await r.json()) as { assessments: SavedAssessmentSummary[] };
        if (!cancelled) setRows(body.assessments.slice(0, 10));
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <nav aria-label="Your assessments" className="px-2 pb-4">
      <p className="type-eyebrow text-ink-faint px-3 pt-3 pb-1.5">Your assessments</p>
      {error ? (
        <p className="type-micro text-ink-soft px-3 py-2">Could not load your assessments.</p>
      ) : rows === null ? (
        <ul className="space-y-1.5 px-1 pt-1" aria-hidden>
          {[0, 1].map((i) => (
            <li key={i} className="rounded-lg px-3 py-2.5">
              <Skeleton className="h-3.5 w-[80%]" />
              <Skeleton className="mt-2 h-3 w-[45%]" />
            </li>
          ))}
        </ul>
      ) : rows.length === 0 ? (
        <p className="type-micro text-ink-soft px-3 py-2">Saved assessments will appear here.</p>
      ) : (
        <ul className="space-y-0.5">
          {rows.map((a) => (
            <li key={a.id}>
              <Link
                href={`/app/assess/${a.id}`}
                className="text-ink-soft hover:bg-muted/60 hover:text-ink focus-visible:ring-ring block rounded-lg px-3 py-2.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
              >
                <span className="type-meta block leading-snug">
                  {HEADLINE_SHORT[a.headline] ?? a.headline}
                  {a.high_risk_basis ? (
                    <span className="type-micro text-ink-faint ml-2 font-mono">{a.high_risk_basis}</span>
                  ) : null}
                </span>
                <span className="type-micro text-ink-faint mt-1 block">
                  {new Date(a.created_at).toLocaleDateString()} <span aria-hidden>&middot;</span>{" "}
                  {a.roles.join(", ") || "no role"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}
