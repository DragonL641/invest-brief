import { useTranslation } from "react-i18next";
import { StockOutlined, ReloadOutlined, UserOutlined } from "@ant-design/icons";

interface HeaderProps {
  market: "us" | "cn";
  onMarketChange: (m: "us" | "cn") => void;
  updatedAt?: string;
}

const pillStyle = (active: boolean): React.CSSProperties => ({
  padding: "6px 20px",
  borderRadius: 9999,
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
  background: active ? "#494fdf" : "#16181a",
  color: "#fff",
  border: "none",
  outline: "none",
  transition: "background 0.2s",
});

const langPillStyle = (active: boolean): React.CSSProperties => ({
  padding: "4px 10px",
  borderRadius: 9999,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  background: active ? "#494fdf" : "transparent",
  color: "#fff",
  border: "none",
  outline: "none",
  transition: "background 0.2s",
});

export default function Header({ market, onMarketChange, updatedAt }: HeaderProps) {
  const { t, i18n } = useTranslation();

  return (
    <header
      style={{
        height: 64,
        padding: "0 40px",
        background: "#000",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}
    >
      {/* Left: Logo */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <StockOutlined style={{ fontSize: 22, color: "#494fdf" }} />
        <span style={{ color: "#fff", fontSize: 20, fontWeight: 600 }}>
          {t("app.title")}
        </span>
      </div>

      {/* Center: Market tabs */}
      <div style={{ display: "flex", gap: 8 }}>
        <button style={pillStyle(market === "us")} onClick={() => onMarketChange("us")}>
          {t("tab.us")}
        </button>
        <button style={pillStyle(market === "cn")} onClick={() => onMarketChange("cn")}>
          {t("tab.cn")}
        </button>
      </div>

      {/* Right */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        {/* Language switch */}
        <div
          style={{
            display: "flex",
            background: "#16181a",
            borderRadius: 9999,
            padding: 2,
          }}
        >
          <button style={langPillStyle(i18n.language === "zh-CN")} onClick={() => i18n.changeLanguage("zh-CN")}>
            中
          </button>
          <button style={langPillStyle(i18n.language === "ko-KR")} onClick={() => i18n.changeLanguage("ko-KR")}>
            한
          </button>
        </div>

        {/* Refresh */}
        <button
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "#16181a",
            border: "none",
            borderRadius: 9999,
            padding: "6px 16px",
            color: "#fff",
            fontSize: 13,
            cursor: "pointer",
          }}
          onClick={() => onMarketChange(market)}
        >
          <ReloadOutlined style={{ fontSize: 13 }} />
          {t("refresh")}
        </button>

        {/* Last update */}
        {updatedAt && (
          <span style={{ color: "#8d969e", fontSize: 12 }}>
            {t("refresh.lastUpdate", { time: updatedAt })}
          </span>
        )}

        {/* Avatar */}
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "#494fdf",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          <UserOutlined />
        </div>
      </div>
    </header>
  );
}
