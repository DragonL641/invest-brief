import { useState } from "react";

interface InfoTooltipProps {
  text: string;
}

export default function InfoTooltip({ text }: InfoTooltipProps) {
  const [show, setShow] = useState(false);

  return (
    <span
      style={{ position: "relative", display: "inline-flex", alignItems: "center", marginLeft: 4, cursor: "help" }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <span
        style={{
          width: 14,
          height: 14,
          borderRadius: "50%",
          border: "1px solid rgba(255,255,255,0.3)",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 10,
          color: "rgba(255,255,255,0.5)",
          flexShrink: 0,
        }}
      >
        i
      </span>
      {show && (
        <span
          style={{
            position: "absolute",
            bottom: "100%",
            left: "50%",
            transform: "translateX(-50%)",
            marginBottom: 6,
            background: "#2a2d30",
            color: "#e0e0e0",
            padding: "6px 10px",
            borderRadius: 6,
            fontSize: 11,
            lineHeight: 1.4,
            width: 200,
            whiteSpace: "normal",
            zIndex: 50,
            boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
            pointerEvents: "none",
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
