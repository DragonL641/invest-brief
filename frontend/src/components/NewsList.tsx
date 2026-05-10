import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

interface NewsItem {
  title: string;
  summary?: string;
  url?: string;
  source?: string;
  time?: string;
  date?: string;
  sentiment?: string;
}

interface NewsListProps {
  news: NewsItem[];
}

const DISPLAY_LIMIT = 5;

function sentimentColor(s: string): string {
  if (!s) return "#494fdf";
  const lower = s.toLowerCase();
  if (lower.includes("positive") || lower.includes("正面") || lower.includes("긍정")) return "#00a87e";
  if (lower.includes("negative") || lower.includes("负面") || lower.includes("부정")) return "#e23b4a";
  return "#494fdf";
}

function sentimentLabel(s: string, t: TFunction): string {
  if (!s) return "--";
  const lower = s.toLowerCase();
  if (lower.includes("positive") || lower.includes("正面") || lower.includes("긍정")) return t("sentiment.positive");
  if (lower.includes("negative") || lower.includes("负面") || lower.includes("부정")) return t("sentiment.negative");
  if (lower.includes("neutral") || lower.includes("中性") || lower.includes("중립")) return t("sentiment.neutral");
  return s;
}

function splitSummary(text: string): string[] {
  // LLM output: each point on its own line
  const byLine = text.split(/\n/).map((s) => s.replace(/^[-•*\d.、)\s]+/, "").trim()).filter(Boolean);
  if (byLine.length > 1) return byLine;
  // Fallback: split on Chinese semicolons
  const bySemicolon = text.split(/[；;]/).map((s) => s.trim()).filter(Boolean);
  if (bySemicolon.length > 1) return bySemicolon;
  return [text];
}

export default function NewsList({ news }: NewsListProps) {
  const { t } = useTranslation();

  if (!news || news.length === 0) return null;

  const display = news.slice(0, DISPLAY_LIMIT);

  return (
    <section>
      <h2 style={{ color: "#fff", fontSize: 18, fontWeight: 600, margin: "0 0 16px 0" }}>
        {t("market.news")}
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {display.map((item, i) => {
          const timeStr = item.time || item.date || "";

          return (
            <div
              key={i}
              style={{
                background: "#111214",
                borderRadius: 16,
                padding: "16px 20px",
                boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
              }}
            >
              <div style={{ fontSize: 14, fontWeight: 600, color: "#fff", marginBottom: 6, lineHeight: 1.5 }}>
                {item.title}
              </div>

              {item.summary && (
                <div style={{ marginBottom: 8 }}>
                  <ul style={{ margin: 0, paddingLeft: 16, color: "#8d969e", fontSize: 13, lineHeight: 1.6 }}>
                    {splitSummary(item.summary).map((line, j) => (
                      <li key={j} style={{ marginBottom: 2 }}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {item.source && (
                  <span style={{ fontSize: 12, color: "#8d969e" }}>{item.source}</span>
                )}
                {timeStr && (
                  <span style={{ fontSize: 12, color: "#8d969e" }}>{timeStr}</span>
                )}
                {item.sentiment && (
                  <span
                    style={{
                      background: `${sentimentColor(item.sentiment)}20`,
                      color: sentimentColor(item.sentiment),
                      borderRadius: 9999,
                      padding: "2px 10px",
                      fontSize: 11,
                      fontWeight: 600,
                    }}
                  >
                    {sentimentLabel(item.sentiment, t)}
                  </span>
                )}
                {item.url && (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      marginLeft: "auto",
                      background: "rgba(73,79,223,0.12)",
                      border: "1px solid rgba(73,79,223,0.3)",
                      borderRadius: 9999,
                      color: "#494fdf",
                      fontSize: 12,
                      fontWeight: 600,
                      padding: "3px 12px",
                      textDecoration: "none",
                      cursor: "pointer",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {t("news.readMore")}
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
