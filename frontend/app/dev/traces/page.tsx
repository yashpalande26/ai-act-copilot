import { notFound } from "next/navigation";

import { TraceDetail } from "@/components/admin/trace-detail";
import { TraceList } from "@/components/admin/trace-list";
import type { TraceDetail as Trace } from "@/lib/types";

import fixture from "./fixture.json";

/**
 * Design harness for the admin trace viewer. Not linked from anywhere and a
 * 404 in production. The fixture is one real trace, read from the database
 * in the exact shape GET /admin/traces/{id} returns (25 candidates, 15 in
 * context, 5 down-weighted by the actor prior).
 *
 *   /dev/traces            detail view
 *   /dev/traces?view=list  list view
 */
export default async function TracesPreview({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { view } = await searchParams;
  const trace = fixture as Trace;

  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-8">
      <p className="type-eyebrow text-ink-faint mb-8">Preview harness, not a product page</p>
      {view === "list" ? (
        <TraceList
          initial={{
            traces: [
              trace,
              { ...trace, id: "00000000-0000-4000-8000-000000000002", abstained: true, environment: "dev" },
              { ...trace, id: "00000000-0000-4000-8000-000000000003", environment: "test" },
            ],
            next_before: null,
          }}
        />
      ) : (
        <TraceDetail id={trace.id} initial={trace} />
      )}
    </main>
  );
}
