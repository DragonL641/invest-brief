import { useTranslation } from "react-i18next";

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
  return val >= 0 ? "#ef4444" : "#22c55e";
}

/** Derive badge annotations from technicals / stock data */
function getBadges(stock: any): { label: string; color: string }[] {
  const badges: { label: string; color: string }[] = [];
  const tech = stock.technicals;

  if (tech?.rsi != null) {
    if (tech.rsi > 70) badges.push({ label: "RSI 超买", color: "#e23b4a" });
    else if (tech.rsi < 30) badges.push({ label: "RSI 超卖", color: "#00a87e" });
  }

  if (tech?.macd_signal === "bullish" || tech?.macd_signal === "buy") {
    badges.push({ label: "MACD 看涨", color: "#00a87e" });
  } else if (tech?.macd_signal === "bearish" || tech?.macd_signal === "sell") {
    badges.push({ label: "MACD 看跌", color: "#e23b4a" });
  }

  if (stock.targets?.upside_pct != null && stock.targets.upside_pct > 30) {
    badges.push({ label: "上行 >30%", color: "#494fdf" });
  }

  if (stock.insider_trades && stock.insider_trades.length > 0) {
    badges.push({ label: "内部人活跃", color: "#494fdf" });
  }

  if (stock.earnings_approaching) {
    badges.push({ label: "财报临近", color: "#ec7e00" });
  }

  return badges;
}

