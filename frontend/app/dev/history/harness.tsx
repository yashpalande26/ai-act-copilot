"use client";

import { useState } from "react";

import { HistoryDrawer, HistorySidebar } from "@/components/chat/history-sidebar";
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

export function HistoryHarness() {
  const [sessions] = useState(fixture);
  const [current, setCurrent] = useState<string | undefined>("a2");
  const props = {
    sessions,
    loading: false,
    currentId: current,
    onSelect: setCurrent,
    onNew: () => setCurrent(undefined),
    showAssessments: false, // no session in the harness; the block would 401
  };

  return (
    <div className="flex h-dvh flex-col">
      <p className="type-eyebrow text-ink-faint border-hairline border-b px-6 py-3">
        Preview harness, not a product page
      </p>
      <div className="flex min-h-0 flex-1">
        <HistorySidebar {...props} className="hidden md:flex md:flex-col" />
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="border-hairline flex h-11 items-center border-b px-3 md:hidden">
            <HistoryDrawer {...props} />
          </div>
          <div className="mx-auto w-full max-w-3xl px-6 py-10">
            <p className="type-body text-ink-soft">
              Conversation column. Current session: {current ?? "none (new chat)"}.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
