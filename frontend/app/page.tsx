import Link from "next/link";
import {
  ArrowRightIcon,
  CircleSlashIcon,
  ClipboardListIcon,
  CodeIcon,
  MessageSquareTextIcon,
  QuoteIcon,
  RocketIcon,
  ScaleIcon,
  ShieldCheckIcon,
  SplitIcon,
  UsersIcon,
} from "lucide-react";

import { auth } from "@/auth";
import { AnswerCard } from "@/components/landing/answer-card";
import { AssessmentCard } from "@/components/landing/assessment-card";
import { LegalNotice } from "@/components/legal-notice";
import { Mark, SiteHeader, Wordmark } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import report from "@/lib/fixtures/assessment-report.json";

const CONSOLIDATED = (report as { corpus_consolidated_date: string }).corpus_consolidated_date;

/* Facts, not claims: each is true of the product as built. */
const FACTS = [
  { label: "Consolidated text of", value: CONSOLIDATED },
  { label: "Scope", value: "113 articles, 13 annexes" },
  { label: "Classification", value: "No language model in the path" },
  { label: "Citations", value: "Every one opens EUR-Lex" },
];

const STEPS = [
  {
    n: "01",
    icon: ClipboardListIcon,
    title: "Describe",
    body: "Seven short steps: scope, your role, a prohibited-practice screen, the high-risk categories, transparency, general-purpose models, exposure inputs. Each question shows the provision it rests on.",
  },
  {
    n: "02",
    icon: ScaleIcon,
    title: "Classify",
    body: "Plain, testable rules against Article 5, Article 6 and Annex III. No language model is involved, so the same answers always give the same result. Where the law calls for a judgment, the report says so instead of deciding.",
  },
  {
    n: "03",
    icon: QuoteIcon,
    title: "Read the obligations",
    body: "Every applicable provision is quoted word for word by citation, with the date it applies from and a link to EUR-Lex. Fine ceilings are computed from the text of Article 99 and your own turnover.",
  },
];

const PILLARS = [
  {
    icon: QuoteIcon,
    title: "Traceable to primary law",
    body: "Every citation opens the provision on EUR-Lex, word for word. The report quotes the Act; it does not paraphrase it.",
  },
  {
    icon: SplitIcon,
    title: "Deterministic where it matters",
    body: "Classification runs in ordinary, testable code with no language model in the path. In the copilot the model explains and cites, but it never decides a verdict.",
  },
  {
    icon: CircleSlashIcon,
    title: "It says what it cannot decide",
    body: "Where the Act requires a legal characterisation, the report records your answer and flags it rather than ruling on it. The copilot declines when the retrieved provisions do not answer the question.",
  },
];

const AUDIENCES = [
  {
    icon: RocketIcon,
    title: "Founders",
    body: "Find out whether what you are building appears to be high-risk before you build it, not during diligence.",
  },
  {
    icon: CodeIcon,
    title: "Developers",
    body: "Get the specific article behind an obligation, so it becomes a ticket.",
  },
  {
    icon: UsersIcon,
    title: "Compliance owners",
    body: "A dated, cited record of where a system appears to sit under the Act, ready for a memo.",
  },
];

