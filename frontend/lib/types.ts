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

export type ChatTurn =
  | { role: "user"; id: string; question: string }
  | { role: "assistant"; id: string; result: AskResult }
  | {
      role: "error";
      id: string;
      kind: "rate_limited_daily" | "rate_limited_burst" | "unavailable" | "generic";
      message: string;
    };
