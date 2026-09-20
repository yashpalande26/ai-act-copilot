import Link from "next/link";
import {
  ArrowRightIcon,
  CircleSlashIcon,
  CodeIcon,
  FileSearchIcon,
  QuoteIcon,
  RocketIcon,
  ScaleIcon,
  ShieldCheckIcon,
  SplitIcon,
  UsersIcon,
} from "lucide-react";

import { auth } from "@/auth";
import { AnswerCard } from "@/components/landing/answer-card";
import { LegalNotice } from "@/components/legal-notice";
import { SiteHeader, Wordmark } from "@/components/site-header";
import { Button } from "@/components/ui/button";

const STEPS = [
  {
    n: "01",
    icon: FileSearchIcon,
    title: "Retrieve",
    body: "Your question is matched against the consolidated Act, provision by provision, using both meaning and exact legal terminology.",
  },
  {
    n: "02",
    icon: QuoteIcon,
    title: "Cite",
    body: "The provisions that will be used are fixed first. Citations are recorded from what was retrieved, before the answer is written.",
  },
  {
    n: "03",
    icon: ScaleIcon,
    title: "Answer",
    body: "The answer is composed from those provisions alone. If they do not cover your question, it declines instead of filling the gap.",
  },
];

const PILLARS = [
  {
    icon: QuoteIcon,
    title: "Traceable to primary law",
    body: "Every citation opens the provision on EUR-Lex, word for word. Citations come from the retrieved text rather than from model prose, so the trail survives even when the wording does not.",
  },
  {
    icon: CircleSlashIcon,
    title: "It abstains when unsure",
    body: "When the retrieved provisions do not answer the question, the copilot says so. A visible refusal is worth more than a confident invention on a subject where being wrong is expensive.",
  },
  {
    icon: SplitIcon,
    title: "Deterministic logic stays out of the model",
    body: "Risk classification runs in ordinary, testable code. The language model explains and cites. It never decides the verdict, so the same input always produces the same result.",
  },
];

const AUDIENCES = [
  {
    icon: RocketIcon,
    title: "Founders",
    body: "Find out whether what you are building is high-risk before you build it, not during diligence.",
  },
  {
    icon: CodeIcon,
    title: "Developers",
    body: "Get the specific article behind a requirement, so an obligation becomes a ticket.",
  },
  {
    icon: UsersIcon,
    title: "Compliance owners",
    body: "Ask precisely, and get the provision back word for word, ready for a memo.",
  },
];

