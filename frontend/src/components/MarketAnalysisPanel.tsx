import { useState } from "react";
import { useTranslation } from "react-i18next";
import { sectionAnalysis } from "../api/chat";

interface MarketAnalysisPanelProps {
  indices: { name: string; point: number; change: number }[];
  calendar: any[];
  market: string;
}

export default function MarketAnalysisPanel({ indices, calendar, market }: MarketAnalysisPanelProps) {
  const { t } = useTranslation();
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const generate = async () => {
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
        {!loading && (
          <button
            onClick={generate}
            disabled={loading}
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
            {analysis ? t("refresh") : t("market.aiAnalysis.generate")}
          </button>
        )}
      </div>
      {loading && (
        <div style={{ color: "#8d969e", fontSize: 14 }}>
          {t("market.aiAnalysis.loading")}
        </div>
      )}
      {error && (
        <div style={{ color: "#e23b4a", fontSize: 14 }}>
          {t("market.aiAnalysis.error")}
        </div>
      )}
      {analysis && !loading && (
        <div style={{ color: "rgba(255,255,255,0.85)", fontSize: 14, lineHeight: 1.8 }}>
          {analysis}
        </div>
      )}
    </div>
  );
}
