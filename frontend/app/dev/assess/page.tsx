import { notFound } from "next/navigation";

import type { AssessmentReport as Report, Extracted, QuestionnaireDef } from "@/lib/types";

import report from "@/lib/fixtures/assessment-report.json";
import extracted from "@/lib/fixtures/extraction.json";

import { AppShell } from "@/components/app/app-shell";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

import { AssessHarness } from "./harness";
import questionnaire from "./questionnaire.json";

/** Stand-in for the server-rendered account control (no session here). */
function FakeAccount({ compact = false }: { compact?: boolean }) {
  const avatar = (
    <Avatar className="size-8">
      <AvatarFallback className="text-xs">OP</AvatarFallback>
    </Avatar>
  );
  if (compact) return avatar;
  return (
    <div className="flex items-center gap-3 px-2.5 py-2">
      {avatar}
      <span className="min-w-0">
        <span className="type-meta text-ink block truncate font-medium">Operator</span>
        <span className="type-micro text-ink-faint block truncate">operator@example.com</span>
      </span>
    </div>
  );
}

/**
 * Design harness for the assessment wedge. 404 in production. All fixtures
 * were produced by the real backend code path (an HR-tech recruitment system,
 * provider and deployer, SME with EUR 2M turnover); the extraction fixture is
 * a real gpt-4o-mini output from eval run 4 (21 Sep 2026), mapped by the real
 * mapper, so the badges and quotes are what a user would see.
 *
 *   /dev/assess                 the report
 *   /dev/assess?view=form       the questionnaire, blank
 *   /dev/assess?view=describe   the free-text entry screen (?describe= pre-fills it)
 *   /dev/assess?view=extracted  the questionnaire pre-filled from a description
 *   &shell=1                    any of the above inside the signed-in app shell
 */
export default async function AssessPreview({
  searchParams,
}: {
  searchParams: Promise<{ view?: string; describe?: string; shell?: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { view, describe, shell } = await searchParams;
  const v =
    view === "form" || view === "describe" || view === "extracted" ? view : ("report" as const);
  const harness = (
    <AssessHarness
      view={v}
      report={report as unknown as Report}
      def={questionnaire as unknown as QuestionnaireDef}
      extracted={extracted as unknown as Extracted}
      initialDescription={typeof describe === "string" ? describe : undefined}
    />
  );
  if (shell === "1") {
    return (
      <AppShell
        account={<FakeAccount />}
        accountCompact={<FakeAccount compact />}
        title="Assessment"
        width="form"
      >
        <p className="type-eyebrow text-ink-faint mb-6">Preview harness, not a product page</p>
        {harness}
      </AppShell>
    );
  }
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <p className="type-eyebrow text-ink-faint mb-8">Preview harness, not a product page</p>
      {harness}
    </main>
  );
}
