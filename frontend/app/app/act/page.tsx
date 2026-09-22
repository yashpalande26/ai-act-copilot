import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { Glossary } from "@/components/act/glossary";
import { AccountMenu } from "@/components/app/account-menu";
import { AppShell } from "@/components/app/app-shell";
import { PageHeader } from "@/components/app/page-header";
import { isAdminEmail } from "@/lib/admin";

/** PROTOTYPE: the Act navigator, starting from the Article 3 definitions. */
export default async function ActPage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/signin");
  const user = {
    name: session.user.name ?? null,
    email: session.user.email,
    image: session.user.image ?? null,
    isAdmin: isAdminEmail(session.user.email),
  };
  return (
    <AppShell isAdmin={user.isAdmin} account={<AccountMenu user={user} />} accountCompact={<AccountMenu user={user} compact />} title="The Act" width="form">
      <PageHeader
        eyebrow="The Act, navigator"
        title="Definitions, word for word."
        description="Every term Article 3 defines, quoted from the consolidated text, with a link to the provision and to EUR-Lex. Open any provision to see what it refers to and what refers to it. Nothing here is generated."
      />
      <Glossary />
    </AppShell>
  );
}
