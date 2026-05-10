import { useTranslation } from "react-i18next";
import { Dropdown, App } from "antd";
import { StockOutlined, ReloadOutlined, LoadingOutlined, SendOutlined, SettingOutlined, LogoutOutlined } from "@ant-design/icons";
import { useAuth } from "../hooks/useAuth";
import { logout } from "../api/auth";
import { sendEmail } from "../api/email";

interface HeaderProps {
  market: "us" | "cn";
  onMarketChange: (m: "us" | "cn") => void;
  onRefresh: () => void;
  refreshing?: boolean;
  updatedAt?: string;
  onOpenPreferences?: () => void;
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

export default function Header({ market, onMarketChange, onRefresh, refreshing, updatedAt, onOpenPreferences }: HeaderProps) {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { message } = App.useApp();

  const handleSendEmail = () => {
    sendEmail()
      .then((r) => {
        const d = r.data;
        if (d.status === "started") message.success(t("avatar.sendEmail.started"));
        else if (d.status === "rate_limited") message.warning(t("avatar.sendEmail.rateLimited"));
        else if (d.status === "error") message.error(d.message || t("avatar.sendEmail.error"));
        else if (d.status === "skipped") message.info(t("avatar.sendEmail.skipped"));
      })
      .catch(() => message.error(t("avatar.sendEmail.error")));
  };

  const handleLogout = () => {
    logout().finally(() => {
      localStorage.removeItem("token");
      window.location.href = "/login";
    });
  };

  const avatarInitial = user?.name?.charAt(0) || "?";

  const menuItems = [
    {
      key: "info",
      label: (
        <div style={{ padding: "4px 0" }}>
          <div style={{ fontWeight: 600, color: "#fff" }}>{user?.name || ""}</div>
          <div style={{ fontSize: 12, color: "#8d969e" }}>{user?.email || ""}</div>
        </div>
      ),
      disabled: true,
    },
    { type: "divider" as const },
    { key: "email", icon: <SendOutlined />, label: t("avatar.sendEmail"), onClick: handleSendEmail },
    { key: "preferences", icon: <SettingOutlined />, label: t("avatar.preferences"), onClick: onOpenPreferences },
    { type: "divider" as const },
    { key: "logout", icon: <LogoutOutlined />, label: t("avatar.logout"), onClick: handleLogout },
  ];

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
            cursor: refreshing ? "not-allowed" : "pointer",
            opacity: refreshing ? 0.7 : 1,
            pointerEvents: refreshing ? "none" : "auto",
            transition: "opacity 0.2s",
          }}
          onClick={onRefresh}
        >
          {refreshing ? (
            <LoadingOutlined style={{ fontSize: 13 }} />
          ) : (
            <ReloadOutlined style={{ fontSize: 13 }} />
          )}
          {refreshing ? t("refreshing") : t("refresh")}
        </button>

        {/* Last update */}
        {updatedAt && (
          <span style={{ color: "#8d969e", fontSize: 12 }}>
            {t("refresh.lastUpdate", { time: updatedAt })}
          </span>
        )}

        {/* Avatar Dropdown */}
        <Dropdown menu={{ items: menuItems }} trigger={["click"]} placement="bottomRight">
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
              cursor: "pointer",
            }}
          >
            {avatarInitial}
          </div>
        </Dropdown>
      </div>
    </header>
  );
}
