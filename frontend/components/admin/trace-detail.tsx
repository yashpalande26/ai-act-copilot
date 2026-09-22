"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon, ArrowUpRightIcon, CircleSlashIcon } from "lucide-react";

import { RetrievalTable } from "@/components/admin/retrieval-table";
import { Skeleton } from "@/components/ui/skeleton";
import { eurlexHref } from "@/lib/eurlex";
import type { TraceDetail as Trace } from "@/lib/types";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="type-micro text-ink-faint">{label}</dt>
      <dd className="type-meta truncate font-mono" title={value}>
        {value}
      </dd>
    </div>
  );
}

function TraceDetailView({ trace }: { trace: Trace }) {
  const r = trace.retrieval;
  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/app/admin/traces"
          className="type-micro text-ink-soft hover:text-ink inline-flex items-center gap-1.5"
        >
          <ArrowLeftIcon className="size-3.5" aria-hidden />
          All traces
        </Link>
        <h1 className="type-h2 mt-3 text-balance">{trace.question}</h1>
        {trace.rewritten_query ? (
          <p className="type-micro text-ink-soft mt-2">
            Retrieved for (rewritten follow-up):{" "}
            <span className="text-ink">{trace.rewritten_query}</span>
          </p>
        ) : null}
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-7">
          <Stat label="When" value={new Date(trace.created_at).toLocaleString()} />
          <Stat label="User" value={trace.user_email} />
          <Stat label="Environment" value={trace.environment} />
          <Stat label="Model" value={trace.model} />
          <Stat
            label="Retrieval"
            value={`${r.config}${r.legacy ? "" : ` / actor ${r.query_actor ?? "none"}`}`}
          />
          <Stat
            label="Tokens in / out"
            value={`${trace.prompt_tokens ?? "–"} / ${trace.completion_tokens ?? "–"}`}
          />
          <Stat
            label="Latency retr / gen"
            value={`${trace.retrieval_latency_ms} / ${trace.generation_latency_ms ?? "–"} ms`}
          />
        </dl>
      </div>

      <section aria-labelledby="answer-heading" className="border-hairline bg-card rounded-2xl border p-5 sm:p-6">
        <h2 id="answer-heading" className="type-eyebrow text-ink-faint">
          Answer
        </h2>
        {trace.abstained ? (
          <p className="type-body text-ink-soft mt-3 flex items-start gap-2.5">
            <CircleSlashIcon className="text-caution mt-1 size-[18px] shrink-0" aria-hidden />
            <span>
              Abstained. The model returned the fixed refusal, so no citations were shown to
              the user.
            </span>
          </p>
        ) : (
          <p className="type-body mt-3 whitespace-pre-wrap">{trace.answer}</p>
        )}
        {trace.citations.length > 0 ? (
          <>
            <h3 className="type-eyebrow text-ink-faint mt-6">
              Citations shown ({trace.citations.length})
            </h3>
            <ul className="mt-2 flex flex-wrap gap-2">
              {trace.citations.map((c) => (
                <li key={c.citation_id}>
                  <a
                    href={eurlexHref(c.citation_id)}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="border-hairline bg-paper hover:border-grounded/45 type-micro inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono"
                  >
                    {c.citation_label}
                    <ArrowUpRightIcon className="text-ink-faint size-3" aria-hidden />
                  </a>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </section>

      <RetrievalTable candidates={trace.candidates} retrieval={trace.retrieval} />
    </div>
  );
}

/** Fetches through the BFF unless given `initial` (the dev harness). */
export function TraceDetail({ id, initial }: { id: string; initial?: Trace }) {
  const [trace, setTrace] = useState<Trace | null>(initial ?? null);
  const [status, setStatus] = useState<"loading" | "ok" | "missing" | "error">(
    initial ? "ok" : "loading",
  );

  useEffect(() => {
    if (initial) return;
    let cancelled = false;
    fetch(`/api/admin/traces/${encodeURIComponent(id)}`, { cache: "no-store" })
      .then(async (r) => {
        if (cancelled) return;
        if (r.status === 404) return setStatus("missing");
        if (!r.ok) return setStatus("error");
        setTrace((await r.json()) as Trace);
        setStatus("ok");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [id, initial]);

  if (status === "loading") {
    return (
      <div className="space-y-4" role="status" aria-label="Loading trace">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (status === "missing") {
    return <p className="type-body text-ink-soft">Trace not found.</p>;
  }
  if (status === "error" || !trace) {
    return <p className="type-body text-ink-soft">That trace could not be loaded right now.</p>;
  }
  return <TraceDetailView trace={trace} />;
}
