"use client";

import { useEffect, useState } from "react";

import {
  AlertTriangleIcon,
  CircleSlashIcon,
  ClockIcon,
  ScaleIcon,
  WifiOffIcon,
} from "lucide-react";

import { AssessCta } from "@/components/chat/assess-cta";
import { CitationsDisclosure } from "@/components/chat/citations-disclosure";
import {
  REFUSAL_LEAD,
  REFUSAL_TITLE,
  SCOPE_EXAMPLES,
  SCOPE_MESSAGE,
  SCOPE_TITLE,
} from "@/lib/scope-copy";
import type { ChatTurn } from "@/lib/types";

function Bubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-4">
      <span className="bg-brand-solid text-brand-on mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg">
        <ScaleIcon className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-5">{children}</div>
    </div>
  );
}

export function UserTurn({ question }: { question: string }) {
  return (
    <div className="flex justify-end">
      <p className="bg-muted type-body max-w-[85%] rounded-2xl rounded-br-md px-4.5 py-3 whitespace-pre-wrap sm:max-w-[75%]">
        {question}
      </p>
    </div>
  );
}

/**
 * Nothing to answer, said purposefully. Two cases share the copy:
 *   scope  a greeting or empty input, answered before any paid call (no
 *          retrieval happened); title says what the copilot is for.
 *   refusal the retrieved provisions did not answer the question; the lead
 *          says so, and the same scope copy follows. The refusal itself is
 *          unchanged upstream; this is presentation.
 * Both show what CAN be asked and the route to an assessment. Caution tone
 * stays reserved for the genuine refusal.
 */
function AbstentionTurn({ question, scope }: { question?: string; scope: boolean }) {
  return (
    <Bubble>
      <div
        className={`rounded-2xl border p-5 sm:p-6 ${
          scope ? "card-raised" : "border-caution/35 bg-caution/[0.07]"
        }`}
        data-testid={scope ? "scope-notice" : "refusal"}
      >
        <div className="flex items-center gap-2.5">
          {scope ? (
            <ScaleIcon className="text-accent-solid size-[18px]" aria-hidden />
          ) : (
            <CircleSlashIcon className="text-caution size-[18px]" aria-hidden />
          )}
          <h3 className="type-h3">{scope ? SCOPE_TITLE : REFUSAL_TITLE}</h3>
        </div>
        {scope ? null : <p className="type-body text-ink-soft mt-3">{REFUSAL_LEAD}</p>}
        <p className={`type-body text-ink-soft ${scope ? "mt-3" : "mt-2"}`}>{SCOPE_MESSAGE}</p>
        <p className="type-eyebrow text-ink-faint mt-5">You can ask, for example</p>
        <ul className="mt-2 space-y-1.5">
          {SCOPE_EXAMPLES.map((q) => (
            <li key={q} className="type-meta text-ink flex items-start gap-2">
              <span className="bg-accent-solid mt-2.5 size-1 shrink-0 rounded-full" aria-hidden />
              {q}
            </li>
          ))}
        </ul>
        <AssessCta text={question} variant="refusal" />
        <p className="type-micro text-ink-faint mt-4">Informational, not legal advice.</p>
      </div>
    </Bubble>
  );
}

function ErrorTurn({ kind, message }: Extract<ChatTurn, { role: "error" }>) {
  const Icon =
    kind === "rate_limited_daily" || kind === "rate_limited_burst"
      ? ClockIcon
      : kind === "unavailable"
        ? WifiOffIcon
        : AlertTriangleIcon;

  const title =
    kind === "rate_limited_daily"
      ? "Daily limit reached"
      : kind === "rate_limited_burst"
        ? "Slow down a moment"
        : kind === "unavailable"
          ? "Copilot unavailable"
          : "Something went wrong";

  return (
    <Bubble>
      <div className="border-border bg-muted/30 rounded-2xl border p-5 sm:p-6">
        <div className="flex items-center gap-2.5">
          <Icon className="text-ink-soft size-[18px]" aria-hidden />
          <h3 className="type-h3">{title}</h3>
        </div>
        <p className="type-body text-ink-soft mt-3">{message}</p>
      </div>
    </Bubble>
  );
}

/** `question` is the user message this turn answers; it rides along into the
 *  assessment's describe box via the CTA. Rendering is otherwise unchanged. */
export function AssistantTurn({ turn, question }: { turn: ChatTurn; question?: string }) {
  if (turn.role === "error") return <ErrorTurn {...turn} />;
  if (turn.role !== "assistant") return null;
  if (turn.result.abstained) {
    return <AbstentionTurn question={question} scope={Boolean(turn.result.scope_notice)} />;
  }

  return (
    <Bubble>
      {turn.result.rewritten_query ? (
        <p className="type-micro text-ink-faint" data-testid="rewritten-query">
          Understood as: <span className="text-ink-soft">{turn.result.rewritten_query}</span>
        </p>
      ) : null}
      <div className="type-body whitespace-pre-wrap">{turn.result.answer}</div>

      <CitationsDisclosure citations={turn.result.citations} />
      <AssessCta text={question} variant="answer" />
    </Bubble>
  );
}

/**
 * In-flight turn. Honest by construction: it never names a stage it cannot
 * see. The bar says a request is running from the first frame; the copy
 * arrives after a second so a fast answer never flashes a sentence; a
 * second, calmer line after eight seconds says longer questions take longer
 * (the profiled pipeline: simple turns about 6 s, questions with several
 * parts up to 19 s). Unmounted by ChatPanel the moment the answer or the
 * abstention lands. `startedAt` exists so a harness can render a later
 * phase without waiting.
 */
export const PENDING_COPY = {
  early: "Working through the Act. Complex questions check several provisions and can take a few seconds.",
  late: "Still working. Questions with several parts can take up to 20 seconds. The answer will cite the provisions it relies on.",
} as const;
const PENDING_COPY_AT_MS = 1000;
const PENDING_LATE_AT_MS = 8000;

type PendingPhase = "bar" | "early" | "late";

export function PendingTurn({ startedAt }: { startedAt?: number } = {}) {
  const [started] = useState(() => startedAt ?? Date.now());
  const [phase, setPhase] = useState<PendingPhase>(() => phaseAt(started));

  useEffect(() => {
    const tick = () => setPhase(phaseAt(started));
    const a = window.setTimeout(tick, Math.max(0, started + PENDING_COPY_AT_MS - Date.now()));
    const b = window.setTimeout(tick, Math.max(0, started + PENDING_LATE_AT_MS - Date.now()));
    return () => {
      window.clearTimeout(a);
      window.clearTimeout(b);
    };
  }, [started]);

  return (
    <Bubble>
      <div role="status" aria-live="polite" data-testid="pending-turn" data-phase={phase} className="space-y-3">
        <div className="pending-track" aria-hidden>
          <span className="pending-sweep" />
        </div>
        {phase === "bar" ? (
          <span className="sr-only">Working on your question</span>
        ) : (
          <p className="type-meta text-ink-soft max-w-prose">{PENDING_COPY[phase]}</p>
        )}
      </div>
    </Bubble>
  );
}

function phaseAt(started: number): PendingPhase {
  const elapsed = Date.now() - started;
  if (elapsed >= PENDING_LATE_AT_MS) return "late";
  if (elapsed >= PENDING_COPY_AT_MS) return "early";
  return "bar";
}
