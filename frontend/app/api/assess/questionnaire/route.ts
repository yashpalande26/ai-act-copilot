import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getQuestionnaire } from "@/lib/fastapi";

/** BFF: the questionnaire definition with the provision text each question rests on. */
export async function GET() {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { error: "unauthorized", message: "Please sign in to continue." },
      { status: 401 },
    );
  }

  const outcome = await getQuestionnaire({
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
        { error: "unavailable", message: "The assessment is temporarily unavailable." },
        { status: 503 },
      );
    default:
      return NextResponse.json(
        { error: "error", message: "Could not load the questionnaire." },
        { status: 500 },
      );
  }
}
