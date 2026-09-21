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
import type { AnswerValue, Answers, Question, QuestionnaireDef } from "@/lib/types";

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

function Field({
  q,
  value,
  onChange,
}: {
  q: Question;
  value: AnswerValue;
  onChange: (v: AnswerValue) => void;
}) {
  const name = `q-${q.id}`;
  return (
    <fieldset className="border-hairline bg-card rounded-2xl border p-4 sm:p-5">
      <legend className="sr-only">{q.label}</legend>
      <p className="type-body text-ink font-medium">{q.label}</p>
      {q.help ? <Commentary>{q.help}</Commentary> : null}

      {q.kind === "boolean" ? (
        <div className="mt-3 flex gap-2" role="radiogroup" aria-label={q.label}>
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
          aria-label={q.label}
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
    </fieldset>
  );
}

export function Questionnaire({
  def,
  onSubmit,
  submitting = false,
  initial,
}: {
  def: QuestionnaireDef;
  onSubmit: (answers: Answers) => void;
  submitting?: boolean;
  initial?: Answers;
}) {
  const [answers, setAnswers] = useState<Answers>(() => initial ?? defaultAnswers(def));
  const [stepIndex, setStepIndex] = useState(0);
  const step = def.steps[stepIndex];
  const shown = useMemo(() => step.questions.filter((q) => visible(q, answers)), [step, answers]);
  const last = stepIndex === def.steps.length - 1;

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
          </li>
        ))}
      </ol>

      <h2 className="type-h2">{step.title}</h2>
      {step.intro ? <p className="type-meta text-ink-soft mt-2">{step.intro}</p> : null}

      <div className="mt-6 space-y-4">
        {shown.map((q) => (
          <Field
            key={q.id}
            q={q}
            value={answers[q.id]}
            onChange={(v) => setAnswers((a) => ({ ...a, [q.id]: v }))}
          />
        ))}
      </div>

      <div className="mt-8 flex items-center justify-between gap-3">
        <Button
          type="button"
          variant="outline"
          onClick={() => setStepIndex((i) => Math.max(0, i - 1))}
          disabled={stepIndex === 0 || submitting}
        >
          Back
        </Button>
        {last ? (
          <Button type="button" onClick={() => onSubmit(toPayload(answers))} disabled={submitting}>
            {submitting ? "Building the report" : "Build the report"}
          </Button>
        ) : (
          <Button type="button" onClick={() => setStepIndex((i) => i + 1)}>
            Next
          </Button>
        )}
      </div>
    </div>
  );
}
