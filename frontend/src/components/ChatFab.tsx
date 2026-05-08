import { useState } from "react";
import { RobotOutlined } from "@ant-design/icons";
import ChatPanel from "./ChatPanel";

interface ChatFabProps {
  market: string;
  data: any;
}

export default function ChatFab({ market, data }: ChatFabProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        style={{
          position: "fixed",
          right: 40,
          bottom: 40,
          width: 56,
          height: 56,
          borderRadius: "50%",
          background: "#494fdf",
          border: "none",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: "0 4px 20px rgba(73,79,223,0.4)",
          zIndex: 1000,
        }}
      >
        <RobotOutlined style={{ fontSize: 24, color: "#fff" }} />
      </button>
      <ChatPanel open={open} onClose={() => setOpen(false)} market={market} data={data} />
    </>
  );
}
