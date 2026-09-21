import Link from "next/link";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AssessFlow } from "@/components/assess/assess-flow";
import { SiteHeader } from "@/components/site-header";

/**
 * The assessment wedge: describe the system -> deterministic classification ->
 * obligations quoted verbatim -> fine ceilings computed from the quoted text.
 * Nothing is stored; nothing paid is called.
 */
export default async function AssessPage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/signin");

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
          <AssessFlow />
        </div>
      </main>
    </div>
  );
}
