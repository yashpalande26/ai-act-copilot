import Link from "next/link";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AssessFlow } from "@/components/assess/assess-flow";
import { SiteHeader } from "@/components/site-header";

/**
 * The assessment wedge: describe the system -> deterministic classification ->
 * obligations quoted verbatim -> fine ceilings computed from the quoted text.
 * Nothing is stored until the user saves. `?describe=` carries the user's own
 * words from a chat turn into the describe box (the funnel): text only,
 * nothing is called by arriving here.
 */
export default async function AssessPage({
  searchParams,
}: {
  searchParams: Promise<{ describe?: string }>;
}) {
  const session = await auth();
  if (!session?.user?.email) redirect("/signin");
  const { describe } = await searchParams;
  const initialDescription = typeof describe === "string" ? describe.slice(0, 4000) : undefined;

  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader width="wide">
        <Link href="/app" className="type-meta text-ink-soft hover:text-ink">
          Back to chat
        </Link>
      </SiteHeader>
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
        <p className="type-eyebrow text-ink-faint">Assessment</p>
        <h1 className="type-h2 mt-2 text-balance">Where does your AI system sit under the Act?</h1>
        <p className="type-lead text-muted-foreground mt-4 max-w-[42rem]">
          Describe the system for a head start, or answer the short questionnaire directly. The
          result quotes the provisions it rests on, word for word, and computes the fine ceilings
          from that text. It is informational, not legal advice.
        </p>
        <div className="mt-10">
          <AssessFlow initialDescription={initialDescription} />
        </div>
      </main>
    </div>
  );
}
