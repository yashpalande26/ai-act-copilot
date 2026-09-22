import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getProvision } from "@/lib/fastapi";

const CID_RE = /^[a-z]+_[0-9a-zA-Z]+(\.[a-z]+_[0-9a-zA-Z]+)*$/;

/** PROTOTYPE BFF: one provision with text-derived cross-references. */
export async function GET(_request: Request, { params }: { params: Promise<{ cid: string }> }) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized", message: "Please sign in to continue." }, { status: 401 });
  }
  const { cid } = await params;
  if (!CID_RE.test(cid)) {
    return NextResponse.json({ error: "not_found", message: "No such provision." }, { status: 404 });
  }
  const outcome = await getProvision(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    cid,
  );
  if (outcome.kind === "ok") return NextResponse.json(outcome.data);
  if (outcome.kind === "not_found") return NextResponse.json({ error: "not_found", message: "No such provision." }, { status: 404 });
  return NextResponse.json({ error: outcome.kind, message: "The provision is unavailable right now." }, { status: outcome.kind === "unavailable" ? 503 : 500 });
}
