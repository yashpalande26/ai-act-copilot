import { notFound } from "next/navigation";

import type { AssessmentReport as Report, Extracted, QuestionnaireDef } from "@/lib/types";

import report from "@/lib/fixtures/assessment-report.json";
import extracted from "@/lib/fixtures/extraction.json";

import { AssessHarness } from "./harness";
import questionnaire from "./questionnaire.json";

/**
 * Design harness for the assessment wedge. 404 in production. All fixtures
 * were produced by the real backend code path (an HR-tech recruitment system,
 * provider and deployer, SME with EUR 2M turnover); the extraction fixture is
 * a real gpt-4o-mini output from eval run 4 (21 Sep 2026), mapped by the real
 * mapper, so the badges and quotes are what a user would see.
 *
 *   /dev/assess                 the report
 *   /dev/assess?view=form       the questionnaire, blank
 *   /dev/assess?view=describe   the free-text entry screen
 *   /dev/assess?view=extracted  the questionnaire pre-filled from a description
 */
export default async function AssessPreview({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { view } = await searchParams;
  const v =
    view === "form" || view === "describe" || view === "extracted" ? view : ("report" as const);
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <p className="type-eyebrow text-ink-faint mb-8">Preview harness, not a product page</p>
      <AssessHarness
        view={v}
        report={report as unknown as Report}
        def={questionnaire as unknown as QuestionnaireDef}
        extracted={extracted as unknown as Extracted}
      />
    </main>
  );
}
