import { useTranslation } from "react-i18next";
import StockCard from "./StockCard";

interface RecommendationsSectionProps {
  recommendations: any[];
  market: string;
}

export default function RecommendationsSection({ recommendations, market }: RecommendationsSectionProps) {
  const { t } = useTranslation();

  return (
    <section>
      <h2 style={{ color: "#fff", fontSize: 18, fontWeight: 600, margin: "0 0 16px 0" }}>
        {t("recommendations.title")}
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {recommendations.map((r, i) => (
          <StockCard key={r.symbol || i} stock={r} market={market} />
        ))}
        {recommendations.length === 0 && (
          <div style={{ background: "#111214", borderRadius: 16, padding: 24, color: "#8d969e", fontSize: 14, textAlign: "center", boxShadow: "0 1px 3px rgba(0,0,0,0.3)" }}>
            {t("recommendations.empty")}
          </div>
        )}
      </div>
    </section>
  );
}
