"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRightIcon,
  ArrowUpIcon,
  CircleSlashIcon,
  ClipboardCheckIcon,
  ScaleIcon,
  UsersIcon,
} from "lucide-react";

import { AssistantTurn, PendingTurn, UserTurn } from "@/components/chat/answer-turn";
import { LegalNotice } from "@/components/legal-notice";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { ChatTurn } from "@/lib/types";

/** The most recent user message before index `i` (undefined for none). */
function lastUserQuestion(turns: ChatTurn[], i: number): string | undefined {
  for (let j = i - 1; j >= 0; j--) {
    const t = turns[j];
    if (t.role === "user") return t.question;
  }
  return undefined;
}

const MAX_CHARS = 2000;

const STARTERS = [
  {
    eyebrow: "Obligations",
    icon: ScaleIcon,
    q: "What obligations apply to providers of high-risk AI systems?",
  },
  {
    eyebrow: "Classification",
    icon: ClipboardCheckIcon,
    q: "Is an AI system used for credit scoring high-risk?",
  },
  {
    eyebrow: "Prohibited practices",
    icon: CircleSlashIcon,
    q: "Which AI practices are prohibited outright?",
  },
  {
    eyebrow: "Deployers",
    icon: UsersIcon,
    q: "What must a deployer do before using a high-risk AI system?",
  },
];

type Props = {
  userName: string;
  turns: ChatTurn[];
  pending: boolean;
  /** Harness only: render a later phase of the in-flight indicator without waiting. */
  pendingStartedAt?: number;
  /** A past session is being fetched. */
  loading?: boolean;
  loadError?: string | null;
  onSubmit: (question: string) => void | Promise<void>;
};

/**
 * The conversation column: transcript, starters, composer. Presentational
 * since the history work: the thread and the session live in useChatSession
 * (via ChatShell), so reopening a past chat swaps `turns` from above.
 */
