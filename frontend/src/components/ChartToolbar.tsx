import { useTranslation } from "react-i18next";

export type Period = "daily" | "weekly" | "monthly";
export type TimeRange = "1m" | "3m" | "6m" | "all";

interface ChartToolbarProps {
  period: Period;
  onPeriodChange: (p: Period) => void;
  range: TimeRange;
  onRangeChange: (r: TimeRange) => void;
  visibleMA: Set<number>;
  onToggleMA: (period: number) => void;
  showRSI: boolean;
  onToggleRSI: () => void;
  showMACD: boolean;
  onToggleMACD: () => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
}

const MA_CONFIG = [
  { period: 5, color: "#f59e0b" },
  { period: 10, color: "#3b82f6" },
  { period: 20, color: "#a855f7" },
];

const pill: React.CSSProperties = {
  padding: "3px 10px",
  borderRadius: 6,
  fontSize: 11,
  fontWeight: 600,
  cursor: "pointer",
  border: "none",
  outline: "none",
  transition: "background 0.15s",
};

function Pill({
  label,
  active,
  color,
  style,
  onClick,
}: {
  label: string;
  active: boolean;
  color?: string;
  style?: React.CSSProperties;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        ...pill,
        background: active
          ? color || "rgba(73,79,223,0.9)"
          : "rgba(255,255,255,0.06)",
        color: active ? "#fff" : "rgba(255,255,255,0.45)",
        ...(active && color ? { color } : {}),
        ...style,
      }}
    >
      {label}
    </button>
  );
}

export default function ChartToolbar({
  period,
  onPeriodChange,
  range,
  onRangeChange,
  visibleMA,
  onToggleMA,
  showRSI,
  onToggleRSI,
  showMACD,
  onToggleMACD,
  isFullscreen,
  onToggleFullscreen,
}: ChartToolbarProps) {
  const { t } = useTranslation();

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        flexWrap: "wrap",
        padding: "6px 8px",
      }}
    >
      {(["daily", "weekly", "monthly"] as Period[]).map((p) => (
        <Pill
          key={p}
          label={t(`chart.${p}`)}
          active={period === p}
          onClick={() => onPeriodChange(p)}
        />
      ))}

      <span style={{ width: 8 }} />

      {(["1m", "3m", "6m", "all"] as TimeRange[]).map((r) => (
        <Pill
          key={r}
          label={t(`chart.${r}`)}
          active={range === r}
          onClick={() => onRangeChange(r)}
        />
      ))}

      <span style={{ width: 8 }} />

      {MA_CONFIG.map(({ period: ma, color }) => (
        <Pill
          key={ma}
          label={`MA${ma}`}
          active={visibleMA.has(ma)}
          color={color}
          onClick={() => onToggleMA(ma)}
          style={{
            ...pill,
            background: visibleMA.has(ma)
              ? `${color}33`
              : "rgba(255,255,255,0.06)",
            color: visibleMA.has(ma) ? color : "rgba(255,255,255,0.3)",
            textDecoration: visibleMA.has(ma) ? "none" : "line-through",
          }}
        />
      ))}

      <span style={{ width: 8 }} />

      <Pill label="RSI" active={showRSI} onClick={onToggleRSI} />
      <Pill label="MACD" active={showMACD} onClick={onToggleMACD} />

      <div style={{ flex: 1 }} />

      <button
        type="button"
        onClick={onToggleFullscreen}
        style={{
          ...pill,
          background: "rgba(255,255,255,0.06)",
          color: "rgba(255,255,255,0.5)",
          fontSize: 14,
          lineHeight: 1,
        }}
        title={isFullscreen ? t("chart.exitFullscreen") : t("chart.fullscreen")}
      >
        {isFullscreen ? "✕" : "⛶"}
      </button>
    </div>
  );
}
