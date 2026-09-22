"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRightIcon, SearchIcon } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { eurlexHref } from "@/lib/eurlex";
import type { ActDefinition } from "@/lib/fastapi";

/**
 * PROTOTYPE: the Article 3 definitions, verbatim, searchable. Deterministic
 * and free: "what is a deployer?" is answered by the Act's own sentence
 * without a retrieval or a model call. Every entry links to the provision
 * view and to EUR-Lex.
 */
export function Glossary({ initial }: { initial?: ActDefinition[] }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<ActDefinition[] | null>(initial ?? null);
  const [date, setDate] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (initial) return;
    let cancelled = false;
    const t = setTimeout(() => {
      fetch(`/api/act/definitions?q=${encodeURIComponent(q)}`, { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(String(r.status));
          const body = (await r.json()) as { corpus_consolidated_date: string; definitions: ActDefinition[] };
          if (!cancelled) {
            setRows(body.definitions);
            setDate(body.corpus_consolidated_date);
            setError(false);
          }
        })
        .catch(() => {
          if (!cancelled) setError(true);
        });
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q, initial]);

  const shown = initial
    ? initial.filter((d) => !q || d.term.toLowerCase().includes(q.toLowerCase()) || d.text.toLowerCase().includes(q.toLowerCase()))
    : rows;

  return (
    <div>
      <label className="card-raised focus-within:ring-ring flex items-center gap-3 rounded-2xl px-4 py-3 focus-within:ring-2">
        <SearchIcon className="text-ink-faint size-4 shrink-0" aria-hidden />
        <span className="sr-only">Search the definitions</span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search a term: deployer, deep fake, general-purpose AI model"
          className="type-body text-ink placeholder:text-ink-faint w-full bg-transparent outline-none"
          data-testid="glossary-search"
        />
      </label>
      <p className="type-micro text-ink-faint mt-3">
        {shown ? `${shown.length} definitions` : "Loading"}
        {date ? ` in the consolidated text of ${date}` : ""}. Article 3, quoted word for word.
      </p>
      {error ? (
        <p className="type-meta text-ink-soft mt-6">The definitions could not be loaded right now.</p>
      ) : shown === null ? (
        <div className="mt-6 space-y-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 w-full rounded-2xl" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <p className="type-meta text-ink-soft mt-6">No definition in Article 3 matches that.</p>
      ) : (
        <ul className="mt-6 space-y-3">
          {shown.map((d) => (
            <li key={d.citation_id} className="card-raised rounded-2xl p-5" data-testid="definition">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <Link href={`/app/act/${encodeURIComponent(d.citation_id)}`} className="type-h3 text-ink hover:underline">
                  {d.term}
                </Link>
                <span className="flex items-center gap-3">
                  <span className="type-micro text-ink-faint font-mono">{d.citation_id}</span>
                  <a
                    href={eurlexHref(d.citation_id)}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="type-micro text-grounded inline-flex items-center gap-1 hover:underline"
                  >
                    EUR-Lex <ArrowUpRightIcon className="size-3" aria-hidden />
                  </a>
                </span>
              </div>
              <blockquote className="border-grounded/40 text-ink-soft type-meta mt-3 border-l-2 pl-3.5">{d.text}</blockquote>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
