"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ChatTurn, SessionDetail, SessionSummary } from "@/lib/types";

const MAX_CHARS = 2000;

let turnCounter = 0;
const nextId = () => `turn-${++turnCounter}`;

/** Server rows -> the turn shapes the answer components already render. */
export function turnsFromSession(detail: SessionDetail): ChatTurn[] {
  return detail.messages.map((m) =>
    m.role === "user"
      ? { role: "user", id: m.id, question: m.content }
      : {
          role: "assistant",
          id: m.id,
          result: {
            answer: m.content,
            citations: m.citations,
            abstained: m.abstained,
            session_id: detail.id,
          },
        },
  );
}

type Fetched =
  | { ok: true; detail: SessionDetail }
  | { ok: false; message: string };

/** GET one session through the BFF. Pure I/O, no state. */
async function fetchSession(id: string): Promise<Fetched> {
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return {
        ok: false,
        message:
          response.status === 404
            ? "That chat could not be found."
            : "That chat could not be loaded right now.",
      };
    }
    return { ok: true, detail: (await response.json()) as SessionDetail };
  } catch {
    return { ok: false, message: "That chat could not be loaded right now." };
  }
}

/**
 * All conversation state in one place: the current thread, the session it
 * belongs to, and the two ways a thread changes hands (reopen, new chat).
 * Bumps `historyVersion` whenever the server-side list may have changed, so
 * the sidebar refetches only then.
 */
export function useChatSession(initialSessionId?: string) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(initialSessionId);
  const [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(Boolean(initialSessionId));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  // Guards against a slow reopen landing after the user moved on.
  const openToken = useRef(0);

  const apply = useCallback((fetched: Fetched) => {
    if (fetched.ok) {
      setTurns(turnsFromSession(fetched.detail));
      setSessionId(fetched.detail.id);
      setLoadError(null);
    } else {
      setTurns([]);
      setSessionId(undefined);
      setLoadError(fetched.message);
    }
    setLoading(false);
  }, []);

  const openSession = useCallback(
    async (id: string) => {
      const token = ++openToken.current;
      setLoading(true);
      setLoadError(null);
      const fetched = await fetchSession(id);
      if (token === openToken.current) apply(fetched);
    },
    [apply],
  );

  const startNewChat = useCallback(() => {
    openToken.current++;
    setTurns([]);
    setSessionId(undefined);
    setLoading(false);
    setLoadError(null);
  }, []);

  // First render only: reopen the session named in the URL. State is set in
  // the fetch callback, never synchronously in the effect body.
  useEffect(() => {
    if (!initialSessionId) return;
    const token = ++openToken.current;
    void fetchSession(initialSessionId).then((fetched) => {
      if (token === openToken.current) apply(fetched);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = useCallback(
    async (raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed || pending || trimmed.length > MAX_CHARS) return;

      setTurns((t) => [...t, { role: "user", id: nextId(), question: trimmed }]);
      setPending(true);

      try {
        const response = await fetch("/api/ask", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ question: trimmed, sessionId }),
        });
        const body = await response.json();

        if (response.ok) {
          // Carry the session id forward so the backend threads the conversation.
          // A scope notice (greeting, empty input) carries none: nothing was
          // created, so the current thread, if any, stays as it is.
          if (body.session_id) setSessionId(body.session_id);
          setTurns((t) => [...t, { role: "assistant", id: nextId(), result: body }]);
          if (!body.scope_notice) setHistoryVersion((v) => v + 1);
        } else {
          const kind =
            response.status === 429
              ? body?.scope === "daily"
                ? ("rate_limited_daily" as const)
                : ("rate_limited_burst" as const)
              : response.status === 503
                ? ("unavailable" as const)
                : ("generic" as const);
          setTurns((t) => [
            ...t,
            { role: "error", id: nextId(), kind, message: body?.message ?? "Please try again." },
          ]);
        }
      } catch {
        setTurns((t) => [
          ...t,
          {
            role: "error",
            id: nextId(),
            kind: "unavailable",
            message: "We couldn't reach the copilot. Check your connection and try again.",
          },
        ]);
      } finally {
        setPending(false);
      }
    },
    [pending, sessionId],
  );

  /** Deletes a chat; resolves true when it is gone (a 404 counts: it is gone).
   *  Clears the thread if it was the open one, then refetches the list. */
  const deleteSession = useCallback(
    async (id: string) => {
      let ok = false;
      try {
        const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
        ok = r.ok || r.status === 404;
      } catch {
        ok = false;
      }
      if (ok) {
        if (id === sessionId) startNewChat();
        setHistoryVersion((v) => v + 1);
      }
      return ok;
    },
    [sessionId, startNewChat],
  );

  return {
    turns,
    sessionId,
    pending,
    loading,
    loadError,
    historyVersion,
    submit,
    openSession,
    startNewChat,
    deleteSession,
  };
}

/** The sidebar's data: refetched whenever `version` changes. */
export function useSessions(version: number) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/sessions", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const body = (await r.json()) as { sessions: SessionSummary[] };
        if (!cancelled) {
          setSessions(body.sessions);
          setError(false);
        }
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [version]);

  return { sessions, loading, error };
}
