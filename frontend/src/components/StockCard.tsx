import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import StockChart from "./StockChart";
import InfoTooltip from "./InfoTooltip";
import AnalystDetailModal from "./AnalystDetailModal";

interface StockCardProps {
  stock: any;
  market: string;
}

const mono: React.CSSProperties = { fontFamily: "'Geist Mono', monospace" };

function fmt(n: number | undefined | null, decimals = 2): string {
  if (n == null) return "--";
  return n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function pct(n: number | undefined | null): string {
  if (n == null) return "--";
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function changeColor(val: number): string {
  if (val > 0) return "#ef4444";
  if (val < 0) return "#22c55e";
  return "#8d969e";
}

function getBadges(stock: any, t: TFunction): { label: string; color: string }[] {
  const badges: { label: string; color: string }[] = [];
  const tech = stock.technicals;
  const rsi = tech?.rsi ?? tech?.rsi_14;

  if (rsi != null) {
    if (rsi > 70) badges.push({ label: t("badge.rsiOverbought"), color: "#e23b4a" });
    else if (rsi < 30) badges.push({ label: t("badge.rsiOversold"), color: "#00a87e" });
  }

  const macdHist = tech?.macd_hist;
  const macdLine = tech?.macd ?? tech?.macd_line;
  if (macdHist != null) {
    if (macdHist > 0 && macdLine != null && macdLine > 0) {
      badges.push({ label: t("badge.macdStrongBullish"), color: "#00a87e" });
    } else if (macdHist > 0) {
      badges.push({ label: t("badge.macdBullish"), color: "#00a87e" });
    } else if (macdLine != null && macdLine < 0) {
      badges.push({ label: t("badge.macdStrongBearish"), color: "#e23b4a" });
    } else {
      badges.push({ label: t("badge.macdBearish"), color: "#e23b4a" });
    }
  }

  const upsidePct = stock.upside_pct ?? stock.targets?.upside_pct;
  if (upsidePct != null && upsidePct > 30) {
    badges.push({ label: t("badge.upside30"), color: "#494fdf" });
  }

  if (stock.insider_trades && stock.insider_trades.length > 0) {
    badges.push({ label: t("badge.insiderBuy"), color: "#22c55e" });
  }

  if (stock.earnings_approaching) {
    badges.push({ label: t("badge.earningsNear"), color: "#ec7e00" });
  }

  return badges;
}

const CURRENCY: Record<string, string> = { us: "$", cn: "¥" };

export default function StockCard({ stock, market = "us" }: StockCardProps) {
  const { t } = useTranslation();
  const cur = CURRENCY[market] ?? "$";
  const [showAnalystModal, setShowAnalystModal] = useState(false);

  const badges = getBadges(stock, t);
  const info = stock.info || {};
  const targets = stock.targets || {};
  const targetMean = targets.target_mean ?? targets.mean;
  const upsidePct = stock.upside_pct ?? targets.upside_pct;
  const tech = stock.technicals || {};
  const eps = stock.eps || {};
  const insiderTrades: any[] = stock.insider_trades || [];
  const upgrades: any[] = stock.upgrades || [];
  const rec = stock.recommendations;
  const earningsHistory: any[] = stock.earnings_history || [];

  const low52 = info.low_52w ?? info["52w_low"] ?? info["52wk_low"];
  const high52 = info.high_52w ?? info["52w_high"] ?? info["52wk_high"];
  const price = stock.price ?? 0;
  const rangeSpan = low52 != null && high52 != null && high52 !== low52 ? high52 - low52 : null;
  const rangePct = rangeSpan ? ((price - low52!) / rangeSpan) * 100 : null;

  const totalBuy = (rec?.strong_buy ?? 0) + (rec?.buy ?? 0);
  const totalHold = rec?.hold ?? 0;
  const totalSell = (rec?.strong_sell ?? 0) + (rec?.sell ?? 0);
  const totalRating = totalBuy + totalHold + totalSell;
  const buyPct = totalRating ? Math.round((totalBuy / totalRating) * 100) : 0;
  const holdPct = totalRating ? Math.round((totalHold / totalRating) * 100) : 0;
  const sellPct = totalRating ? 100 - buyPct - holdPct : 0;

  return (
    <div
      style={{
        background: "#111214",
        borderRadius: 16,
        boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
        padding: 24,
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      {/* Top row: symbol + price */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontSize: 20, fontWeight: 700, color: "#fff" }}>{stock.symbol}</span>
            {stock.name && (
              <span style={{ fontSize: 13, color: "#8d969e", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{stock.name}</span>
            )}
          </div>
          {badges.length > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
              {badges.map((b, i) => (
                <span key={i} style={{ background: `${b.color}20`, color: b.color, borderRadius: 9999, padding: "2px 10px", fontSize: 11, fontWeight: 600 }}>
                  {b.label}
                </span>
              ))}
            </div>
          )}
        </div>
        <div style={{ textAlign: "right", marginLeft: 16, flexShrink: 0 }}>
          <div style={{ ...mono, fontSize: 22, fontWeight: 600, color: "#fff" }}>{fmt(stock.price)}</div>
          <div style={{ ...mono, fontSize: 14, color: changeColor(stock.change ?? 0) }}>
            {pct(stock.change_pct ?? stock.change)}
          </div>
        </div>
      </div>

      {/* Key metrics row */}
      <div style={{ display: "flex", gap: 24, paddingTop: 12, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
        {[
          { label: t("stock.marketCap"), value: stock.market_cap ? `${cur}${fmt(stock.market_cap, 0)}` : "--" },
          { label: "P/E", value: info.pe != null ? fmt(info.pe, 1) : "--" },
          { label: "Beta", value: info.beta != null ? fmt(info.beta, 2) : "--" },
          { label: t("stock.52wRange"), value: low52 != null && high52 != null ? `${fmt(low52)}-${fmt(high52)}` : "--" },
        ].map((col) => (
          <div key={col.label} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 11, color: "#8d969e" }}>{col.label}</span>
            <span style={{ ...mono, fontSize: 13, fontWeight: 500, color: "#fff" }}>{col.value}</span>
          </div>
        ))}
      </div>

      {/* 52-week range bar */}
      {rangePct != null && (
        <div>
          <div style={{ background: "#0a0a0b", height: 4, borderRadius: 2, overflow: "hidden" }}>
            <div style={{ background: "#494fdf", height: "100%", borderRadius: 2, width: `${Math.min(100, Math.max(0, rangePct))}%`, transition: "width 0.4s" }} />
          </div>
        </div>
      )}

      {/* Analyst target */}
      {targetMean != null && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", display: "flex", alignItems: "center", gap: 6 }}>
              {t("stock.analystTarget")}
              <InfoTooltip text={t("tooltip.analystTarget")} />
            </span>
            {totalRating > 0 && (
              <span style={{ fontSize: 11, color: "#8d969e" }}>
                {t("stock.analystCount", { count: totalRating })}
              </span>
            )}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.target")}</div>
              <div style={{ ...mono, fontSize: 18, fontWeight: 600, color: "#fff" }}>{cur}{fmt(targetMean)}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.upside")}</div>
              <div style={{ ...mono, fontSize: 18, fontWeight: 600, color: (upsidePct ?? 0) >= 0 ? "#22c55e" : "#ef4444" }}>
                {pct(upsidePct)}
              </div>
            </div>
          </div>
          {totalRating > 0 && (
            <>
              <div style={{ display: "flex", gap: 2, height: 6, borderRadius: 3, overflow: "hidden" }}>
                <div style={{ flex: buyPct, background: "#ef4444", borderRadius: 3 }} />
                <div style={{ flex: holdPct, background: "#494fdf", borderRadius: 3 }} />
                <div style={{ flex: sellPct, background: "#22c55e", borderRadius: 3 }} />
              </div>
              <div style={{ display: "flex", gap: 16, marginTop: 6 }}>
                <span style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.buy")} {totalBuy}({buyPct}%)</span>
                <span style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.hold")} {totalHold}({holdPct}%)</span>
                <span style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.sell")} {totalSell}({sellPct}%)</span>
              </div>
            </>
          )}
          <button
            onClick={() => setShowAnalystModal(true)}
            style={{
              marginTop: 8, width: "100%", padding: "6px 0",
              background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 8, color: "#8d969e", fontSize: 12, cursor: "pointer",
            }}
          >
            {t("stock.viewDetails")} →
          </button>
        </div>
      )}

      {/* Technicals */}
      {(tech.rsi ?? tech.rsi_14) != null && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            {t("stock.technicals")}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 24px" }}>
            {[
              { label: "RSI", value: (tech.rsi ?? tech.rsi_14) != null ? fmt(tech.rsi ?? tech.rsi_14, 1) : "--", tooltip: t("tooltip.rsi") },
              { label: "SMA 50", value: (tech.sma50 ?? tech.sma_50) != null ? `${cur}${fmt(tech.sma50 ?? tech.sma_50)}` : "--", tooltip: t("tooltip.sma50") },
              { label: "SMA 200", value: (tech.sma200 ?? tech.sma_200) != null ? `${cur}${fmt(tech.sma200 ?? tech.sma_200)}` : "--", tooltip: t("tooltip.sma200") },
              { label: "MACD (DIF)", value: (tech.macd ?? tech.macd_line) != null ? fmt(tech.macd ?? tech.macd_line, 4) : "--", tooltip: t("tooltip.macdLine") },
              { label: t("stock.macdSignal"), value: tech.macd_signal != null ? fmt(tech.macd_signal, 4) : "--", tooltip: t("tooltip.macdSignal") },
              { label: t("stock.macdHist"), value: tech.macd_hist != null ? fmt(tech.macd_hist, 4) : "--", tooltip: t("tooltip.macdHist"), color: tech.macd_hist != null ? (tech.macd_hist > 0 ? "#00a87e" : "#e23b4a") : undefined },
            ].map((row) => (
              <div key={row.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 12, color: "#8d969e", display: "flex", alignItems: "center" }}>
                  {row.label}
                  <InfoTooltip text={row.tooltip} />
                </span>
                <span style={{ ...mono, fontSize: 12, color: row.color ?? "#fff" }}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* EPS */}
      {(eps.current_q ?? eps["0q"]?.avg) != null && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            {t("stock.eps")}
          </div>
          <div style={{ display: "flex", gap: 24 }}>
            {[
              { label: t("stock.currentQ"), value: (eps.current_q ?? eps["0q"]?.avg) != null ? `${cur}${fmt(eps.current_q ?? eps["0q"]?.avg)}` : "--", tooltip: t("tooltip.currentEps") },
              { label: t("stock.nextQ"), value: (eps.next_q ?? eps["+1q"]?.avg) != null ? `${cur}${fmt(eps.next_q ?? eps["+1q"]?.avg)}` : "--", tooltip: t("tooltip.nextEps") },
              { label: t("stock.surprise"), value: (eps.surprise_pct ?? (earningsHistory.length > 0 ? earningsHistory[earningsHistory.length - 1]?.surprise_pct : null)) != null ? pct(eps.surprise_pct ?? (earningsHistory.length > 0 ? earningsHistory[earningsHistory.length - 1]?.surprise_pct : null)) : "--", tooltip: t("tooltip.surprise") },
            ].map((row) => (
              <div key={row.label} style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ fontSize: 11, color: "#8d969e", display: "flex", alignItems: "center" }}>
                  {row.label}
                  <InfoTooltip text={row.tooltip} />
                </span>
                <span style={{ ...mono, fontSize: 13, color: "#fff" }}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Insider trades */}
      {insiderTrades.length > 0 && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            {t("stock.insider")}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {insiderTrades.slice(0, 5).map((it: any, i: number) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 12, color: "#8d969e", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 160 }}>
                  {it.name || it.insider}{it.position ? ` (${it.position})` : ""}
                </span>
                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  {it.shares != null && <span style={{ ...mono, fontSize: 11, color: "#22c55e" }}>{Number(it.shares).toLocaleString()} {t("stock.sharesUnit")}</span>}
                  {it.value != null && <span style={{ ...mono, fontSize: 11, color: "#8d969e" }}>{cur}{fmt(it.value, 0)}</span>}
                  {it.date && <span style={{ ...mono, fontSize: 11, color: "#8d969e" }}>{it.date}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Chart */}
      {stock.symbol ? (
        <StockChart symbol={stock.symbol} />
      ) : stock.chart_b64 ? (
        <div style={{ background: "#0a0a0b", borderRadius: 8, padding: 8 }}>
          <img
            src={`data:image/png;base64,${stock.chart_b64}`}
            alt={`${stock.symbol} chart`}
            style={{ width: "100%", borderRadius: 4 }}
          />
        </div>
      ) : (
        <div style={{ background: "#0a0a0b", borderRadius: 8, height: 100, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.chart")}</span>
        </div>
      )}

      {/* Analyst detail modal */}
      {showAnalystModal && (
        <AnalystDetailModal
          targets={targets}
          upsidePct={upsidePct}
          recommendations={rec ?? null}
          upgrades={upgrades}
          onClose={() => setShowAnalystModal(false)}
        />
      )}
    </div>
  );
}
