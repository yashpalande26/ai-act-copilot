"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { ClipboardCheckIcon, HistoryIcon, PlusIcon, XIcon } from "lucide-react";

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
 * The list itself, presentational. Used inside the desktop rail and the
 * mobile drawer, so both render the same rows and the same states.
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
      <div className="space-y-2 px-3 pt-3 pb-2">
        <Button
          type="button"
          variant="outline"
          onClick={onNew}
          className="border-hairline bg-card hover:bg-grounded/[0.05] w-full justify-start gap-2 rounded-xl"
        >
          <PlusIcon className="size-4" aria-hidden />
          New chat
        </Button>
        <Button
          asChild
          variant="ghost"
          className="text-ink-soft hover:text-ink w-full justify-start gap-2 rounded-xl"
        >
          <Link href="/app/assess">
            <ClipboardCheckIcon className="size-4" aria-hidden />
            Start an assessment
          </Link>
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
      <p className="type-eyebrow text-ink-faint px-5 pt-3 pb-1.5">Past chats</p>

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
          <p className="type-micro text-ink-soft px-3 py-3">
            Your past chats will appear here.
          </p>
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
                    className={`focus-visible:ring-ring relative w-full rounded-lg px-3 py-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none ${
                      current
                        ? "bg-muted text-ink before:bg-grounded before:absolute before:top-2.5 before:bottom-2.5 before:left-0 before:w-0.5 before:rounded-full"
                        : "text-ink-soft hover:bg-muted/60 hover:text-ink"
                    }`}
                  >
                    <span className="type-meta line-clamp-2 leading-snug">{s.title}</span>
                    <span className="type-micro text-ink-faint mt-1 block">
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

/** Desktop rail: always visible from md up. */
export function HistorySidebar(props: HistoryProps & { className?: string }) {
  const { className = "", ...rest } = props;
  return (
    <aside
      aria-label="Chat history"
      className={`border-hairline bg-paper w-72 shrink-0 border-r ${className}`}
    >
      <HistoryList {...rest} />
    </aside>
  );
}

/**
 * Mobile: a "History" button that opens the same list as a left drawer.
 * Real dialog semantics, Escape and backdrop close it, focus goes to the
 * close button on open and back to the trigger on close.
 */
export function HistoryDrawer(props: HistoryProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current; // captured now; the ref may move by cleanup
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      trigger?.focus();
    };
  }, [open]);

  const close = () => setOpen(false);

  return (
    <>
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        aria-expanded={open}
        aria-controls={panelId}
        className="type-meta text-ink-soft gap-2"
      >
        <HistoryIcon className="size-4" aria-hidden />
        History
      </Button>

      {open ? (
        <div className="fixed inset-0 z-50">
          <button
            type="button"
            aria-label="Close chat history"
            onClick={close}
            className="bg-ink/40 absolute inset-0 backdrop-blur-[2px]"
          />
          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-label="Chat history"
            className="border-hairline bg-paper [box-shadow:var(--shadow-xl)] absolute inset-y-0 left-0 flex w-80 max-w-[85vw] flex-col border-r"
          >
            <div className="border-hairline flex h-14 items-center justify-between border-b px-4">
              <span className="type-meta text-ink font-medium">Chat history</span>
              <Button
                ref={closeRef}
                type="button"
                variant="ghost"
                size="icon"
                onClick={close}
                aria-label="Close chat history"
                className="rounded-full"
              >
                <XIcon className="size-4" aria-hidden />
              </Button>
            </div>
            <div className="min-h-0 flex-1">
              <HistoryList
                {...props}
                onSelect={(id) => {
                  props.onSelect(id);
                  close();
                }}
                onNew={() => {
                  props.onNew();
                  close();
                }}
              />
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
