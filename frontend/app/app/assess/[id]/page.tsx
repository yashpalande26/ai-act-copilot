import Link from "next/link";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { SavedAssessmentView } from "@/components/assess/saved-assessment";
import { SiteHeader } from "@/components/site-header";

export default async function SavedAssessmentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await auth();
  if (!session?.user?.email) redirect("/signin");
  const { id } = await params;

  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader width="wide">
        <Link href="/app" className="type-meta text-ink-soft hover:text-ink">
          Back to chat
        </Link>
      </SiteHeader>
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
        <p className="type-eyebrow text-ink-faint mb-4">Saved assessment</p>
        <SavedAssessmentView id={id} />
      </main>
    </div>
  );
}
