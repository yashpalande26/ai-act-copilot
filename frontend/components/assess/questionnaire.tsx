"use client";

import { useMemo, useState } from "react";
import { ChevronDownIcon } from "lucide-react";

import { Commentary, Provision } from "@/components/assess/provision";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type {
  AnswerValue,
  Answers,
  Extracted,
  Provenance,
  Question,
  QuestionnaireDef,
} from "@/lib/types";

/** Defaults mirror app/assessment/schema.py: everything off except the two
 *  questions whose natural default is yes. */
export function defaultAnswers(def: QuestionnaireDef): Answers {
  const a: Answers = {};
  for (const step of def.steps) {
    for (const q of step.questions) {
      if (q.kind === "boolean") a[q.id] = q.id === "is_ai_system" || q.id === "undertaking";
      else if (q.kind === "multiselect") a[q.id] = [];
      else if (q.kind === "select") a[q.id] = "";
      else a[q.id] = null;
    }
  }
  return a;
}

/** Answers to start from after a free-text extraction. Inferred values are
 *  kept; every unknown boolean becomes null so neither radio is selected and
 *  the person has to answer it. The engine is never run on a null. */
export function initialFromExtraction(def: QuestionnaireDef, extracted: Extracted): Answers {
  const a: Answers = { ...defaultAnswers(def), ...extracted.answers };
  for (const step of def.steps) {
    for (const q of step.questions) {
      if (extracted.provenance[q.id] !== "unknown") continue;
      if (q.kind === "boolean") a[q.id] = null;
      else if (q.kind === "select") a[q.id] = "";
      else if (q.kind === "multiselect") a[q.id] = [];
    }
  }
  return a;
}

function visible(q: Question, a: Answers): boolean {
  if (!q.show_if) return true;
  const v = a[q.show_if.field];
  if (q.show_if.any_of) {
    return Array.isArray(v) && v.some((x) => q.show_if!.any_of!.includes(x));
  }
  if (q.show_if.equals === "__any__") return typeof v === "string" && v !== "";
  return v === q.show_if.equals;
}

/** Strip UI-only values before sending: "" select means "none". */
export function toPayload(a: Answers): Answers {
  const out: Answers = {};
  for (const [k, v] of Object.entries(a)) out[k] = v === "" ? null : v;
  return out;
}

/** A question still needs the person's answer: it was left unknown by the
 *  extraction and has not been answered since. Turnover is optional either
 *  way (the ceilings say "enter turnover" without it), so it never blocks. */
function needsConfirmation(
  q: Question,
  a: Answers,
  provenance: Provenance | undefined,
  touched: Set<string>,
): boolean {
  if (!provenance || provenance[q.id] !== "unknown") return false;
  if (q.id === "turnover_eur") return false;
  if (touched.has(q.id)) return false;
  if (q.kind === "boolean") return a[q.id] === null || a[q.id] === undefined;
  return true;
}

