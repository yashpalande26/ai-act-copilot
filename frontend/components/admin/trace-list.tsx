"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { TraceSummary } from "@/lib/types";

const ENVIRONMENTS = ["all", "production", "dev", "test"] as const;
type EnvFilter = (typeof ENVIRONMENTS)[number];

function EnvBadge({ env }: { env: string }) {
  const tone =
    env === "production" ? "bg-grounded/10 text-grounded" : "bg-muted text-ink-soft";
  return <span className={`type-micro rounded-full px-2 py-0.5 font-mono ${tone}`}>{env}</span>;
}

type Page = { traces: TraceSummary[]; next_before: string | null };

/** Fetches through the BFF unless given `initial` (the dev harness). */
export function TraceList({ initial }: { initial?: Page }) {
  const [env, setEnv] = useState<EnvFilter>("all");
  const [rows, setRows] = useState<TraceSummary[]>(initial?.traces ?? []);
  const [nextBefore, setNextBefore] = useState<string | null>(initial?.next_before ?? null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">(initial ? "ok" : "loading");
  const [loadingMore, setLoadingMore] = useState(false);

  async function fetchPage(before?: string): Promise<Page | null> {
    const qs = new URLSearchParams({ limit: "50" });
    if (env !== "all") qs.set("environment", env);
    if (before) qs.set("before", before);
    try {
      const r = await fetch(`/api/admin/traces?${qs}`, { cache: "no-store" });
      if (!r.ok) return null;
      return (await r.json()) as Page;
    } catch {
      return null;
    }
  }

  useEffect(() => {
    if (initial) return;
    let cancelled = false;
    fetchPage().then((page) => {
      if (cancelled) return;
      if (!page) return setStatus("error");
      setRows(page.traces);
      setNextBefore(page.next_before);
      setStatus("ok");
    });
    return () => {
      cancelled = true;
    };
    // env is the only input that should refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [env, initial]);

  async function loadMore() {
    if (!nextBefore) return;
    setLoadingMore(true);
    const page = await fetchPage(nextBefore);
    if (page) {
      setRows((r) => [...r, ...page.traces]);
      setNextBefore(page.next_before);
    }
    setLoadingMore(false);
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="type-h2">Query traces</h1>
          <p className="type-meta text-ink-soft mt-2">
            Every answered question, newest first. Operator view; contains user questions.
          </p>
        </div>
        <label className="type-micro text-ink-soft flex items-center gap-2">
          Environment
          <select
            value={env}
            onChange={(e) => setEnv(e.target.value as EnvFilter)}
            className="border-hairline bg-card type-meta focus-visible:ring-ring rounded-lg border px-2.5 py-1.5 focus-visible:ring-2 focus-visible:outline-none"
          >
            {ENVIRONMENTS.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="border-hairline mt-6 overflow-x-auto rounded-2xl border">
        <table className="w-full min-w-[52rem] border-collapse text-left">
          <thead className="bg-card">
            <tr className="type-micro text-ink-soft [&>th]:px-3 [&>th]:py-2.5 [&>th]:font-medium [&>th]:whitespace-nowrap">
              <th scope="col">When</th>
              <th scope="col">Env</th>
              <th scope="col" className="w-[40%]">
                Question
              </th>
              <th scope="col">Retrieval</th>
              <th scope="col" className="text-right">
                Tokens
              </th>
              <th scope="col" className="text-right">
                Latency
              </th>
            </tr>
          </thead>
          <tbody>
            {status === "loading" ? (
              [0, 1, 2, 3, 4].map((i) => (
                <tr key={i} className="border-hairline border-t">
                  <td colSpan={6} className="px-3 py-3">
                    <Skeleton className="h-4 w-full" />
                  </td>
                </tr>
              ))
            ) : status === "error" ? (
              <tr className="border-hairline border-t">
                <td colSpan={6} className="type-meta text-ink-soft px-3 py-6">
                  Traces could not be loaded right now.
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr className="border-hairline border-t">
                <td colSpan={6} className="type-meta text-ink-soft px-3 py-6">
                  No traces yet.
                </td>
              </tr>
            ) : (
              rows.map((t) => (
                <tr
                  key={t.id}
                  className="border-hairline hover:bg-grounded/[0.04] type-meta border-t align-top [&>td]:px-3 [&>td]:py-2.5"
                >
                  <td className="type-micro font-mono whitespace-nowrap">
                    {new Date(t.created_at).toLocaleString()}
                  </td>
                  <td>
                    <EnvBadge env={t.environment} />
                  </td>
                  <td>
                    <Link
                      href={`/app/admin/traces/${t.id}`}
                      className="focus-visible:ring-ring line-clamp-2 rounded-sm hover:underline focus-visible:ring-2 focus-visible:outline-none"
                    >
                      {t.question}
                    </Link>
                    {t.abstained ? (
                      <span className="type-micro bg-caution/[0.12] text-caution mt-1 inline-block rounded-full px-2 py-0.5">
                        abstained
                      </span>
                    ) : null}
                  </td>
                  <td className="type-micro font-mono">{t.retrieval_config}</td>
                  <td className="text-right font-mono tabular-nums whitespace-nowrap">
                    {t.prompt_tokens ?? "–"} / {t.completion_tokens ?? "–"}
                  </td>
                  <td className="text-right font-mono tabular-nums whitespace-nowrap">
                    {t.retrieval_latency_ms} / {t.generation_latency_ms ?? "–"} ms
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {nextBefore ? (
        <div className="mt-4 flex justify-center">
          <Button type="button" variant="outline" onClick={loadMore} disabled={loadingMore}>
            {loadingMore ? "Loading" : "Load more"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
