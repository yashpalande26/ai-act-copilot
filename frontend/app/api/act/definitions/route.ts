import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getDefinitions } from "@/lib/fastapi";

/** PROTOTYPE BFF: the Article 3 definitions, verbatim. Read-only, free. */
export async function GET(request: Request) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized", message: "Please sign in to continue." }, { status: 401 });
  }
  const q = new URL(request.url).searchParams.get("q") ?? "";
  const outcome = await getDefinitions(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    q.slice(0, 80),
  );
  if (outcome.kind === "ok") return NextResponse.json(outcome.data);
  return NextResponse.json({ error: outcome.kind, message: "The definitions are unavailable right now." }, { status: outcome.kind === "unavailable" ? 503 : 500 });
}
