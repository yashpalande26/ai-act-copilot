import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { listAssessments, saveAssessment } from "@/lib/fastapi";
import type { Answers } from "@/lib/types";

const UNAUTHORIZED = NextResponse.json(
  { error: "unauthorized", message: "Please sign in to continue." },
  { status: 401 },
);

function relay(outcome: { kind: string; data?: unknown }, notFoundMessage: string) {
  switch (outcome.kind) {
    case "ok":
      return NextResponse.json(outcome.data);
    case "invalid":
      return NextResponse.json(
        { error: "invalid", message: "Some answers could not be processed." },
        { status: 422 },
      );
    case "not_found":
      return NextResponse.json({ error: "not_found", message: notFoundMessage }, { status: 404 });
    case "unauthorized":
      return NextResponse.json(
        { error: "error", message: "The service is misconfigured. Please try again later." },
        { status: 500 },
      );
    case "unavailable":
      return NextResponse.json(
        { error: "unavailable", message: "Saved assessments are temporarily unavailable." },
        { status: 503 },
      );
    default:
      return NextResponse.json({ error: "error", message: "Something went wrong." }, { status: 500 });
  }
}

/** BFF: the signed-in user's saved assessments (owner-scoped by FastAPI). */
export async function GET() {
  const session = await auth();
  if (!session?.user?.email) return UNAUTHORIZED;
  const outcome = await listAssessments({
    subject: session.user.id ?? session.user.email,
    email: session.user.email,
  });
  return relay(outcome, "Not found.");
}

/** BFF: save. Only the answers travel; the backend re-derives the result. */
export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.email) return UNAUTHORIZED;

  let answers: Answers;
  try {
    answers = (await request.json()) as Answers;
  } catch {
    return NextResponse.json({ error: "invalid", message: "Malformed request." }, { status: 400 });
  }

  const outcome = await saveAssessment(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    answers,
  );
  if (outcome.kind === "ok") return NextResponse.json(outcome.data, { status: 201 });
  return relay(outcome, "Not found.");
}
