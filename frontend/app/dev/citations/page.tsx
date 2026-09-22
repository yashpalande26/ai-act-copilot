import { notFound } from "next/navigation";

import { AssistantTurn, UserTurn } from "@/components/chat/answer-turn";
import type { ChatTurn } from "@/lib/types";

import citations from "./art16.json";

/**
 * Design harness for the answer turn. Not linked from anywhere and a 404 in
 * production; it exists so the chat components can be screenshotted and
 * critiqued without a signed-in session or a paid backend call.
 *
 * The fixture is real: the twelve Article 16 points, quoted from the live
 * corpus (chunk_text, verbatim), with the answer sentence the landing page
 * already shows for the same question.
 */
export default function CitationsPreview() {
  if (process.env.NODE_ENV === "production") notFound();

  const question = "What obligations apply to providers of high-risk AI systems?";
  const answer: ChatTurn = {
    role: "assistant",
    id: "preview-answer",
    result: {
      answer:
        "Providers must ensure their high-risk AI systems comply with the requirements of Section 2, put a quality management system in place, and draw up technical documentation before the system is placed on the market.",
      citations,
      abstained: false,
      session_id: "preview",
    },
  };
  const abstention: ChatTurn = {
    role: "assistant",
    id: "preview-abstention",
    result: { answer: "", citations: [], abstained: true, session_id: "preview" },
  };
  const scope: ChatTurn = {
    role: "assistant",
    id: "preview-scope",
    result: { answer: "", citations: [], abstained: true, session_id: null, scope_notice: true },
  };
  const systemQuestion = "we use AI to screen CVs for hiring, is that allowed?";
  const systemAnswer: ChatTurn = {
    role: "assistant",
    id: "preview-system",
    result: {
      answer:
        "AI systems intended to be used for the recruitment or selection of natural persons, including to analyse and filter job applications, are listed as high-risk AI systems in Annex III, point 4(a). Whether a specific system falls within that point depends on its intended purpose: whether it is used for recruitment or selection, such as screening applications.",
      citations: [
        {
          citation_id: "anx_III.pt_4.sub_a",
          citation_label: "Annex III, point 4(a)",
          quoted_text:
            "AI systems intended to be used for the recruitment or selection of natural persons, in particular to place targeted job advertisements, to analyse and filter job applications, and to evaluate candidates;",
        },
      ],
      abstained: false,
      session_id: "preview",
      system_description: true,
    },
  };
  const social: ChatTurn = {
    role: "assistant",
    id: "preview-social",
    result: {
      answer:
        "Nice to meet you, Ana. I answer questions about the EU AI Act from its consolidated text, with every answer cited to the provision it comes from, and I can say what the Act says about a type of AI system. For whether your own system is in scope, the assessment gives a classification from your description and a short questionnaire.",
      citations: [],
      abstained: false,
      session_id: "preview",
      social: true,
    },
  };
  const clarifying: ChatTurn = {
    role: "assistant",
    id: "preview-clarifying",
    result: {
      answer:
        "What does the system actually do? For example, does it rank job applicants, decide on a loan, flag suspicious payments, or answer customer questions?",
      citations: [],
      abstained: false,
      session_id: "preview",
      clarifying: true,
      system_description: true,
    },
  };
  const error: ChatTurn = {
    role: "error",
    id: "preview-error",
    kind: "rate_limited_daily",
    message: "You have reached today's question limit. It resets at midnight UTC.",
  };

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-10">
      <p className="type-eyebrow text-ink-faint mb-8">Preview harness, not a product page</p>
      <div className="space-y-8">
        <UserTurn question={question} />
        <AssistantTurn turn={answer} question={question} />
        <AssistantTurn turn={abstention} question={question} />
        <UserTurn question="hey" />
        <AssistantTurn turn={scope} question="hey" />
        <UserTurn question={systemQuestion} />
        <AssistantTurn turn={systemAnswer} question={systemQuestion} />
        <UserTurn question="my name is Ana" />
        <AssistantTurn turn={social} question="my name is Ana" />
        <UserTurn question="we have an AI model in our company, is it a problem?" />
        <AssistantTurn turn={clarifying} question="we have an AI model in our company, is it a problem?" />
        <AssistantTurn turn={error} question={question} />
      </div>
    </main>
  );
}
