import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { SiteHeader } from "@/components/site-header";
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

  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader width="wide">
        <Link href="/app" className="type-meta text-ink-soft hover:text-ink">
          Back to chat
        </Link>
      </SiteHeader>
      {/* 7xl rather than the app's 6xl: an operator table earns the width. */}
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">{children}</main>
    </div>
  );
}