export default async function LandingPage() {
  const session = await auth();
  const signedIn = Boolean(session?.user);
  const assessHref = signedIn ? "/app/assess" : "/signin?callbackUrl=%2Fapp%2Fassess";
  const chatHref = signedIn ? "/app" : "/signin";

  return (
    <>
      <SiteHeader>
        {signedIn ? (
          <>
            <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
              <Link href={chatHref}>Ask a question</Link>
            </Button>
            <Button asChild size="sm">
              <Link href={assessHref}>
                Assess your system <ArrowRightIcon className="size-4" aria-hidden />
              </Link>
            </Button>
          </>
        ) : (
          <>
            <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
              <Link href="/signin">Sign in</Link>
            </Button>
            <Button asChild size="sm">
              <Link href={assessHref}>Assess your system</Link>
            </Button>
          </>
        )}
      </SiteHeader>

      <main className="flex-1">
        {/* Hero */}
        <section className="border-hairline border-b">
          <div className="mx-auto max-w-6xl px-6 pt-16 pb-20 sm:pt-24 lg:grid lg:grid-cols-12 lg:items-center lg:gap-16 lg:pt-28 lg:pb-32">
            <div className="lg:col-span-6">
              <p className="type-eyebrow text-ink-faint flex items-center gap-2">
                <ShieldCheckIcon className="text-accent-solid size-4" aria-hidden />
                EU AI Act, consolidated text
              </p>
              <h1 className="type-display text-ink mt-6 text-balance">
                Find out where your AI system sits under the EU AI Act.
              </h1>
              <p className="type-lead text-ink-soft mt-7 max-w-[34rem] text-pretty">
                Answer a short questionnaire. The classification is deterministic, the
                obligations are quoted from the Act word for word with their citations, and
                the fine ceilings are computed from Article 99. Informational, not legal
                advice.
              </p>
              <div className="mt-9 flex flex-wrap items-center gap-3" data-hero-actions>
                <Button asChild size="lg" className="type-body h-12 px-7">
                  <Link href={assessHref} data-primary-cta>
                    Assess your AI system
                    <ArrowRightIcon className="size-4" aria-hidden />
                  </Link>
                </Button>
                <Button asChild variant="ghost" size="lg" className="type-body h-12 px-5">
                  <Link href={chatHref} data-secondary-cta>
                    <MessageSquareTextIcon className="size-4" aria-hidden />
                    Ask a question instead
                  </Link>
                </Button>
              </div>
              <p className="type-meta text-ink-faint mt-4">
                Free while in development. No card required.
              </p>
            </div>

            <div className="mt-14 lg:col-span-6 lg:mt-0">
              {/* The product visual: a real record, stacked like the printed
                  artefact it is. Two sheets behind, offset upward, no rotation. */}
              <div className="relative">
                <div
                  aria-hidden
                  className="border-hairline bg-surface absolute inset-x-6 -top-3.5 h-full rounded-2xl border opacity-60 shadow-[var(--shadow-sm)]"
                />
                <div
                  aria-hidden
                  className="border-hairline bg-surface absolute inset-x-3 -top-1.5 h-full rounded-2xl border opacity-80 shadow-[var(--shadow-sm)]"
                />
                <div className="relative">
                  <AssessmentCard />
                </div>
              </div>
            </div>
          </div>
          <div className="border-hairline border-t">
            <dl className="mx-auto grid max-w-6xl grid-cols-2 gap-x-8 gap-y-6 px-6 py-8 lg:grid-cols-4">
              {FACTS.map(({ label, value }) => (
                <div key={label}>
                  <dt className="type-eyebrow text-ink-faint">{label}</dt>
                  <dd className="type-meta text-ink mt-1.5 font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        {/* The problem */}
        <section className="border-hairline bg-surface-sunken/40 border-b">
          <div className="reveal mx-auto max-w-6xl px-6 py-20 lg:py-28">
            <div className="lg:grid lg:grid-cols-12 lg:gap-14">
              <div className="lg:col-span-5">
                <p className="type-eyebrow text-ink-faint">The problem</p>
                <h2 className="type-h2 text-ink mt-4 text-balance">
                  The law is public. That is not the same as usable.
                </h2>
              </div>
              <div className="mt-6 lg:col-span-7 lg:mt-0">
                <p className="type-lead text-ink-soft text-pretty">
                  The Act runs to 113 articles and 13 annexes, amended once already. Working
                  out whether it classifies your system as high-risk, and what that obliges
                  you to do, means reading Article 6, Annex III and a dozen more provisions
                  against your own facts.
                </p>
                <p className="type-body text-ink-soft mt-5">
                  Teams end up choosing between an enterprise GRC suite they cannot justify, a
                  lawyer they cannot yet afford, and a confident chatbot answer they cannot
                  check. This is the fourth option: a structured assessment that quotes the
                  primary text back to you, provision by provision.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="border-hairline border-b">
          <div className="mx-auto max-w-6xl px-6 py-20 lg:py-28">
            <div className="reveal max-w-[38rem]">
              <p className="type-eyebrow text-ink-faint">How it works</p>
              <h2 className="type-h2 text-ink mt-4 text-balance">
                Describe, classify, then read the law. In that order.
              </h2>
              <p className="type-lead text-ink-soft mt-5 text-pretty">
                The classification never touches a language model, and the report never
                paraphrases a provision. What you read is the Act.
              </p>
            </div>

            <ol className="mt-14 grid gap-5 lg:grid-cols-3">
              {STEPS.map(({ n, icon: Icon, title, body }) => (
                <li key={n} className="reveal card-raised rounded-2xl p-7 lg:p-9">
                  <div className="flex items-center justify-between">
                    <span className="bg-accent-soft text-accent-solid flex size-10 items-center justify-center rounded-xl">
                      <Icon className="size-[18px]" aria-hidden />
                    </span>
                    <span className="font-display text-ink-faint text-[1.75rem] leading-none">{n}</span>
                  </div>
                  <h3 className="type-h3 text-ink mt-5">{title}</h3>
                  <p className="type-meta text-ink-soft mt-2.5">{body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Ask a question (secondary) */}
        <section className="border-hairline bg-surface-sunken/40 border-b" data-chat-section>
          <div className="reveal mx-auto max-w-6xl px-6 py-20 lg:grid lg:grid-cols-12 lg:items-center lg:gap-16 lg:py-28">
            <div className="lg:col-span-5">
              <p className="type-eyebrow text-ink-faint">Also available</p>
              <h2 className="type-h2 text-ink mt-4 text-balance">
                Ask a question, get the provision back.
              </h2>
              <p className="type-lead text-ink-soft mt-5 text-pretty">
                For anything the questionnaire does not cover, the copilot answers from the
                retrieved provisions alone and cites them. When they do not answer the
                question, it declines.
              </p>
              <Button asChild variant="outline" className="mt-7">
                <Link href={chatHref}>
                  Open the copilot <ArrowRightIcon className="size-4" aria-hidden />
                </Link>
              </Button>
            </div>
            <div className="mt-10 lg:col-span-7 lg:mt-0">
              <AnswerCard />
            </div>
          </div>
        </section>

        {/* Why trust it */}
        <section className="border-hairline border-b">
          <div className="mx-auto max-w-6xl px-6 py-20 lg:py-28">
            <div className="reveal max-w-[38rem]">
              <p className="type-eyebrow text-ink-faint">Why trust it</p>
              <h2 className="type-h2 text-ink mt-4 text-balance">
                Built so it cannot confidently make things up.
              </h2>
            </div>
            <div className="mt-14 grid gap-10 lg:grid-cols-3 lg:gap-12">
              {PILLARS.map(({ icon: Icon, title, body }) => (
                <div key={title} className="reveal max-w-[26rem]">
                  <span className="bg-brand-solid text-brand-on flex size-11 items-center justify-center rounded-xl shadow-[inset_0_1px_0_oklch(1_0_0/0.14),var(--shadow-xs)]">
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <h3 className="type-h3 text-ink mt-5">{title}</h3>
                  <p className="type-meta text-ink-soft mt-3">{body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Who it is for */}
        <section className="border-hairline bg-surface-sunken/40 border-b">
          <div className="mx-auto max-w-6xl px-6 py-20 lg:py-28">
            <div className="reveal flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-[34rem]">
                <p className="type-eyebrow text-ink-faint">Who it is for</p>
                <h2 className="type-h2 text-ink mt-4 text-balance">
                  Teams who need a straight answer.
                </h2>
              </div>
              <p className="type-meta text-ink-soft max-w-[22rem] lg:pb-1.5">
                Built for the people the enterprise compliance market ignores.
              </p>
            </div>
            <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {AUDIENCES.map(({ icon: Icon, title, body }) => (
                <div key={title} className="reveal card-raised rounded-2xl p-7">
                  <span className="bg-accent-soft text-accent-solid flex size-9 items-center justify-center rounded-lg">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <h3 className="type-h3 text-ink mt-5">{title}</h3>
                  <p className="type-meta text-ink-soft mt-2.5">{body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section>
          <div className="mx-auto max-w-6xl px-6 py-20 lg:py-28">
            <div className="reveal bg-brand-solid flex flex-col gap-10 rounded-3xl px-6 py-16 shadow-[var(--shadow-lg),inset_0_1px_0_oklch(1_0_0/0.10)] sm:px-14 lg:flex-row lg:items-center lg:justify-between lg:py-20">
              <div className="max-w-[34rem]">
                <h2 className="type-display-sm text-brand-on text-balance">
                  Find out where you stand.
                </h2>
                <p className="type-lead text-brand-on/85 mt-5 text-pretty">
                  Assess one system and read the exact provisions that appear to apply to it.
                </p>
                <Button
                  asChild
                  size="lg"
                  className="type-body bg-brand-on text-brand-solid hover:bg-brand-on/90 mt-9 h-12 px-7 shadow-none"
                >
                  <Link href={assessHref}>
                    Assess your AI system
                    <ArrowRightIcon className="size-4" aria-hidden />
                  </Link>
                </Button>
              </div>
              <Mark className="text-brand-on/90 hidden size-24 text-[4rem] lg:flex" />
            </div>
            <div className="mx-auto mt-12 max-w-[46rem]">
              <LegalNotice />
            </div>
          </div>
        </section>
      </main>

      <footer className="border-hairline border-t">
        <div className="mx-auto max-w-6xl px-6 py-14">
          <div className="flex flex-col gap-10 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-[22rem]">
              <Wordmark />
              <p className="type-meta text-ink-soft mt-4">
                Where an AI system sits under the EU AI Act, with the provisions quoted from the
                consolidated text.
              </p>
            </div>
            <nav aria-label="Footer" className="grid grid-cols-2 gap-x-12 gap-y-3 sm:grid-cols-3">
              <div className="space-y-2.5">
                <p className="type-eyebrow text-ink-faint">Product</p>
                <Link href={assessHref} className="type-meta text-ink-soft hover:text-ink block">
                  Assess a system
                </Link>
                <Link href={chatHref} className="type-meta text-ink-soft hover:text-ink block">
                  Ask the copilot
                </Link>
              </div>
              <div className="space-y-2.5">
                <p className="type-eyebrow text-ink-faint">Source</p>
                <a
                  href="https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727"
                  target="_blank"
                  rel="noreferrer noopener"
                  className="type-meta text-ink-soft hover:text-ink block"
                >
                  Consolidated text on EUR-Lex
                </a>
              </div>
              <div className="space-y-2.5">
                <p className="type-eyebrow text-ink-faint">Account</p>
                <Link href={signedIn ? "/app" : "/signin"} className="type-meta text-ink-soft hover:text-ink block">
                  {signedIn ? "Open the app" : "Sign in"}
                </Link>
              </div>
            </nav>
          </div>
          <div className="border-hairline type-micro text-ink-faint mt-12 flex flex-col gap-2 border-t pt-6 sm:flex-row sm:items-center sm:justify-between">
            <p>Informational tool. Not legal advice. Only the Official Journal text is legally authentic.</p>
            <p>AI Act Copilot</p>
          </div>
        </div>
      </footer>
    </>
  );
}
