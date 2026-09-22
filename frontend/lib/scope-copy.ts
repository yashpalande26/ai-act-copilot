/**
 * What the copilot says when it has nothing to answer. Two different
 * situations, two different copies (22 Sep 2026):
 *   scope notice    a greeting or empty input, answered before any paid call:
 *                   what the copilot is for, what it is not, examples.
 *   refusal         an on-topic question whose retrieved provisions did not
 *                   answer it: neutral wording that never frames the question
 *                   as misuse, and a nudge towards something the text can
 *                   answer. A real legal question that did not retrieve is
 *                   not a search-engine question.
 * Deterministic UI copy; when the copilot abstains is unchanged.
 */
export const SCOPE_TITLE = "Ask me about the EU AI Act";
export const REFUSAL_TITLE = "The copilot declined to answer";

export const REFUSAL_LEAD =
  "The retrieved provisions did not contain enough to answer that, so it stopped rather than guessing.";

export const REFUSAL_MESSAGE =
  "Naming a specific article, obligation, or system type usually retrieves better, and an assessment covers a system end to end.";

export const SCOPE_MESSAGE =
  "I answer questions about the EU AI Act: obligations, prohibited practices, and whether a system is high-risk, with every answer cited to the consolidated text. I am not a general chatbot, so questions you would put to a search engine or a general assistant will get this note rather than a guess.";

export const SCOPE_EXAMPLES = [
  "What obligations apply to providers of high-risk AI systems?",
  "Is an AI system used for credit scoring high-risk?",
  "Which AI practices are prohibited outright?",
];
