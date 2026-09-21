import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { fetchAssessmentExport } from "@/lib/fastapi";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * BFF: relays the backend's self-contained HTML record. Ownership is decided
 * by FastAPI (404 for a foreign or unknown id). `?download=1` passes through
 * so the same link can open in a tab or save to disk.
 */
export async function GET(
  request: Request,
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
  const download = new URL(request.url).searchParams.get("download") === "1";

  const outcome = await fetchAssessmentExport(
    { subject: session.user.id ?? session.user.email, email: session.user.email },
    id,
    download,
  );

  switch (outcome.kind) {
    case "ok":
      return new Response(outcome.html, {
        status: 200,
        headers: {
          "content-type": "text/html; charset=utf-8",
          "content-disposition": outcome.contentDisposition,
          "cache-control": "no-store",
          // The document carries no scripts; forbid any from running anyway.
          "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        },
      });
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
        { error: "unavailable", message: "Export is temporarily unavailable." },
        { status: 503 },
      );
    default:
      return NextResponse.json(
        { error: "error", message: "Could not export that assessment." },
        { status: 500 },
      );
  }
}
