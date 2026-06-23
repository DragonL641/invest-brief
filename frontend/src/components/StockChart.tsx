import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface StockChartProps {
  symbol: string;
}

const CHART_HEIGHT = 400;

const TV_LOCALE: Record<string, string> = { zh: "zh", ko: "ko" };

function toTVSymbol(symbol: string): string {
  if (/^\d{6}$/.test(symbol)) {
    const exchange = /^6/.test(symbol) ? "SSE" : "SZSE";
    return `${exchange}:${symbol}`;
  }
  return symbol;
}

export default function StockChart({ symbol }: StockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);
  const { i18n } = useTranslation();
  const locale = TV_LOCALE[i18n.language?.split("-")[0]] ?? "zh";

  // IntersectionObserver to lazy-load the TradingView widget
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Inject TradingView widget only when visible
  useEffect(() => {
    if (!isVisible) return;
    const el = containerRef.current;
    if (!el) return;
    el.textContent = "";

    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = CHART_HEIGHT + "px";
    widget.style.width = "100%";
    el.appendChild(widget);

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.textContent = JSON.stringify({
      symbol: toTVSymbol(symbol),
      interval: "D",
      timezone: "Asia/Shanghai",
      theme: "dark",
      style: "1",
      locale,
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      allow_symbol_change: false,
    });
    el.appendChild(script);

    return () => {
      el.textContent = "";
    };
  }, [isVisible, symbol, locale]);

  return (
    <div
      style={{
        height: CHART_HEIGHT,
        width: "100%",
        background: "#0a0a0b",
        borderRadius: 8,
      }}
    >
      <div
        ref={containerRef}
        className="tradingview-widget-container"
        style={{ height: "100%", width: "100%" }}
      />
    </div>
  );
}
