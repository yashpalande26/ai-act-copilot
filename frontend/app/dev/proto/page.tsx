import { notFound } from "next/navigation";

import { Glossary } from "@/components/act/glossary";
import { AssessmentTimeline } from "@/components/act/timeline";
import type { ActDefinition } from "@/lib/fastapi";
import type { AssessmentReport } from "@/lib/types";

import definitions from "@/lib/fixtures/act-definitions.json";
import report from "@/lib/fixtures/assessment-report.json";

/**
 * PROTOTYPE harness. 404 in production. Both fixtures are real: eight
 * Article 3 definitions from the corpus, and the HR-tech assessment report.
 *   /dev/proto?view=glossary
 *   /dev/proto?view=timeline
 */
export default async function ProtoPreview({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  if (process.env.NODE_ENV === "production") notFound();
  const { view } = await searchParams;
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <p className="type-eyebrow text-ink-faint mb-8">Prototype harness, not a product page</p>
      {view === "timeline" ? (
        <AssessmentTimeline id="00000000-0000-4000-8000-000000000000" initialReport={report as unknown as AssessmentReport} />
      ) : (
        <Glossary initial={definitions as ActDefinition[]} />
      )}
    </main>
  );
}
