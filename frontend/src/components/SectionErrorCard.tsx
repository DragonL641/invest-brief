import { useTranslation } from "react-i18next";
import { WarningFilled, ReloadOutlined, LoadingOutlined } from "@ant-design/icons";
import type { SectionError } from "../types/section";

interface Props {
  error: SectionError;
  onRetry: () => void;
  loading?: boolean;
}

export default function SectionErrorCard({ error, onRetry, loading }: Props) {
  const { t } = useTranslation();

  return (
    <div
      style={{
        background: "#111214",
        borderRadius: 16,
        padding: "32px 24px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
      }}
    >
      <WarningFilled style={{ fontSize: 24, color: "#ff4d4f" }} />
      <div style={{ color: "#8d969e", fontSize: 14, textAlign: "center" }}>
        {t(`error.suggestion.${error.reason}`, t("error.solutionUnknown"))}
      </div>
      {error.retryable && (
        <button
          onClick={onRetry}
          disabled={loading}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "rgba(255,255,255,0.08)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 8,
            padding: "6px 16px",
            color: "#fff",
            fontSize: 13,
            cursor: loading ? "not-allowed" : "pointer",
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? <LoadingOutlined /> : <ReloadOutlined />}
          {t("error.retry")}
        </button>
      )}
    </div>
  );
}