export default async function LandingPage() {
  const session = await auth();
  const signedIn = Boolean(session?.user);
  const primaryHref = signedIn ? "/app" : "/signin";
  const primaryLabel = signedIn ? "Open the copilot" : "Start asking questions";

  return (
    <>
      <SiteHeader>
        {signedIn ? (
          <Button asChild size="sm">
            <Link href="/app">
              Open copilot <ArrowRightIcon className="size-4" aria-hidden />
            </Link>
          </Button>
        ) : (
          <>
            <Button
              asChild
              variant="ghost"
              size="sm"
              className="hidden sm:inline-flex"
            >
              <Link href="/signin">Sign in</Link>
            </Button>
            <Button asChild size="sm">
              <Link href="/signin">Get started</Link>
            </Button>
          </>
        )}
      </SiteHeader>

      <main className="flex-1">
        {/* Hero */}
        <section className="relative overflow-hidden">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-0 h-[40rem] bg-[radial-gradient(60rem_28rem_at_50%_-8rem,var(--accent-soft),transparent_70%)]"
          />
          <div className="relative mx-auto max-w-6xl px-6 pt-16 pb-20 sm:pt-24 lg:grid lg:grid-cols-12 lg:items-center lg:gap-14 lg:pt-24 lg:pb-28">
            <div className="lg:col-span-6">
              <p className="type-eyebrow text-ink-faint flex items-center gap-2">
                <ShieldCheckIcon
                  className="text-accent-solid size-4"
                  aria-hidden
                />
                Consolidated EU AI Act
              </p>
              <h1 className="type-display text-ink mt-6 text-balance">
                Know your obligations, with the article to prove it.
              </h1>
              <p className="type-lead text-ink-soft mt-7 max-w-[34rem] text-pretty">
                Ask what the EU AI Act requires of your system. Every answer is
                quoted from the official text and carries a citation you can
                open. When the law does not cover your question, the copilot
                says so.
              </p>
              <div className="mt-9">
                <Button asChild size="lg" className="type-body h-12 px-7">
                  <Link href={primaryHref}>
                    {primaryLabel}
                    <ArrowRightIcon className="size-4" aria-hidden />
                  </Link>
                </Button>
                <p className="type-meta text-ink-faint mt-4">
                  Free while in development. No card required.
                </p>
              </div>
            </div>

            <div className="mt-14 lg:col-span-6 lg:mt-0">
              <AnswerCard />
            </div>
          </div>
        </section>

        {/* The problem */}
        <section className="border-hairline bg-surface-sunken/40 border-y">
          <div className="reveal mx-auto max-w-6xl px-6 py-20 lg:py-24">
            <div className="lg:grid lg:grid-cols-12 lg:gap-14">
              <div className="lg:col-span-5">
                <p className="type-eyebrow text-ink-faint">The problem</p>
                <h2 className="type-h2 text-ink mt-4 text-balance">
                  The law is public. That is not the same as usable.
                </h2>
              </div>
              <div className="mt-6 lg:col-span-7 lg:mt-0">
                <p className="type-lead text-ink-soft text-pretty">
                  The Act runs to 113 articles and 13 annexes, amended once
                  already. General chatbots answer questions about it fluently
                  and without sources, which is the worst possible combination
                  when the answer carries regulatory weight.
                </p>
                <p className="type-body text-ink-soft mt-5">
                  Teams end up choosing between an enterprise GRC suite they
                  cannot justify, a lawyer they cannot yet afford, and a
                  confident answer they cannot check. This is the fourth
                  option: read the primary text, with the provision in front of
                  you.
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
                Retrieve, cite, then answer. In that order.
              </h2>
              <p className="type-lead text-ink-soft mt-5 text-pretty">
                The sequence is the safeguard. Sources are fixed before a single
                word is written, so the answer cannot reach past them.
              </p>
            </div>

            <ol className="lg:bg-hairline mt-14 grid gap-4 overflow-hidden rounded-2xl lg:grid-cols-3 lg:gap-px">
              {STEPS.map(({ n, icon: Icon, title, body }) => (
                <li
                  key={n}
                  className="reveal border-hairline bg-surface rounded-2xl border p-7 lg:rounded-none lg:border-0 lg:p-9"
                >
                  <div className="flex items-center gap-3">
                    <span className="border-hairline bg-paper flex size-10 items-center justify-center rounded-xl border">
                      <Icon
                        className="text-accent-solid size-[18px]"
                        aria-hidden
                      />
                    </span>
                    <span className="type-mono text-ink-faint">{n}</span>
                  </div>
                  <h3 className="type-h3 text-ink mt-5">{title}</h3>
                  <p className="type-meta text-ink-soft mt-2.5">{body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Why trust it */}
        <section className="border-hairline bg-surface-sunken/40 border-b">
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
                  <span className="bg-brand-solid text-brand-on flex size-11 items-center justify-center rounded-xl">
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
        <section className="border-hairline border-b">
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
                <div
                  key={title}
                  className="reveal border-hairline bg-surface rounded-2xl border p-7 [box-shadow:var(--shadow-xs)]"
                >
                  <Icon className="text-accent-solid size-5" aria-hidden />
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
            <div className="reveal bg-brand-solid border-hairline relative overflow-hidden rounded-3xl border px-6 py-16 sm:px-14 lg:py-20">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0 bg-[radial-gradient(40rem_20rem_at_80%_-20%,oklch(1_0_0/0.10),transparent_70%)]"
              />
              <div className="relative max-w-[34rem]">
                <h2 className="type-display-sm text-brand-on text-balance">
                  Find out where you stand.
                </h2>
                <p className="type-lead text-brand-on/85 mt-5 text-pretty">
                  Ask one question about your system and read the exact
                  provisions that apply to it.
                </p>
                <Button
                  asChild
                  size="lg"
                  className="type-body bg-brand-on text-brand-solid hover:bg-brand-on/90 mt-9 h-12 px-7"
                >
                  <Link href={primaryHref}>
                    {primaryLabel}
                    <ArrowRightIcon className="size-4" aria-hidden />
                  </Link>
                </Button>
              </div>
            </div>
            <div className="mx-auto mt-12 max-w-[46rem]">
              <LegalNotice />
            </div>
          </div>
        </section>
      </main>

      <footer className="border-hairline border-t">
        <div className="text-ink-faint type-meta mx-auto flex max-w-6xl flex-col gap-5 px-6 py-12 sm:flex-row sm:items-center sm:justify-between">
          <Wordmark />
          <p>Informational tool. Not legal advice.</p>
        </div>
      </footer>
    </>
  );
}
