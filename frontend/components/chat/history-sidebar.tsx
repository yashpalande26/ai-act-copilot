"use client";

import { MessageSquareDashedIcon, PlusIcon } from "lucide-react";

import { AssessmentsRail } from "@/components/chat/assessments-rail";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { SessionSummary } from "@/lib/types";

export type HistoryProps = {
  sessions: SessionSummary[];
  loading: boolean;
  error?: boolean;
  currentId?: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  /** Render the "Your assessments" block (off in the dev harness, which has no session). */
  showAssessments?: boolean;
};

/** "Today", "Yesterday", "3 days ago", else a short date. */
export function formatWhen(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const days = Math.round(
    (Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) -
      Date.UTC(then.getFullYear(), then.getMonth(), then.getDate())) /
      86_400_000,
  );
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function turnsLabel(messageCount: number): string {
  const turns = Math.max(1, Math.round(messageCount / 2));
  return turns === 1 ? "1 turn" : `${turns} turns`;
}

/**
 * The chat rail, presentational. The app shell places it under the primary
 * navigation on desktop and inside the drawer on small screens, so both
 * render the same rows and the same states.
 */
export function HistoryList({
  sessions,
  loading,
  error = false,
  currentId,
  onSelect,
  onNew,
  showAssessments = true,
}: HistoryProps) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1">
      <div className="flex items-center justify-between px-5 pt-4 pb-1.5">
        <p className="type-eyebrow text-ink-faint">Past chats</p>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={onNew}
          className="text-ink-soft hover:text-ink -mr-1.5 gap-1"
        >
          <PlusIcon className="size-3.5" aria-hidden />
          New
        </Button>
      </div>

      <nav aria-label="Past chats" className="px-2 pb-2">
        {loading ? (
          <ul className="space-y-1.5 px-1 pt-1" aria-hidden>
            {[0, 1, 2, 3].map((i) => (
              <li key={i} className="rounded-lg px-3 py-2.5">
                <Skeleton className="h-3.5 w-[85%]" />
                <Skeleton className="mt-2 h-3 w-[40%]" />
              </li>
            ))}
          </ul>
        ) : error ? (
          <p className="type-micro text-ink-soft px-3 py-3">
            Your past chats could not be loaded right now.
          </p>
        ) : sessions.length === 0 ? (
          <div className="border-hairline mx-1 my-2 rounded-xl border border-dashed px-3 py-4 text-center">
            <MessageSquareDashedIcon className="text-ink-faint mx-auto size-4" aria-hidden />
            <p className="type-micro text-ink-soft mt-2">No chats yet</p>
            <p className="text-ink-faint mt-0.5 text-[0.75rem] leading-snug">
              Your questions will be kept here.
            </p>
          </div>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((s) => {
              const current = s.id === currentId;
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(s.id)}
                    aria-current={current ? "page" : undefined}
                    className={`focus-visible:ring-ring relative w-full rounded-lg px-3 py-2 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none ${
                      current
                        ? "bg-sidebar-accent text-ink ring-hairline shadow-[var(--shadow-xs)] ring-1"
                        : "text-ink-soft hover:bg-sidebar-accent/70 hover:text-ink"
                    }`}
                  >
                    <span className="type-micro line-clamp-2 leading-snug">{s.title}</span>
                    <span className="text-ink-faint mt-0.5 block text-[0.75rem] leading-snug">
                      {formatWhen(s.created_at)} <span aria-hidden>&middot;</span>{" "}
                      {turnsLabel(s.message_count)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      {showAssessments ? <AssessmentsRail /> : null}
      </div>
    </div>
  );
}
