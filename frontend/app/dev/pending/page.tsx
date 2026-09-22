import { notFound } from "next/navigation";

import { PendingHarness } from "./harness";

/**
 * Design harness for the in-flight turn indicator. Not linked from anywhere
 * and a 404 in production. ?phase=bar|early|late picks the phase without
 * waiting; the Resolve button swaps the pending turn for an answer so the
 * clearing behaviour can be probed.
 */
export default async function PendingPreview({
  searchParams,
}: {
  searchParams: Promise<{ phase?: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { phase } = await searchParams;
  return <PendingHarness phase={phase === "late" ? "late" : phase === "bar" ? "bar" : "early"} />;
}
