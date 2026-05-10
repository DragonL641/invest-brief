import { useTranslation } from "react-i18next";

interface IndexData {
  name: string;
  point: number;
  change: number;
}

interface MarketOverviewProps {
  indices: IndexData[];
}

function formatChange(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

export default function MarketOverview({ indices }: MarketOverviewProps) {
  const { t } = useTranslation();

  if (!indices || indices.length === 0) return null;

  return (
    <section>
      <h2 style={{ color: "#fff", fontSize: 20, fontWeight: 600, margin: "0 0 16px 0" }}>
        {t("market.overview")}
      </h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 16 }}>
        {indices.map((idx) => {
          const isUp = idx.change > 0;
          const isDown = idx.change < 0;
          const changeColor = isUp ? "#ef4444" : isDown ? "#22c55e" : "#8d969e";
          return (
            <div
              key={idx.name}
              style={{
                background: "#16181a",
                borderRadius: 20,
                padding: 16,
                display: "flex",
                flexDirection: "column",
                gap: 8,
                minWidth: 180,
                flex: 1,
              }}
            >
              <span style={{ fontSize: 13, color: "#8d969e" }}>{idx.name}</span>
              <span
                style={{
                  fontSize: 24,
                  fontFamily: "'Geist Mono', monospace",
                  fontWeight: 600,
                  color: "#fff",
                }}
              >
                {idx.point.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span
                style={{
                  fontSize: 14,
                  fontFamily: "'Geist Mono', monospace",
                  fontWeight: 500,
                  color: changeColor,
                }}
              >
                {formatChange(idx.change)}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
