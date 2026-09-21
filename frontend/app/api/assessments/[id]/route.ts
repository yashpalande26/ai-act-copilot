import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getAssessment } from "@/lib/fastapi";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * BFF: one saved assessment. The id is a hint, not a capability: FastAPI
 * checks ownership and answers the same 404 for a foreign or unknown id.
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
      { error: "not_found", message: "That assessment could not be found." },
      { status: 404 },
    );
  }

  const outcome = await getAssessment(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    id,
  );

  switch (outcome.kind) {
    case "ok":
      return NextResponse.json(outcome.data);
    case "not_found":
      return NextResponse.json(
        { error: "not_found", message: "That assessment could not be found." },
        { status: 404 },
      );
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
      return NextResponse.json(
        { error: "error", message: "Could not load that assessment." },
        { status: 500 },
      );
  }
}
