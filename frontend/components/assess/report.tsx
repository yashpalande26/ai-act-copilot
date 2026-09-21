"use client";

import { ChevronDownIcon } from "lucide-react";

import { Commentary, Provision } from "@/components/assess/provision";
import { LegalNotice } from "@/components/legal-notice";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { AssessmentReport as Report, Headline, ObligationGroup, PenaltyLine } from "@/lib/types";

const TONE: Record<Headline, string> = {
  OUT_OF_SCOPE: "border-hairline bg-muted/30",
  PROHIBITED_FLAG: "border-destructive/40 bg-destructive/[0.06]",
  HIGH_RISK: "border-caution/40 bg-caution/[0.07]",
  HIGH_RISK_POSSIBLE: "border-caution/40 border-dashed bg-caution/[0.05]",
  TRANSPARENCY: "border-grounded/40 bg-grounded/[0.06]",
  MINIMAL: "border-hairline bg-card",
};

const HEADLINE_LABEL: Record<Headline, string> = {
  OUT_OF_SCOPE: "Outside the Regulation's scope",
  PROHIBITED_FLAG: "Prohibited-practice red flag",
  HIGH_RISK: "High-risk (Article 6(2))",
  HIGH_RISK_POSSIBLE: "Possibly high-risk (Article 6(1))",
  TRANSPARENCY: "Transparency obligations apply",
  MINIMAL: "No high-risk or transparency category matched",
};

const ROLE_LABEL: Record<string, string> = {
  provider: "Provider",
  deployer: "Deployer",
  importer: "Importer",
  distributor: "Distributor",
  authorised_representative: "Authorised representative",
  all: "All operators",
  voluntary: "Voluntary",
};

