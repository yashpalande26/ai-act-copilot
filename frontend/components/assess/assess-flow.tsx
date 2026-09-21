"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Commentary } from "@/components/assess/provision";
import { Questionnaire, initialFromExtraction } from "@/components/assess/questionnaire";
import { AssessmentReport } from "@/components/assess/report";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type {
  Answers,
  AssessmentReport as Report,
  Extracted,
  QuestionnaireDef,
} from "@/lib/types";

const MAX_DESCRIPTION_CHARS = 4000;

type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; id: string }
  | { kind: "failed"; message: string };

/** What the questionnaire started from. Carried to the save call so the
 *  record can say the answers were pre-filled and confirmed. */
type Origin = { extracted: Extracted } | null;

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "describe"; def: QuestionnaireDef; busy: boolean; error?: string }
  | {
      kind: "form";
      def: QuestionnaireDef;
      submitting: boolean;
      answers?: Answers;
      origin: Origin;
      error?: string;
    }
  | {
      kind: "report";
      def: QuestionnaireDef;
      report: Report;
      answers: Answers;
      origin: Origin;
      save: SaveState;
    };

/** Copy calibrated on the extraction eval of 21 Sep 2026 (verdict A 53%,
 *  gold-known-correct 27%): a head start, not a filled form. */
export function DescribeScreen({
  busy,
  error,
  onExtract,
  onSkip,
}: {
  busy: boolean;
  error?: string;
  onExtract: (description: string) => void;
  onSkip: () => void;
}) {
  const [text, setText] = useState("");
  const trimmed = text.trim();
  const tooShort = trimmed.length < 20;
  return (
    <div className="space-y-5">
      <div>
        <h2 className="type-h2">Describe the system</h2>
        <p className="type-meta text-ink-soft mt-2 max-w-[42rem]">
          A few sentences on what it does, who builds it, who uses it, and where. We use them to give you
          a head start on the questionnaire: some answers will be filled in with the passage they came
          from, the rest are marked for you to answer. You confirm every answer before anything is
          assessed. Nothing is stored unless you save the result.
        </p>
      </div>
      <label className="block">
        <span className="sr-only">Description of the AI system</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_DESCRIPTION_CHARS))}
          rows={7}
          disabled={busy}
          placeholder="Example: We are a Dutch logistics company. Our data team built a model that forecasts pallet volumes per warehouse; planners read the output in a spreadsheet and nobody outside the team interacts with it."
          className="border-hairline bg-paper type-body focus-visible:ring-ring w-full rounded-2xl border px-4 py-3 focus-visible:ring-2 focus-visible:outline-none disabled:opacity-60"
        />
      </label>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="type-micro text-ink-faint" aria-live="polite">
          {text.length.toLocaleString()} / {MAX_DESCRIPTION_CHARS.toLocaleString()}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={onSkip} disabled={busy}>
            Fill in the questionnaire by hand
          </Button>
          <Button type="button" onClick={() => onExtract(trimmed)} disabled={busy || tooShort}>
            {busy ? "Reading your description" : "Pre-fill the questionnaire"}
          </Button>
        </div>
      </div>
      {error ? (
        <p className="type-meta text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <Commentary>
        Pre-filling reads your description with a language model. It fills in the form only: it never
        decides the risk tier and never writes legal text. Five questions that are legal characterisations
        are always left for you.
      </Commentary>
    </div>
  );
}

