import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { AccountMenu } from "@/components/app/account-menu";
import { AppShell } from "@/components/app/app-shell";
import { isAdminEmail } from "@/lib/admin";

/**
 * Admin shell. Non-admins get the app's normal 404 here, for UX; the real
 * gate is FastAPI's require_admin on every /admin request, which the BFF
 * relays as 404 regardless of what this layout decides.
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session?.user?.email) redirect("/signin");
  if (!isAdminEmail(session.user.email)) notFound();
  const user = {
    name: session.user.name ?? null,
    email: session.user.email,
    image: session.user.image ?? null,
    isAdmin: true,
  };

  return (
    <AppShell
      isAdmin
      account={<AccountMenu user={user} />}
      accountCompact={<AccountMenu user={user} compact />}
      title="Admin"
      width="wide"
    >
      {children}
    </AppShell>
  );
}
