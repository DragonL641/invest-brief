import React, { useState, useCallback, useRef, useMemo } from "react";
import { RobotOutlined, CloseOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import ChatPanel from "./ChatPanel";
import type { Message, Session } from "./ChatPanel";
import { streamChat } from "../api/chat";

const STORAGE_KEY = "chat_sessions";
const MAX_SESSIONS = 20;
const SESSION_TTL = 24 * 60 * 60 * 1000;

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const sessions: Session[] = JSON.parse(raw);
    const now = Date.now();
    const valid = sessions.filter((s) => now - s.updatedAt < SESSION_TTL);
    if (valid.length !== sessions.length) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(valid));
    }
    return valid;
  } catch {
    return [];
  }
}

function saveSessions(sessions: Session[]) {
  const trimmed = sessions.slice(-MAX_SESSIONS);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
}

interface ChatWidgetProps {
  market: string;
  data?: unknown;
}

function ChatWidget({ market }: ChatWidgetProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<Session[]>(loadSessions);
  const [currentId, setCurrentId] = useState<string>(() => {
    const stored = loadSessions();
    return stored.length > 0 ? stored[stored.length - 1].id : generateId();
  });
  const streamingRef = useRef<Message | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestSessionsRef = useRef<Session[]>(sessions);
  latestSessionsRef.current = sessions;

  const currentSession = sessions.find((s) => s.id === currentId);
  const messages = useMemo(() => currentSession?.messages || [], [currentSession]);

  // Cleanup expired sessions - initial state already loaded via useState(loadSessions)

  const flushToStorage = useCallback(() => {
    saveSessions(latestSessionsRef.current);
  }, []);

  const updateSession = useCallback((id: string, patch: Partial<Session>, immediate = false) => {
    setSessions((prev) => {
      const idx = prev.findIndex((s) => s.id === id);
      const updated = [...prev];
      if (idx >= 0) {
        updated[idx] = { ...updated[idx], ...patch, updatedAt: Date.now() };
      } else {
        updated.push({
          id,
          title: "",
          messages: [],
          updatedAt: Date.now(),
          ...patch,
        });
      }
      latestSessionsRef.current = updated;

      if (immediate) {
        if (debounceTimerRef.current) {
          clearTimeout(debounceTimerRef.current);
          debounceTimerRef.current = null;
        }
        saveSessions(updated);
      } else {
        if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = setTimeout(flushToStorage, 500);
      }

      return updated;
    });
  }, [flushToStorage]);

  const handleSend = useCallback(
    async (text: string) => {
      const userMsg: Message = { role: "user", content: text };
      const aiMsg: Message = { role: "assistant", content: "" };
      const newMessages = [...messages, userMsg, aiMsg];
      const title = messages.length === 0 ? text.slice(0, 20) : currentSession?.title || text.slice(0, 20);

      updateSession(currentId, { messages: newMessages, title }, true);

      streamingRef.current = aiMsg;
      try {
        for await (const chunk of streamChat(text, market)) {
          streamingRef.current.content += chunk;
          updateSession(currentId, {
            messages: [...newMessages.slice(0, -1), { ...streamingRef.current }],
            title,
          });
        }
        // Flush final state immediately after streaming ends
        updateSession(currentId, {
          messages: [...newMessages.slice(0, -1), { ...streamingRef.current }],
          title,
        }, true);
      } catch {
        streamingRef.current.content += "\n" + t("chat.requestFailed");
        updateSession(currentId, {
          messages: [...newMessages.slice(0, -1), { ...streamingRef.current }],
          title,
        }, true);
      }
    },
    [currentId, messages, currentSession, market, updateSession, t]
  );

  const handleNewSession = useCallback(() => {
    const newId = generateId();
    setCurrentId(newId);
  }, []);

  const handleSwitchSession = useCallback((id: string) => {
    setCurrentId(id);
  }, []);

  const handleClearHistory = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setSessions([]);
    setCurrentId(generateId());
  }, []);

  return (
    <>
      {/* FAB button */}
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          position: "fixed",
          right: 40,
          bottom: 40,
          width: 56,
          height: 56,
          borderRadius: "50%",
          background: open ? "#1a1a1a" : "#494fdf",
          border: open ? "1px solid rgba(255,255,255,0.12)" : "none",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: open ? "none" : "0 4px 20px rgba(73,79,223,0.4)",
          zIndex: 1001,
          transition: "all 0.2s ease",
        }}
      >
        {open ? (
          <CloseOutlined style={{ fontSize: 22, color: "#fff" }} />
        ) : (
          <RobotOutlined style={{ fontSize: 24, color: "#fff" }} />
        )}
      </button>

      {/* Floating chat panel */}
      {open && (
        <ChatPanel
          messages={messages}
          onSend={handleSend}
          onClose={() => setOpen(false)}
          sessions={sessions}
          currentSessionId={currentId}
          onSwitchSession={handleSwitchSession}
          onNewSession={handleNewSession}
          onClearHistory={handleClearHistory}
        />
      )}
    </>
  );
}

export default React.memo(ChatWidget);
