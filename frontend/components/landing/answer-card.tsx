import { ArrowUpRightIcon, QuoteIcon, ScaleIcon } from "lucide-react";

/**
 * The signature element: a realistic rendering of a real answer.
 *
 * This is the product, shown rather than described. Everything in it reflects
 * what the system genuinely returns: the question, the grounded prose, and
 * citations that carry both a human label and the machine citation id, each
 * linking to the provision on EUR-Lex. No invented metrics, no fake UI chrome.
 */

type Citation = {
  label: string;
  id: string;
  href: string;
  quote: string;
};

const CITATIONS: Citation[] = [
  {
    label: "Article 16, point (a)",
    id: "art_16.pt_a",
    href: "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727#art_16",
    quote:
      "ensure that their high-risk AI systems are compliant with the requirements set out in Section 2;",
  },
  {
    label: "Article 17, paragraph 1",
    id: "art_17.par_1",
    href: "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727#art_17",
    quote:
      "Providers of high-risk AI systems shall put a quality management system in place that ensures compliance with this Regulation.",
  },
];

export function AnswerCard() {
  return (
    <figure className="border-hairline bg-surface [box-shadow:var(--shadow-xl)] overflow-hidden rounded-2xl border">
      {/* Question */}
      <div className="border-hairline bg-surface-sunken/60 border-b px-5 py-4 sm:px-7 sm:py-5">
        <p className="type-eyebrow text-ink-faint">Question</p>
        <p className="type-body text-ink mt-2 font-medium">
          What obligations apply to providers of high-risk AI systems?
        </p>
      </div>

      {/* Answer */}
      <div className="px-5 py-6 sm:px-7 sm:py-7">
        <div className="flex gap-3.5">
          <span className="bg-brand-solid text-brand-on mt-0.5 hidden size-7 shrink-0 items-center justify-center rounded-lg sm:flex">
            <ScaleIcon className="size-3.5" aria-hidden />
          </span>
          <p className="type-body text-ink-soft min-w-0">
            Providers must ensure their high-risk AI systems comply with the
            requirements of Section 2, put a quality management system in place,
            and draw up technical documentation before the system is placed on
            the market.
          </p>
        </div>

        {/* Citations */}
        <div className="mt-6 sm:pl-[2.625rem]">
          <p className="type-eyebrow text-ink-faint">
            Cited provisions
          </p>
          <ul className="mt-3 space-y-2.5">
            {CITATIONS.map((c) => (
              <li key={c.id}>
                <a
                  href={c.href}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="border-hairline bg-paper hover:border-grounded/45 focus-visible:ring-ring group block rounded-xl border p-3.5 transition-colors focus-visible:ring-2 focus-visible:outline-none sm:p-4"
                >
                  <span className="flex items-center gap-2">
                    <QuoteIcon
                      className="text-grounded size-3.5 shrink-0"
                      aria-hidden
                    />
                    <span className="type-mono text-ink font-medium">
                      {c.label}
                    </span>
                    <ArrowUpRightIcon
                      className="text-ink-faint group-hover:text-grounded ml-auto size-3.5 shrink-0 transition-colors"
                      aria-hidden
                    />
                  </span>
                  <span className="border-grounded/30 text-ink-soft type-meta mt-2.5 block border-l-2 pl-3.5">
                    {c.quote}
                  </span>
                  <span className="type-micro text-ink-faint mt-2 block font-mono">
                    {c.id} · EUR-Lex
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </figure>
  );
}
