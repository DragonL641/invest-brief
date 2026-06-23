import { Drawer, Tag, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { analyzeETF } from "../../api/etf";

interface Props {
  symbol: string | null;
  onClose: () => void;
}

const DIMENSION_ORDER = ["技术面", "趋势面", "资金面", "估值面"];

const SIGNAL_COLORS: Record<string, string> = {
  bullish: "#52c41a",
  bearish: "#cf1322",
  warning: "#faad14",
  neutral: "#8d969e",
};

const SIGNAL_LABELS: Record<string, string> = {
  bullish: "偏多",
  bearish: "偏空",
  warning: "注意",
  neutral: "中性",
};

function formatFlow(val: number | null | undefined): string {
  if (val == null) return "-";
  const abs = Math.abs(val);
  if (abs >= 1e8) return `${(val / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(val / 1e4).toFixed(0)}万`;
  return val.toFixed(0);
}

export default function ETFDetail({ symbol, onClose }: Props) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    analyzeETF(symbol)
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [symbol]);

  return (
    <Drawer
      open={!!symbol}
      onClose={onClose}
      width={520}
      title={data ? `${data.name} (${data.symbol})` : symbol}
      styles={{
        header: { background: "#111", borderBottom: "1px solid rgba(255,255,255,0.08)" },
        body: { background: "#111", padding: "16px 24px" },
      }}
    >
      {loading && <Spin style={{ display: "block", margin: "40px auto" }} />}
      {!loading && data && (
        <>
          {/* 价格 */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span style={{ fontSize: 28, fontWeight: 700, color: (data.change_pct ?? 0) >= 0 ? "#52c41a" : "#cf1322" }}>
                ¥{data.price?.toFixed(3)}
              </span>
              <span style={{ fontSize: 15, color: (data.change_pct ?? 0) >= 0 ? "#52c41a" : "#cf1322" }}>
                {(data.change_pct ?? 0) >= 0 ? "+" : ""}{data.change_pct?.toFixed(2)}%
              </span>
            </div>
            <div style={{ display: "flex", gap: 16, marginTop: 6, fontSize: 13, color: "#8d969e" }}>
              <span>IOPV: {data.iopv?.toFixed(4) ?? "-"}</span>
              <span>溢价率: <span style={{ color: Math.abs(data.premium_rate ?? 0) > 1 ? "#faad14" : "#8d969e" }}>{(data.premium_rate ?? 0).toFixed(2)}%</span></span>
              <span>主力: {formatFlow(data.main_net_flow)}</span>
            </div>
          </div>

          {/* AI 综合研判 */}
          {data.ai_conclusion && (
            <div style={{ background: "rgba(73,79,223,0.1)", border: "1px solid rgba(73,79,223,0.3)", borderRadius: 8, padding: 12, marginBottom: 20 }}>
              <div style={{ fontSize: 12, color: "#494fdf", marginBottom: 4, fontWeight: 600 }}>AI 综合研判</div>
              <Typography.Paragraph style={{ color: "#e0e0e0", fontSize: 13, margin: 0, lineHeight: 1.6 }}>
                {data.ai_conclusion}
              </Typography.Paragraph>
            </div>
          )}

          {/* 按维度展示规则结果 */}
          {DIMENSION_ORDER.map((dim) => {
            const rules = (data.rule_results || []).filter((r: any) => r.dimension === dim);
            if (rules.length === 0) return null;
            return (
              <div key={dim} style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span style={{ color: "#fff", fontWeight: 600, fontSize: 14 }}>{dim}</span>
                  <DimensionTag summary={data.dimension_summary?.[dim]} />
                </div>
                {rules.map((r: any) => (
                  <div key={r.rule_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: 13 }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: SIGNAL_COLORS[r.signal] || "#8d969e", flexShrink: 0 }} />
                    <span style={{ color: "#b0b8c4" }}>{r.name}</span>
                    <span style={{ color: SIGNAL_COLORS[r.signal] || "#8d969e", marginLeft: "auto", fontSize: 12 }}>
                      {r.detail || SIGNAL_LABELS[r.signal] || r.signal}
                    </span>
                  </div>
                ))}
              </div>
            );
          })}
        </>
      )}
    </Drawer>
  );
}

function DimensionTag({ summary }: { summary?: Record<string, number> }) {
  if (!summary) return null;
  const b = summary.bullish || 0;
  const s = summary.bearish || 0;
  const w = summary.warning || 0;
  if (w > 0 && w >= b && w >= s) return <Tag color="gold">注意风险</Tag>;
  if (s > b) return <Tag color="red">偏空</Tag>;
  if (b > s + 1) return <Tag color="green">偏多</Tag>;
  return <Tag>中性</Tag>;
}
