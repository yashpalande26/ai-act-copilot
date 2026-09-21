"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUpIcon } from "lucide-react";

import { AssistantTurn, PendingTurn, UserTurn } from "@/components/chat/answer-turn";
import { LegalNotice } from "@/components/legal-notice";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { ChatTurn } from "@/lib/types";

const MAX_CHARS = 2000;

const STARTERS = [
  "What obligations apply to providers of high-risk AI systems?",
  "Is an AI system used for credit scoring high-risk?",
  "Which AI practices are prohibited outright?",
  "What must a deployer do before using a high-risk AI system?",
];

type Props = {
  userName: string;
  turns: ChatTurn[];
  pending: boolean;
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
  loading = false,
  loadError = null,
  onSubmit,
}: Props) {
  const [question, setQuestion] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
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
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-6 py-10">
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
            <div className="py-8 sm:py-14">
              <h1 className="type-h2 text-balance">
                What can I help you check, {userName}?
              </h1>
              <p className="type-lead text-muted-foreground mt-5 max-w-[42rem]">
                Ask about obligations, prohibited practices, or whether a system
                is high-risk. Every answer cites the provisions it came from.
              </p>
              {loadError ? (
                <p className="type-meta text-ink-soft mt-6" role="status">
                  {loadError}
                </p>
              ) : null}
              <div className="mt-10 grid gap-3 sm:grid-cols-2">
                {STARTERS.map((starter) => (
                  <button
                    key={starter}
                    type="button"
                    onClick={() => submit(starter)}
                    className="border-border/70 bg-card hover:border-primary/40 hover:bg-accent focus-visible:ring-ring type-meta rounded-xl border px-4.5 py-3.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
                  >
                    {starter}
                  </button>
                ))}
              </div>
              <div className="mt-12">
                <LegalNotice />
              </div>
            </div>
          ) : (
            <div className="space-y-8">
              {turns.map((turn) =>
                turn.role === "user" ? (
                  <UserTurn key={turn.id} question={turn.question} />
                ) : (
                  <AssistantTurn key={turn.id} turn={turn} />
                ),
              )}
              {pending ? <PendingTurn /> : null}
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-border/60 bg-background/90 border-t backdrop-blur-md">
        <div className="mx-auto w-full max-w-3xl px-6 py-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(question);
            }}
          >
            <div className="border-border/70 bg-card focus-within:border-primary/50 focus-within:ring-ring/25 flex items-end gap-2 rounded-2xl border p-2.5 transition-shadow focus-within:ring-2">
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
