"use client";

import { useEffect, useState } from "react";

import { Questionnaire } from "@/components/assess/questionnaire";
import { AssessmentReport } from "@/components/assess/report";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Answers, AssessmentReport as Report, QuestionnaireDef } from "@/lib/types";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "form"; def: QuestionnaireDef; submitting: boolean; answers?: Answers; error?: string }
  | { kind: "report"; def: QuestionnaireDef; report: Report; answers: Answers };

/** Questionnaire -> report, on screen, nothing stored. */
export function AssessFlow() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch("/api/assess/questionnaire", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const def = (await r.json()) as QuestionnaireDef;
        if (!cancelled) setState({ kind: "form", def, submitting: false });
      })
      .catch(() => {
        if (!cancelled)
          setState({ kind: "error", message: "The questionnaire could not be loaded right now." });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(def: QuestionnaireDef, answers: Answers) {
    setState({ kind: "form", def, submitting: true, answers });
    try {
      const r = await fetch("/api/assess", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(answers),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setState({
          kind: "form",
          def,
          submitting: false,
          answers,
          error: body?.message ?? "The report could not be built.",
        });
        return;
      }
      setState({ kind: "report", def, report: (await r.json()) as Report, answers });
    } catch {
      setState({
        kind: "form",
        def,
        submitting: false,
        answers,
        error: "We couldn't reach the service. Check your connection and try again.",
      });
    }
  }

  if (state.kind === "loading") {
    return (
      <div className="space-y-4" role="status" aria-label="Loading questionnaire">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }
  if (state.kind === "error") {
    return <p className="type-body text-ink-soft">{state.message}</p>;
  }
  if (state.kind === "report") {
    return (
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="type-micro text-ink-soft">
            This report is not stored. Start over to change your answers.
          </p>
          <Button
            type="button"
            variant="outline"
            onClick={() => setState({ kind: "form", def: state.def, submitting: false, answers: state.answers })}
          >
            Edit answers
          </Button>
        </div>
        <AssessmentReport report={state.report} />
      </div>
    );
  }
  return (
    <div>
      {state.error ? (
        <p className="type-meta text-destructive mb-4" role="alert">
          {state.error}
        </p>
      ) : null}
      <Questionnaire
        key={state.answers ? "edit" : "new"}
        def={state.def}
        initial={state.answers}
        submitting={state.submitting}
        onSubmit={(answers) => void submit(state.def, answers)}
      />
    </div>
  );
}
