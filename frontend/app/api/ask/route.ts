import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { askBackend } from "@/lib/fastapi";

const MAX_QUESTION_CHARS = 2000; // mirrors the backend's Pydantic ceiling

/**
 * BFF route handler.
 *
 * The browser never holds a FastAPI credential. It sends only the Auth.js
 * httpOnly session cookie. This handler verifies that session server-side,
 * then mints a short-lived signed token for the backend. The OpenAI-spending
 * endpoint is therefore never reachable from the open internet with a
 * browser-held token.
 */
export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { error: "unauthorized", message: "Please sign in to continue." },
      { status: 401 },
    );
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: "invalid", message: "Malformed request." },
      { status: 400 },
    );
  }

  const { question, sessionId } = (payload ?? {}) as {
    question?: unknown;
    sessionId?: unknown;
  };

  // Validate here as well as in FastAPI: rejecting locally means an oversized
  // question never even crosses the network, let alone reaches the model.
  if (typeof question !== "string" || question.trim().length === 0) {
    return NextResponse.json(
      { error: "invalid", message: "Please enter a question." },
      { status: 422 },
    );
  }
  if (question.length > MAX_QUESTION_CHARS) {
    return NextResponse.json(
      {
        error: "invalid",
        message: `Questions are limited to ${MAX_QUESTION_CHARS} characters.`,
      },
      { status: 422 },
    );
  }

  const outcome = await askBackend({
    subject: session.user.id ?? session.user.email,
    email: session.user.email,
    question: question.trim(),
    sessionId: typeof sessionId === "string" ? sessionId : undefined,
  });

  switch (outcome.kind) {
    case "ok":
      return NextResponse.json(outcome.data);
    case "rate_limited":
      return NextResponse.json(
        {
          error: "rate_limited",
          scope: outcome.scope,
          message:
            outcome.scope === "daily"
              ? "You have reached today's question limit. It resets at midnight UTC."
              : "You are sending questions quickly. Please wait a moment and try again.",
        },
        { status: 429 },
      );
    case "invalid":
      return NextResponse.json(
        { error: "invalid", message: "That question could not be processed." },
        { status: 422 },
      );
    case "unauthorized":
      // The backend rejected OUR service token, meaning a server
      // misconfiguration (wrong or missing INTERNAL_API_SECRET).
      // Never the user's fault.
      return NextResponse.json(
        {
          error: "error",
          message: "The service is misconfigured. Please try again later.",
        },
        { status: 500 },
      );
    case "unavailable":
      return NextResponse.json(
        {
          error: "unavailable",
          message: "The copilot is temporarily unavailable. Please try again shortly.",
        },
        { status: 503 },
      );
    default:
      return NextResponse.json(
        { error: "error", message: "Something went wrong. Please try again." },
        { status: 500 },
      );
  }
}
