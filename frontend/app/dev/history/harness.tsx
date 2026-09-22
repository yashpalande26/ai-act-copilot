"use client";

import { useState } from "react";

import { AppShell } from "@/components/app/app-shell";
import { ChatPanel } from "@/components/chat/chat-panel";
import { HistoryList } from "@/components/chat/history-sidebar";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import type { SessionSummary } from "@/lib/types";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** Fixture sessions: the starter questions plus a long title, at spread dates. */
function fixture(now = Date.now()): SessionSummary[] {
  return [
    ["a1", "What obligations apply to providers of high-risk AI systems?", now - 2 * HOUR, 6],
    ["a2", "Is an AI system used for credit scoring high-risk?", now - 5 * HOUR, 2],
    ["a3", "Which AI practices are prohibited outright?", now - DAY - HOUR, 4],
    [
      "a4",
      "What transparency obligations apply to deployers of emotion recognition systems used at the workplace, and do they differ for public…",
      now - 3 * DAY,
      8,
    ],
    ["a5", "What must a deployer do before using a high-risk AI system?", now - 12 * DAY, 2],
  ].map(([id, title, at, n]) => ({
    id: id as string,
    title: title as string,
    created_at: new Date(at as number).toISOString(),
    message_count: n as number,
  }));
}

/** Stand-in for the server-rendered account control (no session here). */
function FakeAccount({ compact = false }: { compact?: boolean }) {
  const avatar = (
    <Avatar className="size-8">
      <AvatarFallback className="text-xs">OP</AvatarFallback>
    </Avatar>
  );
  if (compact) return avatar;
  return (
    <div className="flex items-center gap-3 px-2.5 py-2">
      {avatar}
      <span className="min-w-0">
        <span className="type-meta text-ink block truncate font-medium">Operator</span>
        <span className="type-micro text-ink-faint block truncate">operator@example.com</span>
      </span>
    </div>
  );
}

export function HistoryHarness() {
  const [sessions, setSessions] = useState(fixture);
  const [current, setCurrent] = useState<string | undefined>("a2");
  const rail = (
    <HistoryList
      sessions={sessions}
      loading={false}
      currentId={current}
      onSelect={setCurrent}
      onNew={() => setCurrent(undefined)}
      onDelete={async (id) => {
        // No backend in the harness: the row disappears as it would after a 204.
        setSessions((rows) => rows.filter((r) => r.id !== id));
        if (id === current) setCurrent(undefined);
        return true;
      }}
      showAssessments={false} // no session in the harness; the block would 401
    />
  );
  return (
    <AppShell
      account={<FakeAccount />}
      accountCompact={<FakeAccount compact />}
      rail={rail}
      title="Ask the copilot"
      isAdmin
      scroll="none"
    >
      {/* The real empty conversation column: starters and composer, no backend. */}
      <ChatPanel userName="Operator" turns={[]} pending={false} onSubmit={() => undefined} />
    </AppShell>
  );
}