export default function StockCard({ stock }: StockCardProps) {
  const { t } = useTranslation();

  const badges = getBadges(stock);
  const info = stock.info || {};
  const targets = stock.targets || {};
  const tech = stock.technicals || {};
  const eps = stock.eps || {};
  const insiderTrades: any[] = stock.insider_trades || [];
  const upgrades: any[] = stock.upgrades || [];
  const rec = stock.recommendations;

  // 52-week range
  const low52 = info.low_52w ?? info["52w_low"];
  const high52 = info.high_52w ?? info["52w_high"];
  const price = stock.price ?? 0;
  const rangeSpan = low52 != null && high52 != null && high52 !== low52 ? high52 - low52 : null;
  const rangePct = rangeSpan ? ((price - low52!) / rangeSpan) * 100 : null;

  // Rating distribution
  const totalRating = (rec?.buy ?? 0) + (rec?.hold ?? 0) + (rec?.sell ?? 0);
  const buyPct = totalRating ? Math.round(((rec?.buy ?? 0) / totalRating) * 100) : 0;
  const holdPct = totalRating ? Math.round(((rec?.hold ?? 0) / totalRating) * 100) : 0;
  const sellPct = totalRating ? 100 - buyPct - holdPct : 0;

  return (
    <div
      style={{
        background: "#16181a",
        borderRadius: 20,
        padding: 24,
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      {/* 1. Top row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, color: "#fff" }}>{stock.symbol}</div>
          {stock.name && <div style={{ fontSize: 13, color: "#8d969e", marginTop: 2 }}>{stock.name}</div>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ ...mono, fontSize: 22, fontWeight: 600, color: "#fff" }}>
            {fmt(stock.price)}
          </div>
          <div style={{ ...mono, fontSize: 14, color: changeColor(stock.change ?? 0) }}>
            {pct(stock.change_pct)}
          </div>
        </div>
      </div>

      {/* 2. Badge row */}
      {badges.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {badges.map((b, i) => (
            <span
              key={i}
              style={{
                background: b.color,
                color: "#fff",
                borderRadius: 9999,
                padding: "4px 12px",
                fontSize: 11,
                fontWeight: 600,
              }}
            >
              {b.label}
            </span>
          ))}
        </div>
      )}

      {/* 3. Metrics row */}
      <div
        style={{
          display: "flex",
          borderTop: "1px solid rgba(255,255,255,0.08)",
          borderBottom: "1px solid rgba(255,255,255,0.08)",
          padding: "12px 0",
        }}
      >
        {[
          { label: t("stock.marketCap"), value: stock.market_cap ? `$${fmt(stock.market_cap, 0)}` : "--" },
          { label: "P/E", value: info.pe != null ? fmt(info.pe, 1) : "--" },
          { label: "Beta", value: info.beta != null ? fmt(info.beta, 2) : "--" },
          { label: "52周范围", value: low52 != null && high52 != null ? `${fmt(low52)}-${fmt(high52)}` : "--" },
        ].map((col, i, arr) => (
          <div
            key={col.label}
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              gap: 4,
              alignItems: i === arr.length - 1 ? "flex-end" : i === 0 ? "flex-start" : "center",
              borderRight: i < arr.length - 1 ? "1px solid rgba(255,255,255,0.12)" : "none",
              paddingRight: i < arr.length - 1 ? 12 : 0,
              paddingLeft: i > 0 ? 12 : 0,
            }}
          >
            <span style={{ fontSize: 11, color: "#8d969e" }}>{col.label}</span>
            <span style={{ ...mono, fontSize: 14, fontWeight: 500, color: "#fff" }}>{col.value}</span>
          </div>
        ))}
      </div>

      {/* 4. 52-week range bar */}
      {rangePct != null && (
        <div>
          <div
            style={{
              background: "#0a0a0a",
              height: 4,
              borderRadius: 2,
              position: "relative",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                background: "#494fdf",
                height: "100%",
                borderRadius: 2,
                width: `${Math.min(100, Math.max(0, rangePct))}%`,
                transition: "width 0.4s",
              }}
            />
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              marginTop: 4,
            }}
          >
            <span style={{ ...mono, fontSize: 10, color: "#8d969e" }}>{fmt(low52)}</span>
            <span style={{ ...mono, fontSize: 10, color: "#8d969e" }}>{fmt(high52)}</span>
          </div>
        </div>
      )}

      {/* 5. Analyst target section */}
      {targets.target_mean != null && (
        <div
          style={{
            borderTop: "1px solid rgba(255,255,255,0.12)",
            paddingTop: 12,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            分析师目标
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.target")}</div>
              <div style={{ ...mono, fontSize: 18, fontWeight: 600, color: "#fff" }}>
                ${fmt(targets.target_mean)}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.upside")}</div>
              <div
                style={{
                  ...mono,
                  fontSize: 18,
                  fontWeight: 600,
                  color: (targets.upside_pct ?? 0) >= 0 ? "#22c55e" : "#ef4444",
                }}
              >
                {pct(targets.upside_pct)}
              </div>
            </div>
          </div>
          {/* Rating bar */}
          {totalRating > 0 && (
            <>
              <div style={{ display: "flex", gap: 2, height: 8, borderRadius: 4, overflow: "hidden" }}>
                <div style={{ flex: buyPct, background: "#ef4444", borderRadius: 4 }} />
                <div style={{ flex: holdPct, background: "#494fdf", borderRadius: 4 }} />
                <div style={{ flex: sellPct, background: "#22c55e", borderRadius: 4 }} />
              </div>
              <div style={{ display: "flex", gap: 16, marginTop: 6 }}>
                <span style={{ fontSize: 11, color: "#8d969e" }}>买入 {buyPct}%</span>
                <span style={{ fontSize: 11, color: "#8d969e" }}>持有 {holdPct}%</span>
                <span style={{ fontSize: 11, color: "#8d969e" }}>卖出 {sellPct}%</span>
              </div>
            </>
          )}
        </div>
      )}

      {/* 6. Two-column bottom */}
      <div
        style={{
          borderTop: "1px solid rgba(255,255,255,0.12)",
          paddingTop: 12,
          display: "flex",
          gap: 24,
        }}
      >
        {/* Left column */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Technicals */}
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
              {t("stock.technicals")}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {[
                { label: "RSI", value: tech.rsi != null ? fmt(tech.rsi, 1) : "--" },
                { label: "SMA 50", value: tech.sma50 != null ? `$${fmt(tech.sma50)}` : "--" },
                { label: "SMA 200", value: tech.sma200 != null ? `$${fmt(tech.sma200)}` : "--" },
                { label: "MACD", value: tech.macd != null ? fmt(tech.macd, 4) : "--" },
              ].map((row) => (
                <div key={row.label} style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 12, color: "#8d969e" }}>{row.label}</span>
                  <span style={{ ...mono, fontSize: 12, color: "#fff" }}>{row.value}</span>
                </div>
              ))}
            </div>
          </div>

          {/* EPS */}
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
              {t("stock.eps")}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {[
                { label: "本季度", value: eps.current_q != null ? `$${fmt(eps.current_q)}` : "--" },
                { label: "下季度", value: eps.next_q != null ? `$${fmt(eps.next_q)}` : "--" },
                { label: "惊喜", value: eps.surprise_pct != null ? pct(eps.surprise_pct) : "--" },
              ].map((row) => (
                <div key={row.label} style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 12, color: "#8d969e" }}>{row.label}</span>
                  <span style={{ ...mono, fontSize: 12, color: "#fff" }}>{row.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right column */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Insider trades */}
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
              {t("stock.insider")}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {insiderTrades.length > 0 ? (
                insiderTrades.slice(0, 3).map((t: any, i: number) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 12, color: "#8d969e", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 120 }}>
                      {t.name || t.insider}
                    </span>
                    <span
                      style={{
                        ...mono,
                        fontSize: 12,
                        color: (t.action || t.type || "").toLowerCase().includes("buy") ? "#ef4444" : "#22c55e",
                      }}
                    >
                      {t.action || t.type}
                    </span>
                  </div>
                ))
              ) : (
                <span style={{ fontSize: 12, color: "#8d969e" }}>--</span>
              )}
            </div>
          </div>

          {/* Upgrades */}
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
              {t("stock.upgrades")}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {upgrades.length > 0 ? (
                upgrades.slice(0, 3).map((u: any, i: number) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 12, color: "#8d969e", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 120 }}>
                      {u.institution || u.firm}
                    </span>
                    <span style={{ ...mono, fontSize: 12, color: "#fff" }}>
                      {u.from_grade && u.to_grade ? `${u.from_grade}->${u.to_grade}` : u.change || u.grade}
                    </span>
                  </div>
                ))
              ) : (
                <span style={{ fontSize: 12, color: "#8d969e" }}>--</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 7. Chart placeholder */}
      <div
        style={{
          background: "#0a0a0a",
          borderRadius: 8,
          height: 100,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ fontSize: 12, color: "#8d969e" }}>
          {t("stock.chart")} (ECharts)
        </span>
      </div>
    </div>
  );
}
