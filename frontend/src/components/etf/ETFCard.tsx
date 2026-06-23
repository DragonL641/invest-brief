import React, { useState } from "react";
import { Card, Tag, Spin } from "antd";

interface ETFCardProps {
  symbol: string;
  name: string;
  price?: number | null;
  change_pct?: number | null;
  premium_rate?: number | null;
  main_net_flow?: number | null;
  ai_conclusion?: string;
  dimension_summary?: Record<string, Record<string, number>>;
  onViewDetail: (symbol: string) => void;
}

function formatFlow(val: number | null | undefined): string {
  if (val == null) return "-";
  const abs = Math.abs(val);
  if (abs >= 1e8) return `${(val / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(val / 1e4).toFixed(0)}万`;
  return val.toFixed(0);
}

function summaryVerdict(summary?: Record<string, Record<string, number>>): { text: string; color: string } {
  if (!summary) return { text: "加载中", color: "#8d969e" };
  let bullish = 0, bearish = 0, warning = 0;
  for (const d of Object.values(summary)) {
    bullish += d.bullish || 0;
    bearish += d.bearish || 0;
    warning += d.warning || 0;
  }
  if (warning > bullish && warning > bearish) return { text: "注意风险", color: "#faad14" };
  if (bearish > bullish) return { text: "偏空", color: "#cf1322" };
  if (bullish > bearish + 1) return { text: "偏多", color: "#52c41a" };
  return { text: "中性", color: "#8d969e" };
}

function ETFCard({
  symbol, name, price, change_pct, premium_rate,
  main_net_flow, ai_conclusion, dimension_summary, onViewDetail,
}: ETFCardProps) {
  const [loading, setLoading] = useState(false);
  const up = (change_pct ?? 0) >= 0;
  const verdict = summaryVerdict(dimension_summary);

  return (
    <Card
      hoverable
      onClick={() => { setLoading(true); onViewDetail(symbol); }}
      style={{ background: "#111", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, cursor: "pointer" }}
      styles={{ body: { padding: 16 } }}
    >
      {loading && <Spin size="small" style={{ position: "absolute", top: 8, right: 8 }} />}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ color: "#fff", fontSize: 15, fontWeight: 600 }}>{name}</span>
        <span style={{ color: "#8d969e", fontSize: 12 }}>{symbol}</span>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <span style={{ color: up ? "#52c41a" : "#cf1322", fontSize: 22, fontWeight: 700 }}>
          ¥{price?.toFixed(3) ?? "-"}
        </span>
        <span style={{ color: up ? "#52c41a" : "#cf1322", fontSize: 13 }}>
          {up ? "+" : ""}{change_pct?.toFixed(2) ?? "-"}%
        </span>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 8, fontSize: 12, color: "#b0b8c4" }}>
        <span>溢价 {(premium_rate ?? 0).toFixed(2)}%</span>
        <span>主力 {formatFlow(main_net_flow)}</span>
      </div>

      {dimension_summary && (
        <Tag color={verdict.color === "#52c41a" ? "green" : verdict.color === "#cf1322" ? "red" : verdict.color === "#faad14" ? "gold" : "default"} style={{ marginBottom: 4 }}>
          {verdict.text}
        </Tag>
      )}

      {ai_conclusion && (
        <div style={{ fontSize: 12, color: "#8d969e", marginTop: 4, lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
          {ai_conclusion}
        </div>
      )}
    </Card>
  );
}

export default React.memo(ETFCard);
