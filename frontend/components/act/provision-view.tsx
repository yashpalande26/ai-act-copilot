"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon } from "lucide-react";

import { Provision } from "@/components/assess/provision";
import { Skeleton } from "@/components/ui/skeleton";
import type { ActProvisionView, ActReference } from "@/lib/fastapi";

function RefList({ title, items, empty }: { title: string; items: ActReference[]; empty: string }) {
  return (
    <section>
      <p className="type-eyebrow text-ink-faint">{title}</p>
      {items.length === 0 ? (
        <p className="type-micro text-ink-soft mt-2">{empty}</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((r) => (
            <li key={r.citation_id + r.snippet} className="card-raised rounded-xl px-4 py-3">
              <Link href={`/app/act/${encodeURIComponent(r.citation_id)}`} className="type-meta text-ink font-medium hover:underline">
                {r.citation_label}
              </Link>
              <span className="type-micro text-ink-faint ml-2 font-mono">{r.citation_id}</span>
              <p className="type-micro text-ink-soft mt-1">{r.snippet}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * PROTOTYPE: one provision, verbatim, with the cross-references the Act's own
 * wording carries (what it points at, what points at it). Nothing here is
 * generated: the text is the corpus, the references are parsed from it.
 */
export function ProvisionViewer({ cid, initial }: { cid: string; initial?: ActProvisionView }) {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "missing" } | { kind: "error" } | { kind: "ok"; view: ActProvisionView }>(
    initial ? { kind: "ok", view: initial } : { kind: "loading" },
  );

  useEffect(() => {
    if (initial) return;
    let cancelled = false;
    fetch(`/api/act/provisions/${encodeURIComponent(cid)}`, { cache: "no-store" })
      .then(async (r) => {
        if (cancelled) return;
        if (r.status === 404) return setState({ kind: "missing" });
        if (!r.ok) return setState({ kind: "error" });
        setState({ kind: "ok", view: (await r.json()) as ActProvisionView });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [cid, initial]);

  if (state.kind === "loading") {
    return (
      <div className="space-y-4" role="status" aria-label="Loading provision">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-40 w-full rounded-2xl" />
      </div>
    );
  }
  if (state.kind === "missing") return <p className="type-body text-ink-soft">No provision with that citation id.</p>;
  if (state.kind === "error") return <p className="type-body text-ink-soft">The provision could not be loaded right now.</p>;

  const { view } = state;
  return (
    <div className="space-y-10">
      <div>
        <Link href="/app/act" className="type-micro text-ink-soft hover:text-ink inline-flex items-center gap-1.5">
          <ArrowLeftIcon className="size-3.5" aria-hidden />
          Definitions
        </Link>
        {view.parent ? (
          <p className="type-micro text-ink-faint mt-3">
            Within{" "}
            <Link href={`/app/act/${encodeURIComponent(view.parent.citation_id)}`} className="text-grounded hover:underline">
              {view.parent.citation_label}
            </Link>
          </p>
        ) : null}
        <div className="mt-4">
          <Provision p={view.provision} />
        </div>
        <p className="type-micro text-ink-faint mt-3">Consolidated text of {view.corpus_consolidated_date}, quoted word for word.</p>
      </div>
      <div className="grid gap-8 lg:grid-cols-2">
        <RefList title="This provision refers to" items={view.references} empty="No cross-references in its wording." />
        <RefList title="Referred to by" items={view.referenced_by} empty="No other provision names this article." />
      </div>
    </div>
  );
}
