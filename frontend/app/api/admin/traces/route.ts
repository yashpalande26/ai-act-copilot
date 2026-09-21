import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { listTraces } from "@/lib/fastapi";

const ENVIRONMENTS = new Set(["production", "dev", "test"]);
const ISO_RE = /^\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})$/;
// Shape check only (exact match happens server-side); keeps junk out of the URL.
const EMAIL_RE = /^[^\s@/]{1,128}@[^\s@/]{1,128}$/;

/**
 * BFF for the admin trace list. Relays only: the admin decision is FastAPI's
 * (require_admin), and a non-admin gets the backend's 404 straight back.
 */
export async function GET(request: Request) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json(
      { error: "unauthorized", message: "Please sign in to continue." },
      { status: 401 },
    );
  }

  const url = new URL(request.url);
  const limitRaw = Number(url.searchParams.get("limit") ?? "50");
  const limit = Number.isInteger(limitRaw) && limitRaw >= 1 && limitRaw <= 200 ? limitRaw : 50;
  const before = url.searchParams.get("before") ?? undefined;
  const environment = url.searchParams.get("environment") ?? undefined;
  const userEmail = url.searchParams.get("user_email")?.trim() ?? undefined;

  const outcome = await listTraces(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    {
      limit,
      before: before && ISO_RE.test(before) ? before : undefined,
      environment: environment && ENVIRONMENTS.has(environment) ? environment : undefined,
      userEmail: userEmail && EMAIL_RE.test(userEmail) ? userEmail : undefined,
    },
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
        { error: "error", message: "Could not load traces." },
        { status: 500 },
      );
  }
}
