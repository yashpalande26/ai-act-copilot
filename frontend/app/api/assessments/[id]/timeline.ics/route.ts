import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getAssessment } from "@/lib/fastapi";
import { buildIcs } from "@/lib/timeline";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** PROTOTYPE BFF: the saved assessment's dated obligations as an iCalendar
 *  file. Owner-scoped by FastAPI (404 for a foreign or unknown id); built from
 *  the same report the record shows, dates quoted from Article 113. */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user?.email) {
    return NextResponse.json({ error: "unauthorized", message: "Please sign in to continue." }, { status: 401 });
  }
  const { id } = await params;
  if (!UUID_RE.test(id)) {
    return NextResponse.json({ error: "not_found", message: "That assessment could not be found." }, { status: 404 });
  }
  const outcome = await getAssessment({ subject: session.user.id ?? session.user.email, email: session.user.email }, id);
  if (outcome.kind !== "ok") {
    const status = outcome.kind === "not_found" ? 404 : outcome.kind === "unavailable" ? 503 : 500;
    return NextResponse.json({ error: outcome.kind, message: "The timeline is unavailable." }, { status });
  }
  const ics = buildIcs(outcome.data.report, id, outcome.data.report.headline_text);
  return new NextResponse(ics, {
    status: 200,
    headers: {
      "content-type": "text/calendar; charset=utf-8",
      "content-disposition": `attachment; filename="ai-act-obligations-${id.slice(0, 8)}.ics"`,
      "cache-control": "no-store",
    },
  });
}
