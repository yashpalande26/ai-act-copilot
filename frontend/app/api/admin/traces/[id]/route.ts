import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getTrace } from "@/lib/fastapi";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** BFF for one trace. Relays FastAPI's admin decision; validates the id. */
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
    return NextResponse.json({ error: "not_found", message: "Not found." }, { status: 404 });
  }

  const outcome = await getTrace(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    id,
  );

  switch (outcome.kind) {
    case "ok":
      return NextResponse.json(outcome.data);
    case "not_found":
      return NextResponse.json({ error: "not_found", message: "Not found." }, { status: 404 });
    case "unauthorized":
      return NextResponse.json(
        { error: "error", message: "The service is misconfigured. Please try again later." },
        { status: 500 },
      );
    case "unavailable":
      return NextResponse.json(
        { error: "unavailable", message: "Traces are temporarily unavailable." },
        { status: 503 },
      );
    default:
      return NextResponse.json(
        { error: "error", message: "Could not load that trace." },
        { status: 500 },
      );
  }
}
