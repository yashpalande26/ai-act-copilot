import Link from "next/link";
import { ArrowRightIcon } from "lucide-react";

const MAX_DESCRIPTION_CHARS = 4000; // mirrors backend config.MAX_DESCRIPTION_CHARS

/** Link into the assessment with the user's own words carried along. A link,
 *  not an action: nothing is called and nothing is stored by following it. */
export function assessHref(text?: string): string {
  const t = (text ?? "").trim().slice(0, MAX_DESCRIPTION_CHARS);
  return t ? `/app/assess?describe=${encodeURIComponent(t)}` : "/app/assess";
}

/**
 * The funnel from a chat turn to the assessment. Deterministic and free: no
 * classifier decides who sees it, the turn's own shape does. It appears only
 * under a grounded answer ("answer") or a plain-language system explanation
 * ("system"); never under a refusal, a scope notice, a greeting, a chat-lane
 * reply or a clarifying question (23 Sep 2026: it used to sit under every
 * assistant message). The chat's own behaviour is untouched; this is a link
 * to a different, deterministic path that starts from the same text.
 */
export function AssessCta({
  text,
  variant,
}: {
  /** The user's most recent message, pre-filled into the describe box. */
  text?: string;
  variant: "answer" | "system";
}) {
  const href = assessHref(text);
  if (variant === "system") {
    // ADR-21: the user described their own system. The answer above explains
    // the type; the classification of this system is the assessment's.
    return (
      <div
        className="border-hairline flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t pt-4"
        data-testid="assess-cta-system"
      >
        <p className="type-meta text-ink-soft">
          The classification of your system is made by the assessment, from your description and a short
          questionnaire, with the provisions quoted.
        </p>
        <Link href={href} className="text-grounded inline-flex items-center gap-1 font-medium hover:underline">
          Assess this system
          <ArrowRightIcon className="size-3.5" aria-hidden />
        </Link>
      </div>
    );
  }
  return (
    <div
      className="border-hairline flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t pt-4"
      data-testid="assess-cta-answer"
    >
      <p className="type-micro text-ink-soft">
        Get the full obligations report for your system: quoted provisions, dates and fine ceilings.
      </p>
      <Link
        href={href}
        className="type-meta text-grounded inline-flex items-center gap-1 font-medium hover:underline"
      >
        Assess
        <ArrowRightIcon className="size-3.5" aria-hidden />
      </Link>
    </div>
  );
}
