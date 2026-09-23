import Link from "next/link";
import { ArrowRightIcon } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";

const MAX_DESCRIPTION_CHARS = 4000; // mirrors backend config.MAX_DESCRIPTION_CHARS

/** Link into the assessment with the user's own words carried along. A link,
 *  not an action: nothing is called and nothing is stored by following it. */
export function assessHref(text?: string): string {
  const t = (text ?? "").trim().slice(0, MAX_DESCRIPTION_CHARS);
  return t ? `/app/assess?describe=${encodeURIComponent(t)}` : "/app/assess";
}

/**
 * The funnel from a chat turn to the assessment, rendered as the answer
 * card's footer. Deterministic and free: no classifier decides who sees it,
 * the turn's own shape does. It appears only under a grounded answer
 * ("answer") or a plain-language system explanation ("system"); never under a
 * refusal, a scope notice, a greeting, a chat-lane reply or a clarifying
 * question (23 Sep 2026). The chat's own behaviour is untouched; this is a
 * link to a different, deterministic path that starts from the same text.
 * The "system" variant is the primary action of its turn (ADR-21: the
 * classification of the described system is the assessment's), the "answer"
 * variant a quiet outline link.
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
    return (
      <div
        className="border-hairline bg-surface-sunken/60 flex flex-wrap items-center justify-between gap-x-5 gap-y-3 border-t px-5 py-4 sm:px-6"
        data-testid="assess-cta-system"
      >
        <p className="type-meta text-ink-soft min-w-[14rem] flex-1 text-pretty">
          The classification of your system is made by the assessment, from your description and a short
          questionnaire, with the provisions quoted.
        </p>
        <Link href={href} className={buttonVariants({ size: "lg", className: "shrink-0" })}>
          Assess this system
          <ArrowRightIcon className="size-4" aria-hidden />
        </Link>
      </div>
    );
  }
  return (
    <div
      className="border-hairline bg-surface-sunken/60 flex flex-wrap items-center justify-between gap-x-5 gap-y-2 border-t px-5 py-3 sm:px-6"
      data-testid="assess-cta-answer"
    >
      <p className="type-micro text-ink-soft min-w-[14rem] flex-1 text-pretty">
        Need this for one system? The assessment gives the full record: quoted obligations, dates and fine
        ceilings.
      </p>
      <Link href={href} className={buttonVariants({ variant: "outline", size: "sm", className: "shrink-0" })}>
        Assess
        <ArrowRightIcon className="size-3.5" aria-hidden />
      </Link>
    </div>
  );
}
