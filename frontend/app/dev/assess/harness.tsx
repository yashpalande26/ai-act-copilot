"use client";

import { Questionnaire } from "@/components/assess/questionnaire";
import { AssessmentReport } from "@/components/assess/report";
import type { AssessmentReport as Report, QuestionnaireDef } from "@/lib/types";

export function AssessHarness({
  view,
  report,
  def,
}: {
  view: "report" | "form";
  report: Report;
  def: QuestionnaireDef;
}) {
  return view === "form" ? (
    <Questionnaire def={def} onSubmit={() => undefined} />
  ) : (
    <AssessmentReport report={report} />
  );
}
