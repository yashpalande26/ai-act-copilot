import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AssessmentTimeline } from "@/components/act/timeline";
import { AccountMenu } from "@/components/app/account-menu";
import { AppShell } from "@/components/app/app-shell";
import { PageHeader } from "@/components/app/page-header";
import { AssessmentsRail } from "@/components/chat/assessments-rail";
import { isAdminEmail } from "@/lib/admin";

/** PROTOTYPE: when each obligation of a saved assessment starts to apply. */
export default async function TimelinePage({ params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user?.email) redirect("/signin");
  const { id } = await params;
  const user = {
    name: session.user.name ?? null,
    email: session.user.email,
    image: session.user.image ?? null,
    isAdmin: isAdminEmail(session.user.email),
  };
  return (
    <AppShell isAdmin={user.isAdmin} account={<AccountMenu user={user} />} accountCompact={<AccountMenu user={user} compact />} rail={<AssessmentsRail />} title="Timeline" width="form">
      <PageHeader eyebrow="Saved assessment, timeline" title="When these obligations start to apply." description="The obligation groups of this record, ordered by the application date quoted from Article 113 for each. Export them to your calendar." />
      <AssessmentTimeline id={id} />
    </AppShell>
  );
}
