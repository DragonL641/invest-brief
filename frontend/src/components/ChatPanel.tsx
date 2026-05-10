import { useState, useRef, useEffect } from "react";
import { Input, Button, Dropdown } from "antd";
import { SendOutlined, HistoryOutlined, PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { MenuProps } from "antd";
import ReactMarkdown from "react-markdown";

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface Session {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}

interface ChatPanelProps {
  messages: Message[];
  onSend: (text: string) => Promise<void>;
  onClose: () => void;
  sessions: Session[];
  currentSessionId: string;
  onSwitchSession: (id: string) => void;
  onNewSession: () => void;
  onClearHistory: () => void;
}

function relativeTime(ts: number, t: TFunction): string {
  const diff = Date.now() - ts;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return t("chat.justNow");
  if (minutes < 60) return t("chat.minutesAgo", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("chat.hoursAgo", { count: hours });
  return t("chat.daysAgo", { count: Math.floor(hours / 24) });
}

export default function ChatPanel({
  messages,
  onSend,
  onClose,
  sessions,
  currentSessionId,
  onSwitchSession,
  onNewSession,
  onClearHistory,
}: ChatPanelProps) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);
    try {
      await onSend(text);
    } finally {
      setSending(false);
    }
  };

  const historyItems: MenuProps["items"] = [
    ...sessions
      .filter((s) => s.id !== currentSessionId)
      .slice(0, 10)
      .map((s) => ({
        key: s.id,
        label: (
          <div style={{ maxWidth: 200 }}>
            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</div>
            <div style={{ fontSize: 12, color: "#8d969e" }}>{relativeTime(s.updatedAt, t)}</div>
          </div>
        ),
        onClick: () => onSwitchSession(s.id),
      })),
    { type: "divider" as const },
    {
      key: "new",
      icon: <PlusOutlined />,
      label: t("chat.newConversation"),
      onClick: onNewSession,
    },
    {
      key: "clear",
      icon: <DeleteOutlined />,
      label: t("chat.clearHistory"),
      danger: true,
      onClick: onClearHistory,
    },
  ];

  return (
    <div
      style={{
        position: "fixed",
        right: 40,
        bottom: 120,
        width: 380,
        height: 500,
        background: "#000",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 12,
        display: "flex",
        flexDirection: "column",
        zIndex: 1000,
        boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
        overflow: "hidden",
        animation: "chatSlideUp 0.3s ease-out",
      }}
    >
      <style>{`
        @keyframes chatSlideUp {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* Title bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 16px",
          borderBottom: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 14 }}>{t("chat.title")}</span>
        <div style={{ display: "flex", gap: 8 }}>
          <Dropdown menu={{ items: historyItems }} trigger={["click"]} placement="bottomRight">
            <button
              style={{
                background: "none",
                border: "none",
                color: "#8d969e",
                cursor: "pointer",
                padding: 4,
                display: "flex",
                alignItems: "center",
              }}
            >
              <HistoryOutlined style={{ fontSize: 16 }} />
            </button>
          </Dropdown>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              color: "#8d969e",
              cursor: "pointer",
              padding: 4,
              display: "flex",
              alignItems: "center",
              fontSize: 16,
            }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* Message list */}
      <div
        ref={listRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: 16,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {messages.length === 0 && (
          <div style={{ textAlign: "center", color: "#8d969e", padding: "40px 0", fontSize: 13 }}>
            {t("chat.placeholder")}
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
            }}
          >
            <div
              style={{
                maxWidth: "80%",
                padding: "10px 14px",
                borderRadius: 12,
                fontSize: 14,
                lineHeight: 1.5,
                background: msg.role === "user" ? "#494fdf" : "#16181a",
                color: "#fff",
              }}
            >
              {msg.role === "assistant" ? (
                <ReactMarkdown
                  components={{
                    p: ({ children }) => <p style={{ margin: 0 }}>{children}</p>,
                    ul: ({ children }) => <ul style={{ margin: "4px 0", paddingLeft: 16 }}>{children}</ul>,
                    ol: ({ children }) => <ol style={{ margin: "4px 0", paddingLeft: 16 }}>{children}</ol>,
                    li: ({ children }) => <li style={{ margin: "2px 0" }}>{children}</li>,
                    strong: ({ children }) => <strong style={{ color: "#fff" }}>{children}</strong>,
                  }}
                >
                  {msg.content || "..."}
                </ReactMarkdown>
              ) : (
                msg.content || "..."
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Input area */}
      <div
        style={{
          padding: 16,
          borderTop: "1px solid rgba(255,255,255,0.08)",
          display: "flex",
          gap: 8,
        }}
      >
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("chat.placeholder")}
          autoSize={{ minRows: 1, maxRows: 4 }}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          style={{
            background: "#16181a",
            color: "#fff",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 12,
          }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          loading={sending}
          style={{
            borderRadius: 12,
            height: 40,
            width: 40,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        />
      </div>
    </div>
  );
}