function BasisDisclosure({ q }: { q: Question }) {
  if (q.basis.length === 0) return null;
  return (
    <Collapsible className="mt-2">
      <CollapsibleTrigger className="type-micro text-grounded group inline-flex items-center gap-1 hover:underline">
        Text of the provision{q.basis.length > 1 ? "s" : ""}
        <ChevronDownIcon className="size-3.5 transition-transform group-data-[state=open]:rotate-180" aria-hidden />
      </CollapsibleTrigger>
      <CollapsibleContent className="disclosure-content overflow-hidden">
        <div className="mt-2 space-y-3">
          {q.basis.map((p) => (
            <Provision key={p.citation_id} p={p} compact />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** Where a pre-filled answer came from. Green is the design system's
 *  "verifiable" tone: an inferred value always carries the passage that
 *  justified it. "To confirm" is neutral; nothing is wrong, it is unanswered. */
function ProvenanceBadge({
  status,
  quote,
  pending,
}: {
  status: "inferred" | "unknown";
  quote?: string;
  pending: boolean;
}) {
  if (status === "inferred") {
    return (
      <Collapsible className="min-w-0">
        <CollapsibleTrigger className="type-micro border-grounded/40 bg-grounded/[0.08] text-grounded group inline-flex max-w-full items-center gap-1 rounded-full border px-2.5 py-0.5 hover:underline">
          Inferred from your description
          <ChevronDownIcon className="size-3 transition-transform group-data-[state=open]:rotate-180" aria-hidden />
        </CollapsibleTrigger>
        {quote ? (
          <CollapsibleContent className="disclosure-content overflow-hidden">
            <blockquote className="type-micro text-ink-soft border-grounded/40 mt-2 border-l-2 pl-3">
              &ldquo;{quote}&rdquo;
            </blockquote>
          </CollapsibleContent>
        ) : null}
      </Collapsible>
    );
  }
  return (
    <span
      className={`type-micro inline-flex items-center rounded-full border px-2.5 py-0.5 ${
        pending ? "border-ink/30 text-ink font-medium" : "border-hairline text-ink-soft"
      }`}
    >
      {pending ? "To confirm: not in your description" : "Confirmed by you"}
    </span>
  );
}

function Field({
  q,
  value,
  onChange,
  provenance,
  quote,
  pending,
}: {
  q: Question;
  value: AnswerValue;
  onChange: (v: AnswerValue) => void;
  provenance?: "inferred" | "unknown";
  quote?: string;
  pending: boolean;
}) {
  const name = `q-${q.id}`;
  const labelId = `${name}-label`;
  // One visible label, referenced by id. A <fieldset>/<legend> pair was the
  // first version, but <legend> ignores absolute positioning in WebKit, so a
  // "visually hidden" legend rendered as a second copy of the question.
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      data-pending={pending || undefined}
      className={`bg-card rounded-2xl border p-4 sm:p-5 ${pending ? "border-ink/30" : "border-hairline"}`}
    >
      {provenance ? (
        <div className="mb-2 flex flex-wrap items-start gap-2">
          <ProvenanceBadge status={provenance} quote={quote} pending={pending} />
        </div>
      ) : null}
      <p id={labelId} className="type-body text-ink font-medium">
        {q.label}
      </p>
      {q.help ? <Commentary>{q.help}</Commentary> : null}

      {q.kind === "boolean" ? (
        <div className="mt-3 flex gap-2" role="radiogroup" aria-labelledby={labelId}>
          {[
            ["Yes", true],
            ["No", false],
          ].map(([label, v]) => (
            <label
              key={String(v)}
              className={`type-meta focus-within:ring-ring cursor-pointer rounded-xl border px-4 py-2 focus-within:ring-2 ${
                value === v
                  ? "border-grounded/50 bg-grounded/[0.08] text-ink"
                  : "border-hairline text-ink-soft hover:bg-muted/60"
              }`}
            >
              <input
                type="radio"
                name={name}
                className="sr-only"
                checked={value === v}
                onChange={() => onChange(v as boolean)}
              />
              {label as string}
            </label>
          ))}
        </div>
      ) : null}

      {q.kind === "number" ? (
        <input
          type="number"
          inputMode="decimal"
          min={0}
          step="1"
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          aria-labelledby={labelId}
          className="border-hairline bg-paper type-meta focus-visible:ring-ring mt-3 w-full max-w-xs rounded-xl border px-3.5 py-2 font-mono focus-visible:ring-2 focus-visible:outline-none"
          placeholder="e.g. 2000000"
        />
      ) : null}

      {q.kind === "select" || q.kind === "multiselect" ? (
        <ul className="mt-3 space-y-2">
          {q.options.map((opt) => {
            const selected =
              q.kind === "select"
                ? value === opt.value
                : Array.isArray(value) && value.includes(opt.value);
            return (
              <li key={opt.value || "__none__"}>
                <label
                  className={`focus-within:ring-ring flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-2.5 focus-within:ring-2 ${
                    selected
                      ? "border-grounded/50 bg-grounded/[0.06]"
                      : "border-hairline hover:bg-muted/60"
                  }`}
                >
                  <input
                    type={q.kind === "select" ? "radio" : "checkbox"}
                    name={name}
                    className="mt-1"
                    checked={selected}
                    onChange={() => {
                      if (q.kind === "select") onChange(opt.value);
                      else {
                        const cur = Array.isArray(value) ? value : [];
                        onChange(
                          selected ? cur.filter((x) => x !== opt.value) : [...cur, opt.value],
                        );
                      }
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="type-meta block">{opt.label}</span>
                    {opt.basis ? (
                      <span className="type-micro text-ink-soft mt-1 line-clamp-3 block">
                        {opt.basis.text}
                      </span>
                    ) : null}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      ) : null}

      <BasisDisclosure q={q} />
    </div>
  );
}

export function Questionnaire({
  def,
  onSubmit,
  submitting = false,
  initial,
  provenance,
  quotes,
  intro,
}: {
  def: QuestionnaireDef;
  onSubmit: (answers: Answers) => void;
  submitting?: boolean;
  initial?: Answers;
  /** Present after a free-text extraction; turns on badges and the gate. */
  provenance?: Provenance;
  quotes?: Record<string, string>;
  intro?: string;
}) {
  const [answers, setAnswers] = useState<Answers>(() => initial ?? defaultAnswers(def));
  const [touched, setTouched] = useState<Set<string>>(() => new Set());
  const [stepIndex, setStepIndex] = useState(0);
  const step = def.steps[stepIndex];
  const shown = useMemo(() => step.questions.filter((q) => visible(q, answers)), [step, answers]);
  const last = stepIndex === def.steps.length - 1;

  // Every visible question, on any step, that still needs an answer. The
  // engine is not run until this is empty: an unknown never becomes a
  // silent default.
  const pendingByStep = useMemo(
    () =>
      def.steps.map((s) =>
        s.questions
          .filter((q) => visible(q, answers) && needsConfirmation(q, answers, provenance, touched))
          .map((q) => q.id),
      ),
    [def.steps, answers, provenance, touched],
  );
  const pendingTotal = pendingByStep.reduce((n, ids) => n + ids.length, 0);
  const pendingHere = new Set(pendingByStep[stepIndex]);

  function change(id: string, v: AnswerValue) {
    setAnswers((a) => ({ ...a, [id]: v }));
    setTouched((t) => (t.has(id) ? t : new Set(t).add(id)));
  }

  return (
    <div>
      <ol className="type-micro text-ink-faint mb-6 flex flex-wrap gap-x-4 gap-y-1" aria-label="Steps">
        {def.steps.map((s, i) => (
          <li
            key={s.key}
            aria-current={i === stepIndex ? "step" : undefined}
            className={i === stepIndex ? "text-ink font-medium" : i < stepIndex ? "text-ink-soft" : ""}
          >
            {i + 1}. {s.title}
            {pendingByStep[i].length ? (
              <span className="text-ink ml-1 font-medium" aria-label={`${pendingByStep[i].length} to confirm`}>
                ({pendingByStep[i].length})
              </span>
            ) : null}
          </li>
        ))}
      </ol>

      {provenance && stepIndex === 0 && intro ? (
        <div className="mb-6">
          <Commentary>{intro}</Commentary>
        </div>
      ) : null}

      <h2 className="type-h2">{step.title}</h2>
      {step.intro ? <p className="type-meta text-ink-soft mt-2">{step.intro}</p> : null}

      <div className="mt-6 space-y-4">
        {shown.map((q) => (
          <Field
            key={q.id}
            q={q}
            value={answers[q.id]}
            onChange={(v) => change(q.id, v)}
            provenance={provenance?.[q.id]}
            quote={quotes?.[q.id]}
            pending={pendingHere.has(q.id)}
          />
        ))}
      </div>

      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
        <Button
          type="button"
          variant="outline"
          onClick={() => setStepIndex((i) => Math.max(0, i - 1))}
          disabled={stepIndex === 0 || submitting}
        >
          Back
        </Button>
        {last ? (
          <div className="flex flex-wrap items-center gap-3">
            {pendingTotal ? (
              <p className="type-micro text-ink-soft" role="status">
                {pendingTotal} {pendingTotal === 1 ? "answer" : "answers"} still to confirm before the report
                can be built.
              </p>
            ) : null}
            <Button
              type="button"
              onClick={() => onSubmit(toPayload(answers))}
              disabled={submitting || pendingTotal > 0}
              data-testid="build-report"
            >
              {submitting ? "Building the report" : "Build the report"}
            </Button>
          </div>
        ) : (
          <Button type="button" onClick={() => setStepIndex((i) => i + 1)}>
            Next
          </Button>
        )}
      </div>
    </div>
  );
}
