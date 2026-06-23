import React, { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import { sectionAnalysis } from "../api/chat";

interface MarketAnalysisPanelProps {
  indices: { name: string; point: number; change: number }[];
  calendar: any[];
  market: string;
}

const MD_ANALYSIS_COMPONENTS = {
  p: ({ children }: any) => <p style={{ margin: "0 0 12px 0" }}>{children}</p>,
  ul: ({ children }: any) => <ul style={{ margin: "4px 0 12px 0", paddingLeft: 20 }}>{children}</ul>,
  ol: ({ children }: any) => <ol style={{ margin: "4px 0 12px 0", paddingLeft: 20 }}>{children}</ol>,
  li: ({ children }: any) => <li style={{ margin: "4px 0" }}>{children}</li>,
  strong: ({ children }: any) => <strong style={{ color: "#fff" }}>{children}</strong>,
  h3: ({ children }: any) => <h3 style={{ color: "#fff", fontSize: 15, fontWeight: 600, margin: "16px 0 8px 0" }}>{children}</h3>,
  h4: ({ children }: any) => <h4 style={{ color: "#fff", fontSize: 14, fontWeight: 600, margin: "12px 0 6px 0" }}>{children}</h4>,
};

function MarketAnalysisPanel({ indices, calendar, market }: MarketAnalysisPanelProps) {
  const { t } = useTranslation();
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const lastMarketRef = useRef(market);
  const generatedRef = useRef(false);

  // Reset when market changes
  useEffect(() => {
    if (lastMarketRef.current !== market) {
      lastMarketRef.current = market;
      setAnalysis(null);
      setError(false);
      generatedRef.current = false;
    }
  }, [market]);

  // Auto-generate analysis when data is ready
  useEffect(() => {
    if (generatedRef.current || loading || indices.length === 0) return;
    generatedRef.current = true;
    setLoading(true);
    setError(false);

    sectionAnalysis("market_overview_and_calendar", market, { indices, economic_calendar: calendar })
      .then((res) => setAnalysis(res.analysis))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [indices, calendar, market]);

  const refresh = async () => {
    setLoading(true);
    setError(false);
    try {
      const res = await sectionAnalysis(
        "market_overview_and_calendar",
        market,
        { indices, economic_calendar: calendar }
      );
      setAnalysis(res.analysis);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        background: "#111214",
        borderRadius: 16,
        padding: 24,
        boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ color: "#fff", fontSize: 15, fontWeight: 600, margin: 0 }}>
          {t("market.aiAnalysis")}
        </h3>
        {!loading && analysis && (
          <button
            onClick={refresh}
            style={{
              background: "rgba(73,79,223,0.12)",
              border: "1px solid rgba(73,79,223,0.3)",
              borderRadius: 9999,
              color: "#494fdf",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              padding: "6px 16px",
            }}
          >
            {t("refresh")}
          </button>
        )}
      </div>
      {loading && (
        <div style={{ color: "#8d969e", fontSize: 14 }}>
          {t("market.aiAnalysis.loading")}
        </div>
      )}
      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ color: "#e23b4a", fontSize: 14 }}>
            {t("market.aiAnalysis.error")}
          </div>
          <button
            onClick={refresh}
            style={{
              background: "rgba(73,79,223,0.12)",
              border: "1px solid rgba(73,79,223,0.3)",
              borderRadius: 9999,
              color: "#494fdf",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
              padding: "4px 12px",
            }}
          >
            {t("refresh")}
          </button>
        </div>
      )}
      {analysis && !loading && (
        <div style={{ color: "rgba(255,255,255,0.85)", fontSize: 14, lineHeight: 1.8 }}>
          <ReactMarkdown components={MD_ANALYSIS_COMPONENTS}>
            {analysis}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

export default React.memo(MarketAnalysisPanel);
