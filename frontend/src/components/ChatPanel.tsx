import { useState, useRef, useEffect } from "react";
import { Drawer, Input, Button } from "antd";
import { SendOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { streamChat } from "../api/chat";

interface ChatPanelProps {
  open: boolean;
  onClose: () => void;
  market: string;
  data: any;
}

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function ChatPanel({ open, onClose, market }: ChatPanelProps) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<Message[]>([]);
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

    const userMsg: Message = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);

    const aiMsg: Message = { role: "assistant", content: "" };
    setMessages((prev) => [...prev, aiMsg]);

    try {
      for await (const chunk of streamChat(text, market)) {
        aiMsg.content += chunk;
        setMessages((prev) => [...prev.slice(0, -1), { ...aiMsg }]);
      }
    } catch {
      aiMsg.content += "\n[请求失败，请重试]";
      setMessages((prev) => [...prev.slice(0, -1), { ...aiMsg }]);
    } finally {
      setSending(false);
    }
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="AI 助手"
      styles={{
        header: { background: "#000", borderBottom: "1px solid rgba(255,255,255,0.08)" },
        body: { background: "#000", display: "flex", flexDirection: "column", padding: 0 },
        wrapper: {},
        mask: { background: "rgba(0,0,0,0.5)" },
      }}
    >
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
              {msg.content || "..."}
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
          style={{ borderRadius: 12, height: 40, width: 40, display: "flex", alignItems: "center", justifyContent: "center" }}
        />
      </div>
    </Drawer>
  );
}
