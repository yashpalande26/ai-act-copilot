/** Shared client/server types. Mirrors the FastAPI /ask contract. */
export type AskCitation = {
  citation_id: string;
  citation_label: string;
  quoted_text: string;
};

export type AskResult = {
  answer: string;
  citations: AskCitation[];
  abstained: boolean;
  session_id: string;
};

/** Mirrors GET /sessions. */
export type SessionSummary = {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
};

/** Mirrors GET /sessions/{id}. */
export type SessionMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  abstained: boolean;
  created_at: string;
  citations: AskCitation[];
};

export type SessionDetail = {
  id: string;
  title: string;
  created_at: string;
  messages: SessionMessage[];
};

/** Mirrors GET /admin/traces (operator-only). */
export type TraceSummary = {
  id: string;
  created_at: string;
  environment: string;
  user_id: string;
  user_email: string;
  question: string;
  retrieval_config: string;
  abstained: boolean;
  model: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  retrieval_latency_ms: number;
  generation_latency_ms: number | null;
};

export type TraceRetrieval = {
  config: string;
  query_actor: string | null;
  factor: number | null;
  legacy: boolean;
};

export type TraceCandidate = {
  final_rank: number;
  citation_id: string;
  citation_label: string;
  chunk_id: number | null;
  chunk_preview: string | null;
  vector_rank: number | null;
  lexical_rank: number | null;
  rrf_score: number | null;
  similarity: number | null;
  used_in_context: boolean;
  actor: string | null;
  downweighted: boolean;
};

/** Mirrors GET /admin/traces/{id}. */
export type TraceDetail = TraceSummary & {
  retrieval: TraceRetrieval;
  answer: string;
  citations: { citation_id: string; citation_label: string }[];
  candidates: TraceCandidate[];
};

export type ChatTurn =
  | { role: "user"; id: string; question: string }
  | { role: "assistant"; id: string; result: AskResult }
  | {
      role: "error";
      id: string;
      kind: "rate_limited_daily" | "rate_limited_burst" | "unavailable" | "generic";
      message: string;
    };
