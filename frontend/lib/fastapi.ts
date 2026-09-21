import "server-only";

import { SignJWT } from "jose";

import type {
  Answers,
  AssessmentReport,
  QuestionnaireDef,
  SavedAssessment,
  SavedAssessmentSummary,
  SessionDetail,
  SessionSummary,
  TraceDetail,
  TraceSummary,
} from "@/lib/types";

/**
 * Server-only bridge to the FastAPI backend (the "BFF" half of the contract).
 *
 * Every export here touches INTERNAL_API_SECRET or FASTAPI_URL. The
 * `server-only` import at the top is load-bearing: if any client component
 * ever imports this module, the BUILD FAILS rather than silently shipping the
 * secret to the browser. That is the guarantee, enforced by the bundler
 * rather than by convention.
 */

export const SERVICE_TOKEN_TTL_SECONDS = 60;

export type AskCitation = {
  citation_id: string;
  citation_label: string;
  quoted_text: string;
};

export type AskResponse = {
  answer: string;
  citations: AskCitation[];
  abstained: boolean;
  session_id: string;
};

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

/**
 * Mint the short-lived HS256 token FastAPI verifies.
 *
 * Deliberately short (60s): the signing key itself never leaves the server,
 * so a leaked request log exposes at most a one-minute credential rather than
 * a standing one. FastAPI verifies with a 10s leeway to absorb clock drift
 * between the two hosts.
 */
async function mintServiceToken(subject: string, email: string): Promise<string> {
  const secret = new TextEncoder().encode(requireEnv("INTERNAL_API_SECRET"));
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({ email })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(subject)
    .setIssuedAt(now)
    .setExpirationTime(now + SERVICE_TOKEN_TTL_SECONDS)
    .sign(secret);
}

export type AskOutcome =
  | { kind: "ok"; data: AskResponse }
  | { kind: "rate_limited"; scope: "burst" | "daily" }
  | { kind: "invalid" }
  | { kind: "unauthorized" }
  | { kind: "unavailable" }
  | { kind: "error" };

/**
 * Call POST /ask. Maps backend status codes onto a closed set of outcomes so
 * the UI never has to interpret raw HTTP, and so backend error text is never
 * forwarded verbatim to the browser.
 */
export async function askBackend(
  params: { subject: string; email: string; question: string; sessionId?: string },
): Promise<AskOutcome> {
  const base = requireEnv("FASTAPI_URL").replace(/\/$/, "");
  const token = await mintServiceToken(params.subject, params.email);

  let response: Response;
  try {
    response = await fetch(`${base}/ask`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        question: params.question,
        session_id: params.sessionId ?? null,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
  } catch {
    // Network failure or timeout. The backend may be down or cold-starting.
    return { kind: "unavailable" };
  }

  if (response.ok) {
    return { kind: "ok", data: (await response.json()) as AskResponse };
  }

  if (response.status === 429) {
    // Distinguish the burst guard from the daily money cap: they need
    // different copy ("slow down" versus "come back tomorrow").
    let scope: "burst" | "daily" = "burst";
    try {
      const body = await response.json();
      const code = body?.error?.code ?? "";
      if (String(code).includes("daily")) scope = "daily";
    } catch {
      /* fall back to burst */
    }
    return { kind: "rate_limited", scope };
  }

  if (response.status === 401) return { kind: "unauthorized" };
  if (response.status === 422) return { kind: "invalid" };
  if (response.status === 503) return { kind: "unavailable" };
  return { kind: "error" };
}

// --- conversation history (read-only) ---------------------------------------

export type HistoryOutcome<T> =
  | { kind: "ok"; data: T }
  | { kind: "not_found" }
  | { kind: "unauthorized" }
  | { kind: "unavailable" }
  | { kind: "error" };

type Identity = { subject: string; email: string };

/**
 * GET against the backend with a freshly minted service token. Same token,
 * same closed set of outcomes as askBackend; these calls never spend money.
 */
async function getBackend<T>(path: string, identity: Identity): Promise<HistoryOutcome<T>> {
  const base = requireEnv("FASTAPI_URL").replace(/\/$/, "");
  const token = await mintServiceToken(identity.subject, identity.email);

  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return { kind: "unavailable" };
  }

  if (response.ok) return { kind: "ok", data: (await response.json()) as T };
  if (response.status === 404) return { kind: "not_found" };
  if (response.status === 401) return { kind: "unauthorized" };
  if (response.status === 503) return { kind: "unavailable" };
  return { kind: "error" };
}

