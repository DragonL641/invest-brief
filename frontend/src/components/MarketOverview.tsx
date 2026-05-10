import { useTranslation } from "react-i18next";
import InfoTooltip from "./InfoTooltip";

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

const INDEX_TOOLTIP_MAP: Record<string, string> = {
  "S&P 500": "tooltip.index.sp500",
  "NASDAQ": "tooltip.index.nasdaq",
  "Dow Jones": "tooltip.index.dowjones",
  "VIX": "tooltip.index.vix",
  "10Y国债": "tooltip.index.tnx",
  "WTI原油": "tooltip.index.wti",
  "美元指数": "tooltip.index.dxy",
  "上证指数": "tooltip.index.sh",
  "深证成指": "tooltip.index.sz",
  "创业板指": "tooltip.index.cyb",
  "沪深300": "tooltip.index.hs300",
  "科创50": "tooltip.index.kc50",
};

const INDEX_NAME_MAP: Record<string, string> = {
  "S&P 500": "index.sp500",
  "NASDAQ": "index.nasdaq",
  "Dow Jones": "index.dowjones",
  "VIX": "index.vix",
  "10Y国债": "index.tnx",
  "WTI原油": "index.wti",
  "美元指数": "index.dxy",
  "上证指数": "index.sh",
  "深证成指": "index.sz",
  "创业板指": "index.cyb",
  "沪深300": "index.hs300",
  "科创50": "index.kc50",
};

const INDEX_CATEGORIES = [
  {
    titleKey: "market.category.stockUS",
    names: ["S&P 500", "NASDAQ", "Dow Jones"],
  },
  {
    titleKey: "market.category.stockCN",
    names: ["上证指数", "深证成指", "创业板指", "沪深300", "科创50"],
  },
  {
    titleKey: "market.category.bonds",
    names: ["VIX", "10Y国债", "WTI原油", "美元指数"],
  },
];

function IndexCard({ idx }: { idx: IndexData }) {
  const { t } = useTranslation();
  const isUp = idx.change > 0;
  const isDown = idx.change < 0;
  const changeColor = isUp ? "#ef4444" : isDown ? "#22c55e" : "#8d969e";
  const tooltipKey = INDEX_TOOLTIP_MAP[idx.name];

  return (
    <div
      style={{
        background: "#111214",
        borderRadius: 16,
        padding: 20,
        boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
        display: "flex",
        flexDirection: "column",
        gap: 4,
        minWidth: 180,
        flex: "1 1 180px",
      }}
    >
      <span style={{ fontSize: 13, color: "#8d969e", fontWeight: 500, display: "flex", alignItems: "center" }}>
        {t(INDEX_NAME_MAP[idx.name] ?? idx.name)}
        {tooltipKey && <InfoTooltip text={t(tooltipKey)} />}
      </span>
      <span
        style={{
          fontSize: 28,
          fontFamily: "'Geist Mono', monospace",
          fontWeight: 600,
          color: "#fff",
          letterSpacing: "-0.5px",
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
}

export default function MarketOverview({ indices }: MarketOverviewProps) {
  const { t } = useTranslation();

  if (!indices || indices.length === 0) return null;

  const indexMap = new Map(indices.map((idx) => [idx.name, idx]));
  const matched = new Set<string>();

  const categories = INDEX_CATEGORIES.map((cat) => {
    const items = cat.names
      .filter((name) => indexMap.has(name))
      .map((name) => {
        matched.add(name);
        return indexMap.get(name)!;
      });
    return { titleKey: cat.titleKey, items };
  }).filter((cat) => cat.items.length > 0);

  // Uncategorized indices go into a catch-all row
  const uncategorized = indices.filter((idx) => !matched.has(idx.name));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {categories.map((cat) => (
        <div key={cat.titleKey}>
          <h3 style={{ color: "#8d969e", fontSize: 13, fontWeight: 600, margin: "0 0 8px 0", textTransform: "uppercase", letterSpacing: "0.5px" }}>
            {t(cat.titleKey)}
          </h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {cat.items.map((idx) => (
              <IndexCard key={idx.name} idx={idx} />
            ))}
          </div>
        </div>
      ))}
      {uncategorized.length > 0 && (
        <div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {uncategorized.map((idx) => (
              <IndexCard key={idx.name} idx={idx} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
