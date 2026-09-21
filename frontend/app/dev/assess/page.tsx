import { notFound } from "next/navigation";

import type { AssessmentReport as Report, QuestionnaireDef } from "@/lib/types";

import { AssessHarness } from "./harness";
import questionnaire from "./questionnaire.json";
import report from "./report.json";

/**
 * Design harness for the assessment wedge. 404 in production. Both fixtures
 * were produced by the real backend code path (an HR-tech recruitment system,
 * provider and deployer, SME with EUR 2M turnover), so every quoted provision
 * is the corpus text.
 *
 *   /dev/assess             the report
 *   /dev/assess?view=form   the questionnaire
 */
export default async function AssessPreview({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { view } = await searchParams;
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <p className="type-eyebrow text-ink-faint mb-8">Preview harness, not a product page</p>
      <AssessHarness
        view={view === "form" ? "form" : "report"}
        report={report as unknown as Report}
        def={questionnaire as unknown as QuestionnaireDef}
      />
    </main>
  );
}
