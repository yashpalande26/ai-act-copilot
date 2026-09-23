import { notFound } from "next/navigation";

import { ChatTurnsHarness } from "./harness";

/**
 * Design harness for the chat panel as a whole: every kind of assistant turn
 * the backend can return, inside the real app shell, so the CTA rule and the
 * panel layout can be screenshotted without a signed-in session or a paid
 * call. Not linked from anywhere and a 404 in production.
 *   ?thread=short   one exchange (the layout bug's trigger: few messages)
 *   ?thread=lanes   one turn of each kind (CTA rule)
 *   ?thread=long    enough turns to scroll
 */
export default async function ChatTurnsPreview({
  searchParams,
}: {
  searchParams: Promise<{ thread?: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { thread } = await searchParams;
  return <ChatTurnsHarness thread={thread === "lanes" ? "lanes" : thread === "long" ? "long" : "short"} />;
}
