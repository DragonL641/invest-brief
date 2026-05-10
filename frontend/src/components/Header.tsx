import { useTranslation } from "react-i18next";
import { Dropdown, App } from "antd";
import { StockOutlined, ReloadOutlined, LoadingOutlined, SendOutlined, SettingOutlined, LogoutOutlined, DownOutlined } from "@ant-design/icons";
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

  const marketMenuItems = [
    { key: "us", label: t("tab.us") },
    { key: "cn", label: t("tab.cn") },
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
        position: "sticky",
        top: 0,
        zIndex: 200,
      }}
    >
      {/* Left: Logo + Market dropdown */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <StockOutlined style={{ fontSize: 20, color: "#494fdf" }} />
          <span style={{ color: "#fff", fontSize: 18, fontWeight: 700, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
            {t("app.title")}
          </span>
        </div>
        <Dropdown
          menu={{ items: marketMenuItems, onClick: (e) => onMarketChange(e.key as "us" | "cn"), selectedKeys: [market] }}
          trigger={["click"]}
        >
          <button
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              background: "rgba(255,255,255,0.06)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 8,
              padding: "5px 12px",
              color: "#fff",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            {market === "us" ? t("tab.us") : t("tab.cn")}
            <DownOutlined style={{ fontSize: 10, color: "#8d969e" }} />
          </button>
        </Dropdown>
      </div>

      {/* Right */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {/* Language switch */}
        <div
          style={{
            display: "flex",
            background: "rgba(255,255,255,0.06)",
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
            background: "rgba(255,255,255,0.06)",
            border: "none",
            borderRadius: 9999,
            padding: "5px 14px",
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
              fontSize: 13,
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