export function ChatPanel({
  userName,
  turns,
  pending,
  pendingStartedAt,
  loading = false,
  loadError = null,
  onSubmit,
}: Props) {
  const [question, setQuestion] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Follow the conversation, but leave the empty state at the top so the
    // heading and starters are what a new user sees first.
    if (turns.length === 0 && !pending) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, pending]);

  useEffect(() => {
    if (!pending) inputRef.current?.focus();
  }, [pending, turns.length]);

  function submit(raw: string) {
    const trimmed = raw.trim();
    if (!trimmed || pending || trimmed.length > MAX_CHARS) return;
    setQuestion("");
    void onSubmit(trimmed);
  }

  const empty = turns.length === 0 && !loading;
  const tooLong = question.length > MAX_CHARS;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* The transcript is the only scroll region: min-h-0 lets it shrink inside
          the flex column, overscroll-contain keeps a wheel or swipe at the end of
          the list from scrolling the document behind it. */}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" data-testid="transcript">
        <div className="mx-auto w-full max-w-[52rem] px-5 py-8 md:px-10 md:py-12">
          {loading ? (
            <div className="space-y-8" role="status" aria-live="polite" aria-label="Loading chat">
              <div className="flex justify-end">
                <Skeleton className="h-11 w-[70%] rounded-2xl" />
              </div>
              <div className="flex gap-4">
                <Skeleton className="size-8 shrink-0 rounded-lg" />
                <div className="flex-1 space-y-3">
                  <Skeleton className="h-4 w-[95%]" />
                  <Skeleton className="h-4 w-[88%]" />
                  <Skeleton className="h-4 w-[60%]" />
                </div>
              </div>
            </div>
          ) : empty ? (
            <div className="py-6 sm:py-12">
              <p className="type-eyebrow text-ink-faint">Ask the copilot</p>
              <h1 className="type-title text-ink mt-2.5 text-balance">
                What can I help you check, {userName}?
              </h1>
              <p className="type-lead text-ink-soft mt-4 max-w-[38rem] text-pretty">
                Ask about obligations, prohibited practices, or whether a system
                is high-risk. Every answer cites the provisions it came from.
              </p>
              {loadError ? (
                <p className="type-meta text-ink-soft mt-6" role="status">
                  {loadError}
                </p>
              ) : null}
              <div className="mt-10 grid gap-3 sm:grid-cols-2">
                {STARTERS.map(({ eyebrow, icon: Icon, q }) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => submit(q)}
                    className="card-raised lift group focus-visible:ring-ring hover:border-hairline-strong flex flex-col rounded-2xl p-5 text-left focus-visible:ring-2 focus-visible:outline-none"
                  >
                    <span className="flex items-center gap-2">
                      <span className="bg-accent-soft text-accent-solid flex size-7 items-center justify-center rounded-lg">
                        <Icon className="size-3.5" aria-hidden />
                      </span>
                      <span className="type-eyebrow text-ink-faint">{eyebrow}</span>
                    </span>
                    <span className="type-meta text-ink mt-3 font-medium">{q}</span>
                    <span className="type-micro text-ink-faint group-hover:text-accent-solid mt-4 inline-flex items-center gap-1 transition-colors">
                      Ask
                      <ArrowRightIcon className="size-3 transition-transform group-hover:translate-x-0.5" aria-hidden />
                    </span>
                  </button>
                ))}
              </div>
              <Link
                href="/app/assess"
                className="card-raised lift hover:border-hairline-strong focus-visible:ring-ring mt-4 flex items-center gap-4 rounded-2xl p-5 focus-visible:ring-2 focus-visible:outline-none"
              >
                <span className="bg-brand-solid text-brand-on font-display flex size-10 shrink-0 items-center justify-center rounded-xl text-[1.35rem] leading-none shadow-[inset_0_1px_0_oklch(1_0_0/0.14)]">
                  <span aria-hidden>&sect;</span>
                </span>
                <span className="min-w-0 flex-1">
                  <span className="type-meta text-ink block font-medium">Need the full record for one system?</span>
                  <span className="type-micro text-ink-soft mt-0.5 block">
                    Run the assessment: quoted obligations, dates and fine ceilings, saved and exportable.
                  </span>
                </span>
                <ArrowRightIcon className="text-ink-faint size-4 shrink-0" aria-hidden />
              </Link>
              <div className="mt-12">
                <LegalNotice />
              </div>
            </div>
          ) : (
            <div className="space-y-8">
              {turns.map((turn, i) =>
                turn.role === "user" ? (
                  <UserTurn key={turn.id} question={turn.question} />
                ) : (
                  <AssistantTurn
                    key={turn.id}
                    turn={turn}
                    // The message this turn answers, carried into the assessment CTA.
                    question={lastUserQuestion(turns, i)}
                  />
                ),
              )}
              {pending ? <PendingTurn startedAt={pendingStartedAt} /> : null}
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-hairline bg-paper/90 shrink-0 border-t backdrop-blur-md">
        <div className="mx-auto w-full max-w-[52rem] px-5 py-4 md:px-10">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(question);
            }}
          >
            <div className="border-hairline-strong bg-card focus-within:border-accent-solid/60 focus-within:ring-ring/20 flex items-end gap-2 rounded-2xl border p-2 shadow-[var(--shadow-sm)] transition-shadow focus-within:ring-4">
              <Textarea
                ref={inputRef}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit(question);
                  }
                }}
                rows={1}
                disabled={pending || loading}
                aria-label="Your question about the EU AI Act"
                placeholder="Ask about an obligation, a practice, or a system type"
                className="type-body max-h-40 min-h-[2.75rem] resize-none border-0 bg-transparent py-2.5 shadow-none focus-visible:ring-0 dark:bg-transparent"
              />
              <Button
                type="submit"
                size="icon"
                disabled={pending || loading || !question.trim() || tooLong}
                aria-label="Send question"
                className="size-10 shrink-0 rounded-xl"
              >
                <ArrowUpIcon className="size-4" aria-hidden />
              </Button>
            </div>
          </form>
          <div className="mt-2.5 flex items-center justify-between gap-4">
            <LegalNotice variant="inline" />
            <span
              className={`type-micro shrink-0 font-mono ${tooLong ? "text-destructive" : "text-muted-foreground/60"}`}
              aria-live={tooLong ? "polite" : "off"}
            >
              {question.length}/{MAX_CHARS}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
