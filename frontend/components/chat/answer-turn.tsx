import {
  AlertTriangleIcon,
  CircleSlashIcon,
  ClockIcon,
  ScaleIcon,
  WifiOffIcon,
} from "lucide-react";

import { CitationCard } from "@/components/chat/citation-card";
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
 * The abstention state, deliberately distinct from a normal answer.
 *
 * For a compliance tool "I do not know" is a feature, so it gets its own
 * treatment (caution colour, its own icon, an explanation of why) rather than
 * rendering as prose a user might skim past.
 */
function AbstentionTurn() {
  return (
    <Bubble>
      <div className="border-caution/35 bg-caution/[0.07] rounded-2xl border p-5 sm:p-6">
        <div className="flex items-center gap-2.5">
          <CircleSlashIcon className="text-caution size-[18px]" aria-hidden />
          <h3 className="type-h3">The copilot declined to answer</h3>
        </div>
        <p className="type-body text-ink-soft mt-3">
          The retrieved provisions did not contain enough to answer that
          question, so it stopped rather than guessing. Try rephrasing, or ask
          about a specific obligation, actor, or system type.
        </p>
        <p className="type-meta text-ink-soft mt-4">
          This is intended behaviour. An unanswered question is safer than a
          confident wrong one.
        </p>
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

export function AssistantTurn({ turn }: { turn: ChatTurn }) {
  if (turn.role === "error") return <ErrorTurn {...turn} />;
  if (turn.role !== "assistant") return null;
  if (turn.result.abstained) return <AbstentionTurn />;

  return (
    <Bubble>
      <div className="type-body whitespace-pre-wrap">{turn.result.answer}</div>

      {turn.result.citations.length > 0 ? (
        <section aria-label="Cited provisions" className="space-y-2.5">
          <h3 className="type-micro text-ink-soft font-medium tracking-[0.07em] uppercase">
            Cited provisions ({turn.result.citations.length})
          </h3>
          <div className="space-y-2">
            {turn.result.citations.map((citation) => (
              <CitationCard key={citation.citation_id} citation={citation} />
            ))}
          </div>
        </section>
      ) : null}
    </Bubble>
  );
}

export function PendingTurn() {
  return (
    <Bubble>
      <div
        className="type-body text-ink-soft flex items-center gap-3"
        role="status"
        aria-live="polite"
      >
        <span className="flex gap-1.5" aria-hidden>
          {[0, 150, 300].map((delay) => (
            <span
              key={delay}
              className="bg-muted-foreground/45 size-1.5 animate-bounce rounded-full"
              style={{ animationDelay: `${delay}ms` }}
            />
          ))}
        </span>
        Searching the Act and drafting a cited answer
      </div>
    </Bubble>
  );
}
