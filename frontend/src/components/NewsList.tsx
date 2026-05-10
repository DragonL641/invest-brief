import { useState } from "react";
import { useTranslation } from "react-i18next";

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
  const [expandedSet, setExpandedSet] = useState<Set<number>>(new Set());

  if (!news || news.length === 0) return null;

  const display = news.slice(0, DISPLAY_LIMIT);

  const toggleExpand = (i: number) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  return (
    <section>
      <h2 style={{ color: "#fff", fontSize: 20, fontWeight: 600, margin: "0 0 16px 0" }}>
        {t("market.news")}
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {display.map((item, i) => {
          const timeStr = item.time || item.date || "";
          const isExpanded = expandedSet.has(i);

          return (
            <div
              key={i}
              style={{
                background: "#16181a",
                borderRadius: 20,
                padding: 16,
              }}
            >
              {/* Title — clickable if url exists */}
              <div style={{ fontSize: 15, fontWeight: 500, color: "#fff", marginBottom: 8 }}>
                {item.url ? (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "#fff", textDecoration: "none" }}
                  >
                    {item.title}
                  </a>
                ) : (
                  item.title
                )}
              </div>

              {/* Summary — collapsible */}
              {item.summary && (
                <div style={{ marginBottom: 8 }}>
                  <div
                    style={{
                      fontSize: 13,
                      color: "#8d969e",
                      lineHeight: 1.6,
                      maxHeight: isExpanded ? "none" : 44,
                      overflow: "hidden",
                    }}
                  >
                    {item.summary}
                  </div>
                  {item.summary.length > 80 && (
                    <button
                      onClick={() => toggleExpand(i)}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#494fdf",
                        fontSize: 12,
                        cursor: "pointer",
                        padding: 0,
                        marginTop: 4,
                      }}
                    >
                      {isExpanded ? t("news.collapse") : t("news.expand")}
                    </button>
                  )}
                </div>
              )}

              {/* Meta: source · time · sentiment */}
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
          );
        })}
      </div>
    </section>
  );
}
