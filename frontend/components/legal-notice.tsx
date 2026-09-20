import { InfoIcon } from "lucide-react";

/**
 * The honesty framing, shown wherever answers appear.
 *
 * Deliberately not dismissible: for a compliance tool the disclaimer is part
 * of the product, not an interruption to be cleared. The variants differ only
 * in density, never in substance.
 */
export function LegalNotice({
  variant = "full",
}: {
  variant?: "full" | "inline";
}) {
  if (variant === "inline") {
    return (
      <p className="type-micro text-ink-faint">
        Informational, not legal advice. Only the Official Journal text is
        legally authentic.
      </p>
    );
  }

  return (
    <div className="border-hairline bg-surface-sunken/50 flex gap-3.5 rounded-xl border p-5">
      <InfoIcon className="text-ink-faint mt-0.5 size-[18px] shrink-0" aria-hidden />
      <p className="type-meta text-ink-soft">
        <span className="text-ink font-medium">
          Informational, not legal advice.
        </span>{" "}
        Answers are generated from the consolidated EU AI Act text and are for
        orientation only. Only the version published in the Official Journal is
        legally authentic. Have anything you intend to act on reviewed by a
        qualified professional.
      </p>
    </div>
  );
}