const eur = new Intl.NumberFormat("en-IE", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

function Section({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      {eyebrow ? <p className="type-eyebrow text-ink-faint">{eyebrow}</p> : null}
      <h2 className="type-h3">{title}</h2>
      {children}
    </section>
  );
}

function Group({ g }: { g: ObligationGroup }) {
  return (
    <Collapsible className="border-hairline bg-card rounded-2xl border">
      <CollapsibleTrigger className="group hover:bg-grounded/[0.04] focus-visible:ring-ring flex w-full items-start gap-3 rounded-2xl px-4 py-3.5 text-left focus-visible:ring-2 focus-visible:outline-none data-[state=open]:rounded-b-none sm:px-5">
        <span className="min-w-0 flex-1">
          <span className="type-body text-ink block font-medium">{g.title}</span>
          <span className="type-micro text-ink-soft mt-1 flex flex-wrap gap-x-3 gap-y-1">
            <span className="bg-muted rounded-full px-2 py-0.5">{ROLE_LABEL[g.role] ?? g.role}</span>
            <span className="font-mono">{g.provisions.map((p) => p.citation_label).join(" · ")}</span>
          </span>
        </span>
        <ChevronDownIcon
          className="text-ink-faint mt-1 size-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180"
          aria-hidden
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="disclosure-content overflow-hidden">
        <div className="border-hairline space-y-5 border-t px-4 py-4 sm:px-5">
          {g.commentary ? <Commentary>{g.commentary}</Commentary> : null}
          {g.provisions.map((p) => (
            <Provision key={p.citation_id} p={p} />
          ))}
          {g.applies_from ? (
            <div className="border-hairline border-t pt-4">
              <p className="type-eyebrow text-ink-faint mb-2">Applies from</p>
              <Provision p={g.applies_from} compact />
            </div>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

type TurnoverStatus = Report["penalties"]["turnover_status"];

// Shown in place of a personalised ceiling when it could not be computed.
// Never a computed "EUR 0": the backend leaves ceiling_eur null for 0 turnover.
const CEILING_PROMPT: Record<TurnoverStatus, string> = {
  provided: "enter annual turnover to compute",
  not_needed: "enter annual turnover to compute",
  missing: "enter annual turnover to compute",
  zero: "turnover entered as 0; enter a positive annual turnover to compute",
};

function PenaltyRow({ line, turnoverStatus }: { line: PenaltyLine; turnoverStatus: TurnoverStatus }) {
  const rule =
    line.rule === "eur_only"
      ? "fixed amount (not an undertaking)"
      : line.rule === "lower"
        ? "whichever is lower"
        : "whichever is higher";
  return (
    <li className={`border-hairline rounded-2xl border p-4 sm:p-5 ${line.applicable ? "bg-card" : "bg-muted/30"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="type-mono text-ink font-medium">{line.paragraph.citation_label}</span>
        <span className="type-micro text-ink-soft">
          {line.applicable ? "relevant to your answers" : "shown for completeness"}
        </span>
      </div>
      <dl className="type-meta mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        <div>
          <dt className="type-micro text-ink-faint">Fixed cap</dt>
          <dd className="font-mono">{eur.format(line.eur_cap)}</dd>
        </div>
        <div>
          <dt className="type-micro text-ink-faint">Turnover cap</dt>
          <dd className="font-mono">{line.pct_cap} %</dd>
        </div>
        <div>
          <dt className="type-micro text-ink-faint">Rule</dt>
          <dd>{rule}</dd>
        </div>
        <div>
          <dt className="type-micro text-ink-faint">Maximum ceiling for you</dt>
          <dd className="font-mono font-medium">
            {line.ceiling_eur === null ? CEILING_PROMPT[turnoverStatus] : eur.format(line.ceiling_eur)}
          </dd>
        </div>
      </dl>
      <Commentary>{line.why}</Commentary>
      <div className="mt-4 space-y-3">
        <Provision p={line.paragraph} compact />
        {line.rule_basis.map((p) => (
          <Provision key={p.citation_id} p={p} compact />
        ))}
      </div>
    </li>
  );
}

export function AssessmentReport({ report }: { report: Report }) {
  const d = report.decision;
  return (
    <article className="space-y-10">
      <header className={`rounded-2xl border p-5 sm:p-7 ${TONE[d.headline]}`}>
        <p className="type-eyebrow text-ink-faint">{HEADLINE_LABEL[d.headline]}</p>
        <h1 className="type-h2 mt-2 text-balance">{report.headline_text}</h1>
        <dl className="type-micro text-ink-soft mt-5 flex flex-wrap gap-x-6 gap-y-1">
          <div>
            <dt className="inline">Roles: </dt>
            <dd className="inline font-medium">
              {d.roles.length ? d.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ") : "none selected"}
            </dd>
          </div>
          <div>
            <dt className="inline">Generated: </dt>
            <dd className="inline font-mono">{new Date(report.generated_at).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="inline">Consolidated text of: </dt>
            <dd className="inline font-mono">{report.corpus_consolidated_date}</dd>
          </div>
        </dl>
      </header>

      {report.scope.length ? (
        <Section title="Scope" eyebrow="Why the Regulation may not apply">
          {report.scope.map((p) => (
            <Provision key={p.citation_id} p={p} />
          ))}
        </Section>
      ) : null}

      {report.prohibited_flags.length ? (
        <Section title="Prohibited-practice patterns you matched" eyebrow="Article 5(1)">
          <Commentary>
            Each point below carries conditions and exceptions. A match here is a red flag to
            take to counsel, not a determination that the practice is prohibited.
          </Commentary>
          {report.prohibited_flags.map((f) => (
            <Provision key={f.key} p={f.provision} />
          ))}
        </Section>
      ) : null}

      {report.high_risk_basis ? (
        <Section title="Why it appears high-risk" eyebrow="Article 6(2) and Annex III">
          <Provision p={report.high_risk_basis} />
          {report.derogation.length ? (
            <div className="border-hairline bg-card mt-4 rounded-2xl border p-4 sm:p-5">
              <p className="type-eyebrow text-ink-faint mb-3">The Article 6(3) derogation</p>
              <Commentary>
                {d.derogation_claimed
                  ? "You indicated you intend to rely on this derogation. This tool has not applied it: the assessment stays high-risk unless the derogation is documented as Article 6(4) requires."
                  : "This tool never applies the derogation itself. It is quoted so you can assess whether its conditions could apply."}
              </Commentary>
              <div className="mt-3 space-y-4">
                {report.derogation.map((p) => (
                  <Provision key={p.citation_id} p={p} compact />
                ))}
              </div>
            </div>
          ) : null}
        </Section>
      ) : null}

      {report.product_route.length ? (
        <Section title="Product-safety route" eyebrow="Article 6(1)">
          {report.product_route.map((p) => (
            <Provision key={p.citation_id} p={p} />
          ))}
        </Section>
      ) : null}

      {report.role_definitions.length ? (
        <Section title="Your role, as the Regulation defines it" eyebrow="Article 3">
          {report.role_definitions.map((p) => (
            <Provision key={p.citation_id} p={p} compact />
          ))}
          {report.treated_as_provider.map((p) => (
            <Provision key={p.citation_id} p={p} compact />
          ))}
        </Section>
      ) : null}

      {report.obligations.length ? (
        <Section title="Obligations and their basis" eyebrow="Verbatim, by article">
          <div className="space-y-3">
            {report.obligations.map((g) => (
              <Group key={g.key} g={g} />
            ))}
          </div>
        </Section>
      ) : null}

      {report.dates.length ? (
        <Section title="When these apply" eyebrow="Article 113 and transitional provisions">
          {report.dates.map((p) => (
            <Provision key={p.citation_id} p={p} compact />
          ))}
        </Section>
      ) : null}

      <Section title="Maximum administrative fine ceilings" eyebrow="Article 99">
        <Commentary>{report.penalties.commentary}</Commentary>
        <ul className="space-y-3">
          {report.penalties.lines.map((line) => (
            <PenaltyRow
              key={line.paragraph.citation_id}
              line={line}
              turnoverStatus={report.penalties.turnover_status}
            />
          ))}
        </ul>
        <div className="border-hairline bg-card rounded-2xl border p-4 sm:p-5">
          <p className="type-eyebrow text-ink-faint mb-3">What authorities weigh</p>
          <Provision p={report.penalties.factors} compact />
        </div>
      </Section>

      <Section title="Notes" eyebrow="Commentary">
        <ul className="space-y-2">
          {report.commentary.map((c, i) => (
            <li key={i} className="type-meta text-ink-soft">
              {c}
            </li>
          ))}
        </ul>
        <div className="pt-2">
          <LegalNotice />
        </div>
      </Section>
    </article>
  );
}
