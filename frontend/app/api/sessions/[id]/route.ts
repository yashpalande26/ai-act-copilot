import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getSession } from "@/lib/fastapi";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * BFF: one past chat with its messages and citations. The id in the URL is a
 * hint, not a capability: FastAPI checks that the verified caller owns the
 * session and answers 404 otherwise, the same 404 it gives for an id that
 * does not exist.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { error: "unauthorized", message: "Please sign in to continue." },
      { status: 401 },
    );
  }

  const { id } = await params;
  if (!UUID_RE.test(id)) {
    return NextResponse.json(
      { error: "not_found", message: "That chat could not be found." },
      { status: 404 },
    );
  }

  const outcome = await getSession(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    id,
  );

  switch (outcome.kind) {
    case "ok":
      return NextResponse.json(outcome.data);
    case "not_found":
      return NextResponse.json(
        { error: "not_found", message: "That chat could not be found." },
        { status: 404 },
      );
    case "unauthorized":
      return NextResponse.json(
        { error: "error", message: "The service is misconfigured. Please try again later." },
        { status: 500 },
      );
    case "unavailable":
      return NextResponse.json(
        { error: "unavailable", message: "History is temporarily unavailable." },
        { status: 503 },
      );
    default:
      return NextResponse.json(
        { error: "error", message: "Could not load that chat." },
        { status: 500 },
      );
  }
}
