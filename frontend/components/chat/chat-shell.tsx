"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ChatPanel } from "@/components/chat/chat-panel";
import { HistoryDrawer, HistorySidebar } from "@/components/chat/history-sidebar";
import { useChatSession, useSessions } from "@/components/chat/use-chat-session";

/**
 * The signed-in workspace: history rail + conversation. Owns nothing itself;
 * state lives in useChatSession, data in useSessions. The current session id
 * is mirrored to `?s=` so a reload reopens the same thread. That parameter is
 * only a hint about which session to fetch: the fetch is ownership-checked
 * server-side, so a foreign id simply fails to load.
 */
export function ChatShell({ userName }: { userName: string }) {
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

  const historyProps = {
    sessions: history.sessions,
    loading: history.loading,
    error: history.error,
    currentId: chat.sessionId,
    onSelect: (id: string) => {
      if (id !== chat.sessionId) void chat.openSession(id);
    },
    onNew: chat.startNewChat,
  };

  return (
    <div className="flex min-h-0 flex-1">
      <HistorySidebar {...historyProps} className="hidden md:flex md:flex-col" />

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="border-hairline flex h-11 items-center border-b px-3 md:hidden">
          <HistoryDrawer {...historyProps} />
        </div>
        <ChatPanel
          userName={userName}
          turns={chat.turns}
          pending={chat.pending}
          loading={chat.loading}
          loadError={chat.loadError}
          onSubmit={chat.submit}
        />
      </div>
    </div>
  );
}
