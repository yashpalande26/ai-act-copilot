import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { postAssessment } from "@/lib/fastapi";
import type { Answers } from "@/lib/types";

/**
 * BFF: answers in, report out. Deterministic on the backend; nothing is
 * stored and nothing paid is called. The body is passed through as JSON and
 * validated by FastAPI's Answers model (422 -> "invalid").
 */
export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { error: "unauthorized", message: "Please sign in to continue." },
      { status: 401 },
    );
  }

  let answers: Answers;
  try {
    answers = (await request.json()) as Answers;
  } catch {
    return NextResponse.json({ error: "invalid", message: "Malformed request." }, { status: 400 });
  }

  const outcome = await postAssessment(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    answers,
  );

  switch (outcome.kind) {
    case "ok":
      return NextResponse.json(outcome.data);
    case "invalid":
      return NextResponse.json(
        { error: "invalid", message: "Some answers could not be processed." },
        { status: 422 },
      );
    case "unauthorized":
      return NextResponse.json(
        { error: "error", message: "The service is misconfigured. Please try again later." },
        { status: 500 },
      );
    case "unavailable":
      return NextResponse.json(
        { error: "unavailable", message: "The assessment is temporarily unavailable." },
        { status: 503 },
      );
    default:
      return NextResponse.json(
        { error: "error", message: "Could not build the report." },
        { status: 500 },
      );
  }
}
