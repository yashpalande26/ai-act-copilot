/**
 * What the copilot says when it has nothing to answer. Shown both for a
 * scope notice (greeting or empty input, answered before any paid call) and
 * for a retrieval refusal (the provisions did not answer). Deterministic UI
 * copy; the refusal logic itself is unchanged.
 */
export const SCOPE_TITLE = "Ask me about the EU AI Act";
export const REFUSAL_TITLE = "The copilot declined to answer";

export const REFUSAL_LEAD =
  "The retrieved provisions did not contain enough to answer that, so it stopped rather than guessing.";

export const SCOPE_MESSAGE =
  "I answer questions about the EU AI Act: obligations, prohibited practices, and whether a system is high-risk, with every answer cited to the consolidated text. I am not a general chatbot, so questions you would put to a search engine or a general assistant will get this note rather than a guess.";

export const SCOPE_EXAMPLES = [
  "What obligations apply to providers of high-risk AI systems?",
  "Is an AI system used for credit scoring high-risk?",
  "Which AI practices are prohibited outright?",
];
