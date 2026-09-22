import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AccountMenu } from "@/components/app/account-menu";
import { AppShell } from "@/components/app/app-shell";
import { SavedAssessmentView } from "@/components/assess/saved-assessment";
import { AssessmentsRail } from "@/components/chat/assessments-rail";
import { isAdminEmail } from "@/lib/admin";

export default async function SavedAssessmentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
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
    <AppShell
      isAdmin={user.isAdmin}
      account={<AccountMenu user={user} />}
      accountCompact={<AccountMenu user={user} compact />}
      rail={<AssessmentsRail />}
      title="Saved assessment"
      width="form"
    >
      <p className="type-eyebrow text-ink-faint mb-4">Saved assessment</p>
      <SavedAssessmentView id={id} />
    </AppShell>
  );
}
