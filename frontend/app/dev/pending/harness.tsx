"use client";

import { useState } from "react";

import { AppShell } from "@/components/app/app-shell";
import { ChatPanel } from "@/components/chat/chat-panel";
import type { ChatTurn } from "@/lib/types";

const QUESTION = "Who counts as a deployer under the Act, and what human oversight must deployers of high-risk AI systems assign?";

const ANSWER: ChatTurn = {
  role: "assistant",
  id: "a1",
  result: {
    answer:
      "A deployer is a natural or legal person, public authority, agency or other body using an AI system under its authority, except where the AI system is used in the course of a personal non-professional activity (Article 3, point (4)). Deployers of high-risk AI systems must assign human oversight to natural persons who have the necessary competence, training and authority, as well as the necessary support (Article 26, paragraph 2).",
    citations: [
      { citation_id: "art_3.pt_4", citation_label: "Article 3, point (4)", quoted_text: "‘deployer’ means a natural or legal person, public authority, agency or other body using an AI system under its authority except where the AI system is used in the course of a personal non-professional activity;" },
      { citation_id: "art_26.par_2", citation_label: "Article 26, paragraph 2", quoted_text: "Deployers shall assign human oversight to natural persons who have the necessary competence, training and authority, as well as the necessary support." },
    ],
    abstained: false,
    session_id: "00000000-0000-4000-8000-000000000000",
  },
};

const OFFSET_MS = { bar: 0, early: 1500, late: 9000 } as const;

export function PendingHarness({ phase }: { phase: "bar" | "early" | "late" }) {
  const [resolved, setResolved] = useState(false);
  const [startedAt] = useState(() => Date.now() - OFFSET_MS[phase]);
  const turns: ChatTurn[] = [{ role: "user", id: "u1", question: QUESTION }, ...(resolved ? [ANSWER] : [])];
  return (
    <AppShell isAdmin={false} account={null} accountCompact={null} rail={null} title="Ask the copilot" scroll="none">
      <p className="type-micro text-ink-faint px-6 pt-4 uppercase tracking-wide">Prototype harness, not a product page</p>
      <div className="px-6 pb-2">
        <button
          type="button"
          className="type-micro text-ink-soft underline"
          onClick={() => setResolved(true)}
          data-testid="resolve"
        >
          Resolve the turn
        </button>
      </div>
      <ChatPanel
        userName="Yash"
        turns={turns}
        pending={!resolved}
        pendingStartedAt={startedAt}
        onSubmit={() => {}}
      />
    </AppShell>
  );
}
