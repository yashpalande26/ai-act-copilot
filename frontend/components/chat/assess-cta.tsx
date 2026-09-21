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
 * The funnel from a chat turn to the assessment. Deterministic and free: it is
 * present after every answer and inside every refusal, so no classifier
 * decides who sees it. The chat's own behaviour is untouched; this is a link
 * to a different, deterministic path that starts from the same text.
 */
export function AssessCta({
  text,
  variant,
}: {
  /** The user's most recent message, pre-filled into the describe box. */
  text?: string;
  variant: "answer" | "refusal";
}) {
  const href = assessHref(text);
  if (variant === "refusal") {
    return (
      <p className="type-meta text-ink-soft mt-4" data-testid="assess-cta-refusal">
        If you were describing your own system, the full assessment is the better route: it works
        from your description and a short questionnaire, not from a search of the text.{" "}
        <Link href={href} className="text-grounded inline-flex items-center gap-1 font-medium hover:underline">
          Assess this system
          <ArrowRightIcon className="size-3.5" aria-hidden />
        </Link>
      </p>
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
