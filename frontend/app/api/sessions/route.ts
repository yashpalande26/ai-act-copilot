import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { listSessions } from "@/lib/fastapi";

/**
 * BFF: the signed-in user's past chats. Same shape as /api/ask: the browser
 * sends only the Auth.js cookie; identity is verified here and carried to
 * FastAPI in a short-lived service token. FastAPI scopes the list to that
 * identity, so no session id from another user can ever appear in the reply.
 */
export async function GET() {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { error: "unauthorized", message: "Please sign in to continue." },
      { status: 401 },
    );
  }

  const outcome = await listSessions({
    subject: session.user.id ?? session.user.email,
    email: session.user.email,
  });

  switch (outcome.kind) {
    case "ok":
      return NextResponse.json(outcome.data);
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
        { error: "error", message: "Could not load your chats." },
        { status: 500 },
      );
  }
}
