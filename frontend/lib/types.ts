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

// --- assessment wedge (mirrors app/assessment/schema.py) ------------------

export type ProvisionText = {
  citation_id: string;
  citation_label: string;
  text: string;
  children: ProvisionText[];
};

export type QuestionKind = "boolean" | "select" | "multiselect" | "number";

export type QuestionOption = {
  value: string;
  label: string;
  basis: ProvisionText | null;
};

export type Question = {
  id: string;
  kind: QuestionKind;
  label: string;
  help: string | null;
  basis: ProvisionText[];
  options: QuestionOption[];
  show_if: { field: string; equals: unknown; any_of: string[] | null } | null;
};

export type QuestionnaireDef = {
  corpus_version_id: number;
  corpus_consolidated_date: string;
  steps: { key: string; title: string; intro: string | null; questions: Question[] }[];
};

export type AnswerValue = boolean | string | string[] | number | null;
export type Answers = Record<string, AnswerValue>;

export type Headline =
  | "OUT_OF_SCOPE"
  | "PROHIBITED_FLAG"
  | "HIGH_RISK"
  | "HIGH_RISK_POSSIBLE"
  | "TRANSPARENCY"
  | "MINIMAL";

export type ObligationGroup = {
  key: string;
  title: string;
  role: string;
  provisions: ProvisionText[];
  applies_from: ProvisionText | null;
  commentary: string | null;
};

export type PenaltyLine = {
  paragraph: ProvisionText;
  applicable: boolean;
  eur_cap: number;
  pct_cap: number;
  rule: "higher" | "lower" | "eur_only";
  rule_basis: ProvisionText[];
  ceiling_eur: number | null;
  why: string;
};

export type AssessmentReport = {
  generated_at: string;
  corpus_version_id: number;
  corpus_consolidated_date: string;
  decision: {
    headline: Headline;
    in_scope: boolean;
    scope_exclusions: string[];
    open_source_exempt: boolean;
    roles: string[];
    treated_as_provider_basis: string[];
    prohibited_flags: string[];
    high_risk_basis: string | null;
    annex_iii_note: string | null;
    product_route: boolean;
    derogation_claimed: boolean;
    transparency: string[];
    gpai: string[];
  };
  headline_text: string;
  scope: ProvisionText[];
  role_definitions: ProvisionText[];
  treated_as_provider: ProvisionText[];
  prohibited_flags: { key: string; provision: ProvisionText }[];
  high_risk_basis: ProvisionText | null;
  derogation: ProvisionText[];
  product_route: ProvisionText[];
  obligations: ObligationGroup[];
  dates: ProvisionText[];
  penalties: { lines: PenaltyLine[]; factors: ProvisionText; commentary: string };
  commentary: string[];
};

/** Mirrors GET /assessments and GET /assessments/{id}. */
export type SavedAssessmentSummary = {
  id: string;
  created_at: string;
  headline: Headline;
  roles: string[];
  engine_version: string;
  corpus_consolidated_date: string;
  environment: string;
  high_risk_basis: string | null;
};

export type SavedAssessment = {
  id: string;
  created_at: string;
  engine_version: string;
  corpus_consolidated_date: string;
  environment: string;
  answers: Answers;
  report: AssessmentReport;
  known_limitation: string;
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
