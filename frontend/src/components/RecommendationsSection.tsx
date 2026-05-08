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
      <h2 style={{ color: "#fff", fontSize: 20, fontWeight: 600, margin: "0 0 16px 0" }}>
        {t("recommendations.title")}
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {recommendations.map((r, i) => (
          <StockCard key={r.symbol || i} stock={r} market={market} />
        ))}
        {recommendations.length === 0 && (
          <div style={{ color: "#8d969e", fontSize: 14, padding: "40px 0", textAlign: "center" }}>
            --
          </div>
        )}
      </div>
    </section>
  );
}
