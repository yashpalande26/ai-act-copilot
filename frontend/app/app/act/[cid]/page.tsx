import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { ProvisionViewer } from "@/components/act/provision-view";
import { AccountMenu } from "@/components/app/account-menu";
import { AppShell } from "@/components/app/app-shell";
import { isAdminEmail } from "@/lib/admin";

/** PROTOTYPE: one provision with its text-derived cross-references. */
export default async function ProvisionPage({ params }: { params: Promise<{ cid: string }> }) {
  const session = await auth();
  if (!session?.user?.email) redirect("/signin");
  const { cid } = await params;
  const user = {
    name: session.user.name ?? null,
    email: session.user.email,
    image: session.user.image ?? null,
    isAdmin: isAdminEmail(session.user.email),
  };
  return (
    <AppShell isAdmin={user.isAdmin} account={<AccountMenu user={user} />} accountCompact={<AccountMenu user={user} compact />} title="The Act" width="reading">
      <p className="type-eyebrow text-ink-faint mb-4">The Act, navigator</p>
      <ProvisionViewer cid={cid} />
    </AppShell>
  );
}
