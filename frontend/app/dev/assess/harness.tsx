"use client";

import { DescribeScreen } from "@/components/assess/assess-flow";
import { Questionnaire, initialFromExtraction } from "@/components/assess/questionnaire";
import { AssessmentReport } from "@/components/assess/report";
import type { AssessmentReport as Report, Extracted, QuestionnaireDef } from "@/lib/types";

export function AssessHarness({
  view,
  report,
  def,
  extracted,
  initialDescription,
}: {
  view: "report" | "form" | "describe" | "extracted";
  report: Report;
  def: QuestionnaireDef;
  extracted: Extracted;
  initialDescription?: string;
}) {
  if (view === "form") return <Questionnaire def={def} onSubmit={() => undefined} />;
  if (view === "describe") {
    return (
      <DescribeScreen
        busy={false}
        initialText={initialDescription}
        onExtract={() => undefined}
        onSkip={() => undefined}
      />
    );
  }
  if (view === "extracted") {
    return (
      <Questionnaire
        def={def}
        initial={initialFromExtraction(def, extracted)}
        provenance={extracted.provenance}
        quotes={extracted.quotes}
        intro={extracted.note}
        onSubmit={() => undefined}
      />
    );
  }
  return <AssessmentReport report={report} />;
}
