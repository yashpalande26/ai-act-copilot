import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AccountMenu } from "@/components/app/account-menu";
import { AppShell } from "@/components/app/app-shell";
import { PageHeader } from "@/components/app/page-header";
import { AssessFlow } from "@/components/assess/assess-flow";
import { AssessmentsRail } from "@/components/chat/assessments-rail";
import { isAdminEmail } from "@/lib/admin";

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
  const user = {
    name: session.user.name ?? null,
    email: session.user.email,
    image: session.user.image ?? null,
    isAdmin: isAdminEmail(session.user.email),
  };

  return (
    <AppShell
      isAdmin={user.isAdmin}
      account={<AccountMenu user={user} />}
      accountCompact={<AccountMenu user={user} compact />}
      rail={<AssessmentsRail />}
      title="Assessment"
      width="form"
    >
      <PageHeader
        eyebrow="Assessment"
        title="Where does your AI system sit under the Act?"
        description="Describe the system for a head start, or answer the short questionnaire directly. The result quotes the provisions it rests on, word for word, and computes the fine ceilings from that text. It is informational, not legal advice."
      />
      <AssessFlow initialDescription={initialDescription} />
    </AppShell>
  );
}
