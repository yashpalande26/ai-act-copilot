import { Suspense } from "react";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AccountMenu } from "@/components/app/account-menu";
import { ChatShell } from "@/components/chat/chat-shell";
import { isAdminEmail } from "@/lib/admin";

export default async function AppPage() {
  const session = await auth();
  // Middleware already gates this route; this is the defence-in-depth check
  // that doesn't depend on matcher config being correct.
  if (!session?.user?.email) redirect("/signin");

  const email = session.user.email;
  const name = session.user.name?.split(" ")[0] ?? email.split("@")[0];
  const user = {
    name: session.user.name ?? null,
    email,
    image: session.user.image ?? null,
    isAdmin: isAdminEmail(email),
  };

  return (
    // Suspense: ChatShell reads ?s= via useSearchParams.
    <Suspense fallback={null}>
      <ChatShell
        userName={name}
        isAdmin={user.isAdmin}
        account={<AccountMenu user={user} />}
        accountCompact={<AccountMenu user={user} compact />}
      />
    </Suspense>
  );
}