/** Describe (optional) -> questionnaire -> report, on screen, nothing stored. */
export function AssessFlow() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch("/api/assess/questionnaire", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const def = (await r.json()) as QuestionnaireDef;
        if (!cancelled) setState({ kind: "describe", def, busy: false });
      })
      .catch(() => {
        if (!cancelled)
          setState({ kind: "error", message: "The questionnaire could not be loaded right now." });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function extract(def: QuestionnaireDef, description: string) {
    setState({ kind: "describe", def, busy: true });
    try {
      const r = await fetch("/api/assess/extract", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ description }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setState({
          kind: "describe",
          def,
          busy: false,
          error: body?.message ?? "Could not pre-fill the questionnaire. You can fill it in by hand.",
        });
        return;
      }
      const extracted = (await r.json()) as Extracted;
      setState({
        kind: "form",
        def,
        submitting: false,
        answers: initialFromExtraction(def, extracted),
        origin: { extracted },
      });
    } catch {
      setState({
        kind: "describe",
        def,
        busy: false,
        error: "We couldn't reach the service. Check your connection and try again.",
      });
    }
  }

  async function submit(def: QuestionnaireDef, answers: Answers, origin: Origin) {
    setState({ kind: "form", def, submitting: true, answers, origin });
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
          origin,
          error: body?.message ?? "The report could not be built.",
        });
        return;
      }
      setState({
        kind: "report",
        def,
        report: (await r.json()) as Report,
        answers,
        origin,
        save: { kind: "idle" },
      });
    } catch {
      setState({
        kind: "form",
        def,
        submitting: false,
        answers,
        origin,
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
  if (state.kind === "describe") {
    const { def } = state;
    return (
      <DescribeScreen
        busy={state.busy}
        error={state.error}
        onExtract={(d) => void extract(def, d)}
        onSkip={() => setState({ kind: "form", def, submitting: false, origin: null })}
      />
    );
  }
  if (state.kind === "report") {
    const { save, origin } = state;
    // Only the answers are sent; the backend re-derives and stores the result.
    async function saveNow() {
      if (state.kind !== "report") return;
      setState({ ...state, save: { kind: "saving" } });
      try {
        const qs = origin ? `?extraction_id=${encodeURIComponent(origin.extracted.id)}` : "";
        const r = await fetch(`/api/assessments${qs}`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(state.answers),
        });
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          setState({ ...state, save: { kind: "failed", message: body?.message ?? "Could not save." } });
          return;
        }
        const saved = (await r.json()) as { id: string };
        setState({ ...state, save: { kind: "saved", id: saved.id } });
      } catch {
        setState({ ...state, save: { kind: "failed", message: "We couldn't reach the service." } });
      }
    }

    return (
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="type-micro text-ink-soft" role="status">
            {save.kind === "saved" ? (
              <>
                Saved.{" "}
                <Link href={`/app/assess/${save.id}`} className="text-grounded hover:underline">
                  Open the saved assessment
                </Link>
                .
              </>
            ) : save.kind === "failed" ? (
              save.message
            ) : (
              "Not stored until you save it. Saving keeps your answers; the quoted text is rendered from the current corpus when reopened."
            )}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                setState({ kind: "form", def: state.def, submitting: false, answers: state.answers, origin })
              }
            >
              Edit answers
            </Button>
            {save.kind !== "saved" ? (
              <Button type="button" onClick={() => void saveNow()} disabled={save.kind === "saving"}>
                {save.kind === "saving" ? "Saving" : "Save this assessment"}
              </Button>
            ) : null}
          </div>
        </div>
        {origin ? (
          <Commentary>
            Answers were pre-filled from your description and confirmed by you before this report was
            built. The result is the deterministic engine&apos;s, from those confirmed answers.
          </Commentary>
        ) : null}
        <AssessmentReport report={state.report} />
      </div>
    );
  }
  const { origin } = state;
  return (
    <div>
      {state.error ? (
        <p className="type-meta text-destructive mb-4" role="alert">
          {state.error}
        </p>
      ) : null}
      <Questionnaire
        key={origin ? origin.extracted.id : state.answers ? "edit" : "new"}
        def={state.def}
        initial={state.answers}
        submitting={state.submitting}
        provenance={origin?.extracted.provenance}
        quotes={origin?.extracted.quotes}
        intro={origin?.extracted.note}
        onSubmit={(answers) => void submit(state.def, answers, origin)}
      />
      {origin ? (
        <p className="type-micro text-ink-faint mt-6">
          Started from a description?{" "}
          <button
            type="button"
            className="text-grounded hover:underline"
            onClick={() => setState({ kind: "describe", def: state.def, busy: false })}
          >
            Describe it again
          </button>
          .
        </p>
      ) : null}
    </div>
  );
}
