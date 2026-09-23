import { notFound } from "next/navigation";

import { ChatTurnsHarness, type ThreadName } from "./harness";

const THREADS: ThreadName[] = ["short", "lanes", "long", "grounded", "empty", "loading"];

/**
 * Design harness for the chat panel as a whole: every kind of assistant turn
 * the backend can return, inside the real app shell with a sample history
 * rail, so the CTA rule, the citation scope and the panel layout can be
 * screenshotted without a signed-in session or a paid call. Not linked from
 * anywhere and a 404 in production.
 *   ?thread=short     one exchange (the layout bug's trigger: few messages)
 *   ?thread=lanes     one turn of each kind (CTA rule)
 *   ?thread=long      enough turns to scroll
 *   ?thread=grounded  a realistic served context of sixteen passages, two cited
 *   ?thread=empty     the empty state with starters
 *   ?thread=loading   a past chat being fetched (panel and rail skeletons)
 */
export default async function ChatTurnsPreview({
  searchParams,
}: {
  searchParams: Promise<{ thread?: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { thread } = await searchParams;
  const name = THREADS.find((t) => t === thread) ?? "short";
  return <ChatTurnsHarness thread={name} />;
}
