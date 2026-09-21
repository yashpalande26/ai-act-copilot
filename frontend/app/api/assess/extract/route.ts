import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { extractAnswers } from "@/lib/fastapi";

const MAX_DESCRIPTION_CHARS = 4000; // mirrors backend config.MAX_DESCRIPTION_CHARS

/**
 * BFF: a description in, pre-filled answers + provenance out. This is a paid
 * call (gpt-4o-mini) and counts against the same daily quota as chat; the
 * backend enforces both. Nothing here is a verdict: the engine runs only after
 * the user has confirmed the answers, through /api/assess as usual.
 */
export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { error: "unauthorized", message: "Please sign in to continue." },
      { status: 401 },
    );
  }

  let description: unknown;
  try {
    ({ description } = (await request.json()) as { description?: unknown });
  } catch {
    return NextResponse.json({ error: "invalid", message: "Malformed request." }, { status: 400 });
  }
  if (typeof description !== "string" || description.trim().length < 20) {
    return NextResponse.json(
      { error: "invalid", message: "Please describe the system in at least a sentence or two." },
      { status: 422 },
    );
  }
  if (description.length > MAX_DESCRIPTION_CHARS) {
    return NextResponse.json(
      { error: "invalid", message: `Please keep the description under ${MAX_DESCRIPTION_CHARS} characters.` },
      { status: 422 },
    );
  }

  const outcome = await extractAnswers(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    description.trim(),
  );

  switch (outcome.kind) {
    case "ok":
      return NextResponse.json(outcome.data, { status: 201 });
    case "rate_limited":
      return NextResponse.json(
        {
          error: "rate_limited",
          scope: outcome.scope,
          message:
            outcome.scope === "daily"
              ? "You have reached today's limit for this feature. It resets at midnight UTC; the questionnaire is free to fill in by hand."
              : "You are sending requests quickly. Please wait a moment and try again.",
        },
        { status: 429 },
      );
    case "invalid":
      return NextResponse.json(
        {
          error: "invalid",
          message: "That description could not be turned into answers. You can fill in the questionnaire by hand.",
        },
        { status: 422 },
      );
    case "unauthorized":
      return NextResponse.json(
        { error: "error", message: "The service is misconfigured. Please try again later." },
        { status: 500 },
      );
    case "unavailable":
      return NextResponse.json(
        {
          error: "unavailable",
          message: "Pre-filling is temporarily unavailable. The questionnaire still works by hand.",
        },
        { status: 503 },
      );
    default:
      return NextResponse.json(
        { error: "error", message: "Could not pre-fill the questionnaire." },
        { status: 500 },
      );
  }
}
