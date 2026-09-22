"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { AppShell } from "@/components/app/app-shell";
import { ChatPanel } from "@/components/chat/chat-panel";
import { HistoryList } from "@/components/chat/history-sidebar";
import { useChatSession, useSessions } from "@/components/chat/use-chat-session";

/**
 * The signed-in workspace: the app shell with the chat history as its rail,
 * and the conversation as the content. Owns nothing itself; state lives in
 * useChatSession, data in useSessions. The current session id is mirrored to
 * `?s=` so a reload reopens the same thread. That parameter is only a hint
 * about which session to fetch: the fetch is ownership-checked server-side,
 * so a foreign id simply fails to load.
 */
export function ChatShell({
  userName,
  isAdmin,
  account,
  accountCompact,
}: {
  userName: string;
  isAdmin: boolean;
  account: ReactNode;
  accountCompact: ReactNode;
}) {
  const params = useSearchParams();
  const router = useRouter();
  const chat = useChatSession(params.get("s") ?? undefined);
  const history = useSessions(chat.historyVersion);

  useEffect(() => {
    const target = chat.sessionId ? `/app?s=${encodeURIComponent(chat.sessionId)}` : "/app";
    if (`${window.location.pathname}${window.location.search}` !== target) {
      router.replace(target, { scroll: false });
    }
  }, [chat.sessionId, router]);

  const rail = (
    <HistoryList
      sessions={history.sessions}
      loading={history.loading}
      error={history.error}
      currentId={chat.sessionId}
      onSelect={(id) => {
        if (id !== chat.sessionId) void chat.openSession(id);
      }}
      onNew={chat.startNewChat}
    />
  );

  return (
    <AppShell
      isAdmin={isAdmin}
      account={account}
      accountCompact={accountCompact}
      rail={rail}
      title="Ask the copilot"
      scroll="none"
    >
      <ChatPanel
        userName={userName}
        turns={chat.turns}
        pending={chat.pending}
        loading={chat.loading}
        loadError={chat.loadError}
        onSubmit={chat.submit}
      />
    </AppShell>
  );
}
