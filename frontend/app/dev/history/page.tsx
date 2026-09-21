import { notFound } from "next/navigation";

import { HistoryHarness } from "./harness";

/**
 * Design harness for the history rail and drawer. Not linked from anywhere
 * and a 404 in production; lets the sidebar be screenshotted and critiqued
 * without a signed-in session or a backend.
 */
export default function HistoryPreview() {
  if (process.env.NODE_ENV === "production") notFound();
  return <HistoryHarness />;
}
