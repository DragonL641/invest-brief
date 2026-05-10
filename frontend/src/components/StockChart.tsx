import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

interface StockChartProps {
  symbol: string;
}

const TV_LOCALE: Record<string, string> = { zh: "zh", ko: "ko" };

function toTVSymbol(symbol: string): string {
  if (/^\d{6}$/.test(symbol)) {
    // 6xxxxx = SSE (Shanghai), everything else (0xxxxx, 3xxxxx, 8xxxxx) = SZSE
    const exchange = /^6/.test(symbol) ? "SSE" : "SZSE";
    return `${exchange}:${symbol}`;
  }
  return symbol;
}

export default function StockChart({ symbol }: StockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { i18n } = useTranslation();
  const locale = TV_LOCALE[i18n.language?.split("-")[0]] ?? "zh";

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.textContent = "";

    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = "300px";
    widget.style.width = "100%";
    el.appendChild(widget);

    const script = document.createElement("script");
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.textContent = JSON.stringify({
      symbol: toTVSymbol(symbol),
      interval: "D",
      timezone: "Asia/Shanghai",
      theme: "dark",
      style: "1",
      locale,
      hide_top_toolbar: true,
      hide_legend: true,
      save_image: false,
      allow_symbol_change: false,
      autosize: true,
    });
    el.appendChild(script);

    return () => {
      el.textContent = "";
    };
  }, [symbol, locale]);

  return (
    <div
      style={{
        background: "#0a0a0a",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <div
        ref={containerRef}
        className="tradingview-widget-container"
      />
    </div>
  );
}