export function listSessions(identity: Identity) {
  return getBackend<{ sessions: SessionSummary[] }>("/sessions", identity);
}

export function getSession(identity: Identity, id: string) {
  return getBackend<SessionDetail>(`/sessions/${encodeURIComponent(id)}`, identity);
}

// --- admin trace viewer (read-only, allowlisted server-side) ---------------

export function listTraces(
  identity: Identity,
  params: { limit?: number; before?: string; environment?: string; userEmail?: string },
) {
  const qs = new URLSearchParams();
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.before) qs.set("before", params.before);
  if (params.environment) qs.set("environment", params.environment);
  if (params.userEmail) qs.set("user_email", params.userEmail);
  const query = qs.toString();
  return getBackend<{ traces: TraceSummary[]; next_before: string | null }>(
    `/admin/traces${query ? `?${query}` : ""}`,
    identity,
  );
}

export function getTrace(identity: Identity, id: string) {
  return getBackend<TraceDetail>(`/admin/traces/${encodeURIComponent(id)}`, identity);
}

// --- assessment wedge (deterministic; nothing here costs money) --------------

export type AssessOutcome<T> = HistoryOutcome<T> | { kind: "invalid" };

async function postBackend<T>(
  path: string,
  identity: Identity,
  body: unknown,
): Promise<AssessOutcome<T>> {
  const base = requireEnv("FASTAPI_URL").replace(/\/$/, "");
  const token = await mintServiceToken(identity.subject, identity.email);

  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return { kind: "unavailable" };
  }

  if (response.ok) return { kind: "ok", data: (await response.json()) as T };
  if (response.status === 422) return { kind: "invalid" };
  if (response.status === 404) return { kind: "not_found" };
  if (response.status === 401) return { kind: "unauthorized" };
  if (response.status === 503) return { kind: "unavailable" };
  return { kind: "error" };
}

export function getQuestionnaire(identity: Identity) {
  return getBackend<QuestionnaireDef>("/assess/questionnaire", identity);
}

export function postAssessment(identity: Identity, answers: Answers) {
  return postBackend<AssessmentReport>("/assess", identity, answers);
}

// --- saved assessments (answers only go up; the server re-derives the result) --

export function saveAssessment(identity: Identity, answers: Answers) {
  return postBackend<SavedAssessment>("/assessments", identity, answers);
}

export function listAssessments(identity: Identity) {
  return getBackend<{ assessments: SavedAssessmentSummary[] }>("/assessments", identity);
}

export function getAssessment(identity: Identity, id: string) {
  return getBackend<SavedAssessment>(`/assessments/${encodeURIComponent(id)}`, identity);
}

export type ExportOutcome =
  | { kind: "ok"; html: string; contentDisposition: string }
  | { kind: "not_found" }
  | { kind: "unauthorized" }
  | { kind: "unavailable" }
  | { kind: "error" };

/** The self-contained HTML record, relayed byte for byte with its disposition. */
export async function fetchAssessmentExport(
  identity: Identity,
  id: string,
  download: boolean,
): Promise<ExportOutcome> {
  const base = requireEnv("FASTAPI_URL").replace(/\/$/, "");
  const token = await mintServiceToken(identity.subject, identity.email);
  const path = `/assessments/${encodeURIComponent(id)}/export.html${download ? "?download=1" : ""}`;

  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return { kind: "unavailable" };
  }

  if (response.ok) {
    return {
      kind: "ok",
      html: await response.text(),
      contentDisposition: response.headers.get("content-disposition") ?? "inline",
    };
  }
  if (response.status === 404) return { kind: "not_found" };
  if (response.status === 401) return { kind: "unauthorized" };
  if (response.status === 503) return { kind: "unavailable" };
  return { kind: "error" };
}
