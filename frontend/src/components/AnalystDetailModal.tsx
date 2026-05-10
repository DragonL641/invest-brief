import { useTranslation } from "react-i18next";

const mono: React.CSSProperties = { fontFamily: "'Geist Mono', monospace" };

interface Upgrade {
  firm?: string;
  institution?: string;
  to_grade?: string;
  from_grade?: string;
  action?: string;
  grade?: string;
  change?: string;
  price_target?: number | null;
  date?: string;
}

interface Recommendations {
  strong_buy: number;
  buy: number;
  hold: number;
  sell: number;
  strong_sell: number;
}

interface AnalystDetailModalProps {
  targets: { low?: number; mean?: number; high?: number; median?: number };
  upsidePct: number | null | undefined;
  recommendations: Recommendations | null;
  upgrades: Upgrade[];
  onClose: () => void;
}

function fmt(n: number | undefined | null, decimals = 2): string {
  if (n == null) return "--";
  return n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export default function AnalystDetailModal({
  targets, upsidePct, recommendations, upgrades, onClose,
}: AnalystDetailModalProps) {
  const { t } = useTranslation();

  const rec = recommendations;
  const totalBuy = (rec?.strong_buy ?? 0) + (rec?.buy ?? 0);
  const totalHold = rec?.hold ?? 0;
  const totalSell = (rec?.strong_sell ?? 0) + (rec?.sell ?? 0);
  const total = totalBuy + totalHold + totalSell;
  const buyPct = total ? Math.round((totalBuy / total) * 100) : 0;
  const holdPct = total ? Math.round((totalHold / total) * 100) : 0;
  const sellPct = total ? 100 - buyPct - holdPct : 0;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 100, padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#1a1c1e", borderRadius: 16, padding: 24,
          maxWidth: 520, width: "100%", maxHeight: "80vh", overflow: "auto",
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: "#fff" }}>{t("stock.analystModal.title")}</span>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: "#8d969e", cursor: "pointer", fontSize: 18, padding: 4 }}
          >
            ✕
          </button>
        </div>

        {/* Target price */}
        {targets.mean != null && (
          <div style={{ display: "flex", gap: 24, marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.target")}</div>
              <div style={{ ...mono, fontSize: 20, fontWeight: 600, color: "#fff" }}>${fmt(targets.mean)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.upside")}</div>
              <div style={{
                ...mono, fontSize: 20, fontWeight: 600,
                color: (upsidePct ?? 0) >= 0 ? "#22c55e" : "#ef4444",
              }}>
                {upsidePct != null ? `${upsidePct >= 0 ? "+" : ""}${upsidePct.toFixed(2)}%` : "--"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.52wRange")}</div>
              <div style={{ ...mono, fontSize: 14, color: "#fff" }}>
                ${fmt(targets.low)} - ${fmt(targets.high)}
              </div>
            </div>
          </div>
        )}

        {/* Rating distribution */}
        {total > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
              {t("stock.analystModal.rating")}
            </div>
            <div style={{ display: "flex", gap: 2, height: 10, borderRadius: 5, overflow: "hidden", marginBottom: 8 }}>
              <div style={{ flex: buyPct, background: "#ef4444", borderRadius: 5 }} />
              <div style={{ flex: holdPct, background: "#494fdf", borderRadius: 5 }} />
              <div style={{ flex: sellPct, background: "#22c55e", borderRadius: 5 }} />
            </div>
            <div style={{ display: "flex", gap: 16 }}>
              <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.buy")} {totalBuy}({buyPct}%)</span>
              <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.hold")} {totalHold}({holdPct}%)</span>
              <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.sell")} {totalSell}({sellPct}%)</span>
            </div>
          </div>
        )}

        {/* Upgrades/downgrades table */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            {t("stock.analystModal.upgrades")}
          </div>
          {(() => {
            const realChanges = upgrades.filter(
              (u) => u.from_grade !== u.to_grade || u.action === "up" || u.action === "down" || u.action === "init"
            );
            return realChanges.length > 0 ? (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.12)" }}>
                    <th style={{ textAlign: "left", padding: "6px 8px", color: "#8d969e", fontWeight: 500 }}>{t("stock.analystModal.firm")}</th>
                    <th style={{ textAlign: "left", padding: "6px 8px", color: "#8d969e", fontWeight: 500 }}>{t("stock.analystModal.grade")}</th>
                    <th style={{ textAlign: "right", padding: "6px 8px", color: "#8d969e", fontWeight: 500 }}>{t("stock.analystModal.targetPrice")}</th>
                    <th style={{ textAlign: "right", padding: "6px 8px", color: "#8d969e", fontWeight: 500 }}>{t("stock.analystModal.date")}</th>
                  </tr>
                </thead>
                <tbody>
                  {realChanges.slice(0, 10).map((u, i) => {
                    const actionColor = u.action === "up" ? "#ef4444" : u.action === "down" ? "#22c55e" : "#494fdf";
                    return (
                      <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                        <td style={{ padding: "6px 8px", color: "#fff", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {u.firm || u.institution}
                        </td>
                        <td style={{ padding: "6px 8px", color: actionColor }}>
                          {u.from_grade && u.to_grade ? `${u.from_grade} → ${u.to_grade}` : u.change || u.grade || ""}
                        </td>
                        <td style={{ ...mono, padding: "6px 8px", textAlign: "right", color: "#fff" }}>
                          {u.price_target != null ? `$${fmt(u.price_target, 0)}` : "--"}
                        </td>
                        <td style={{ padding: "6px 8px", textAlign: "right", color: "#8d969e" }}>
                          {u.date || "--"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.analystModal.noData")}</span>
            );
          })()}
        </div>

        {/* Close button */}
        <div style={{ marginTop: 20, textAlign: "right" }}>
          <button
            onClick={onClose}
            style={{
              background: "rgba(255,255,255,0.1)", border: "none", color: "#fff",
              padding: "8px 20px", borderRadius: 8, cursor: "pointer", fontSize: 13,
            }}
          >
            {t("stock.analystModal.close")}
          </button>
        </div>
      </div>
    </div>
  );
}
