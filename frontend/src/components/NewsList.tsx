import { useTranslation } from "react-i18next";

interface NewsListProps {
  news: any[];
}

function sentimentColor(s: string): string {
  if (!s) return "#494fdf";
  const lower = s.toLowerCase();
  if (lower.includes("positive") || lower.includes("正面") || lower.includes("긍정")) return "#00a87e";
  if (lower.includes("negative") || lower.includes("负面") || lower.includes("부정")) return "#e23b4a";
  return "#494fdf";
}

function sentimentLabel(s: string): string {
  if (!s) return "--";
  const lower = s.toLowerCase();
  if (lower.includes("positive") || lower.includes("正面")) return "正面";
  if (lower.includes("negative") || lower.includes("负面")) return "负面";
  if (lower.includes("neutral") || lower.includes("中性")) return "中性";
  if (lower.includes("긍정")) return "긍정";
  if (lower.includes("부정")) return "부정";
  if (lower.includes("중립")) return "중립";
  return s;
}

export default function NewsList({ news }: NewsListProps) {
  const { t } = useTranslation();

  if (!news || news.length === 0) return null;

  return (
    <section>
      <h2 style={{ color: "#fff", fontSize: 20, fontWeight: 600, margin: "0 0 16px 0" }}>
        {t("market.news")}
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {news.map((item, i) => (
          <div
            key={i}
            style={{
              background: "#16181a",
              borderRadius: 20,
              padding: 16,
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 500, color: "#fff", marginBottom: 8 }}>
              {item.title}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {item.source && (
                <span style={{ fontSize: 12, color: "#8d969e" }}>{item.source}</span>
              )}
              {item.time && (
                <span style={{ fontSize: 12, color: "#8d969e" }}>{item.time}</span>
              )}
              {item.sentiment && (
                <span
                  style={{
                    background: sentimentColor(item.sentiment),
                    color: "#fff",
                    borderRadius: 9999,
                    padding: "2px 10px",
                    fontSize: 11,
                    fontWeight: 600,
                  }}
                >
                  {sentimentLabel(item.sentiment)}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
