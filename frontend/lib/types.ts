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

export type ChatTurn =
  | { role: "user"; id: string; question: string }
  | { role: "assistant"; id: string; result: AskResult }
  | {
      role: "error";
      id: string;
      kind: "rate_limited_daily" | "rate_limited_burst" | "unavailable" | "generic";
      message: string;
    };
