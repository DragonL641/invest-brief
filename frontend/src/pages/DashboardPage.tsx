import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton, App } from "antd";
import Header from "../components/Header";
import MarketOverview from "../components/MarketOverview";
import WatchlistSection from "../components/WatchlistSection";
import RecommendationsSection from "../components/RecommendationsSection";
import NewsList from "../components/NewsList";
import EconomicCalendar from "../components/EconomicCalendar";
import MarketAnalysisPanel from "../components/MarketAnalysisPanel";
import ChatWidget from "../components/ChatWidget";
import SectionNav from "../components/SectionNav";
import PreferencesModal from "../components/PreferencesModal";
import SectionErrorCard from "../components/SectionErrorCard";
import type { SectionDef } from "../components/SectionNav";
import type { SectionState } from "../types/section";
import { getMarketData, refreshMarket, refreshSection } from "../api/data";
import { useAuth } from "../hooks/useAuth";

const SECTIONS: SectionDef[] = [
  { id: "overview", titleKey: "market.overview" },
  { id: "news", titleKey: "market.news" },
  { id: "watchlist", titleKey: "watchlist.title" },
  { id: "recommendations", titleKey: "recommendations.title" },
];

function ProgressBar({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div
      style={{
        position: "fixed",
        top: 64,
        left: 0,
        width: "100%",
        height: 2,
        zIndex: 1000,
        overflow: "hidden",
        background: "transparent",
      }}
    >
      <div
        style={{
          width: "20%",
          height: "100%",
          background: "#494fdf",
          animation: "indeterminate 1.2s ease-in-out infinite",
        }}
      />
      <style>{`
        @keyframes indeterminate {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(500%); }
        }
      `}</style>
    </div>
  );
}

function formatUpdatedAt(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const y = d.getFullYear();
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${y}.${m}.${day} ${hh}:${mm}`;
}

function SectionSkeleton() {
  return (
    <div style={{ background: "#111214", borderRadius: 16, padding: 24 }}>
      <Skeleton active paragraph={{ rows: 2 }} title={{ width: "40%" }} />
    </div>
  );
}

export default function DashboardPage() {
  const [market, setMarket] = useState<"us" | "cn">("us");
  const [sections, setSections] = useState<Record<string, SectionState>>({});
  const [globalRefreshing, setGlobalRefreshing] = useState(false);
  const [refreshingSection, setRefreshingSection] = useState<string | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [initialError, setInitialError] = useState(false);
  const [activeId, setActiveId] = useState(SECTIONS[0].id);
  const spyDisabledRef = useRef(false);
  const [prefsOpen, setPrefsOpen] = useState(false);
  const sectionRefs = useRef<Map<string, HTMLElement>>(new Map());
  useAuth();
  const { t } = useTranslation();
  const { message } = App.useApp();

  const mapSectionsResponse = (data: any): Record<string, SectionState> => {
    const result: Record<string, SectionState> = {};
    const raw = data.sections || {};
    for (const [key, val] of Object.entries(raw)) {
      const s = val as any;
      result[key] = {
        status: s.status === "cached" ? "ok" : s.status,
        data: s.data,
        error: s.error,
        updatedAt: s.updated_at,
      };
    }
    return result;
  };

  const fetchData = (m: string) => {
    setInitialLoading(true);
    setInitialError(false);
    getMarketData(m)
      .then((r) => {
        setSections(mapSectionsResponse(r.data));
        setInitialError(false);
      })
      .catch(() => {
        setInitialError(true);
        setSections({});
      })
      .finally(() => setInitialLoading(false));
  };

  const refreshData = (m: string) => {
    setGlobalRefreshing(true);
    setSections((prev) => {
      const next: Record<string, SectionState> = {};
      for (const [key, val] of Object.entries(prev)) {
        next[key] = { ...val, status: "loading" };
      }
      return next;
    });
    refreshMarket(m)
      .then((r) => {
        const d = r.data;
        if (d.status === "rate_limited") {
          message.warning(t("refresh.rateLimited"));
          fetchData(m);
          return;
        }
        setSections(mapSectionsResponse(d));
        message.success(t("refresh.success"));
      })
      .catch(() => {
        message.error(t("refresh.failed"));
        fetchData(m);
      })
      .finally(() => setGlobalRefreshing(false));
  };

  const retrySection = (m: string, sectionName: string) => {
    setRefreshingSection(sectionName);
    setSections((prev) => ({
      ...prev,
      [sectionName]: { ...prev[sectionName], status: "loading" },
    }));
    refreshSection(m, sectionName)
      .then((r) => {
        const d = r.data;
        if (d.status === "rate_limited") {
          message.warning(t("refresh.rateLimited"));
          setSections((prev) => ({
            ...prev,
            [sectionName]: { ...prev[sectionName], status: "error" },
          }));
          return;
        }
        const sectionResult: SectionState = {
          status: d.status === "cached" ? "ok" : d.status,
          data: d.data,
          error: d.error,
          updatedAt: d.updated_at,
        };
        setSections((prev) => ({ ...prev, [sectionName]: sectionResult }));
        if (d.status === "error") {
          message.error(t("refresh.failed"));
        }
      })
      .catch(() => {
        setSections((prev) => ({
          ...prev,
          [sectionName]: { ...prev[sectionName], status: "error" },
        }));
        message.error(t("refresh.failed"));
      })
      .finally(() => setRefreshingSection(null));
  };

  useEffect(() => {
    fetchData(market);
  }, [market]);

  useEffect(() => {
    if (initialLoading) return;
    const handleScroll = () => {
      if (spyDisabledRef.current) return;
      const anchor = 120;
      for (const s of SECTIONS) {
        const el = sectionRefs.current.get(s.id);
        if (!el) continue;
        const rect = el.getBoundingClientRect();
        if (rect.top <= anchor && rect.bottom > anchor) {
          setActiveId(s.id);
          break;
        }
      }
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener("scroll", handleScroll);
  }, [initialLoading, sections]);

  const sectionRef = useCallback((id: string) => (el: HTMLElement | null) => {
    if (el) sectionRefs.current.set(id, el);
    else sectionRefs.current.delete(id);
  }, []);

  const handleNavigate = (id: string) => {
    const el = sectionRefs.current.get(id);
    if (!el) return;
    spyDisabledRef.current = true;
    setActiveId(id);
    const offset = 120;
    const top = el.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ behavior: "smooth", top });
    setTimeout(() => { spyDisabledRef.current = false; }, 500);
  };

  const indices = sections.indices?.data || [];
  const holdings = sections.holdings?.data || [];
  const news = sections.news?.data || [];
  const recommendations = sections.recommendations?.data || [];
  const calendar = sections.economic_calendar?.data || [];
  const earningsCalendar = sections.earnings_calendar?.data || [];
  const earningsSymbols = new Set<string>(
    earningsCalendar.filter((e: any) => e.days_away <= 7).map((e: any) => e.symbol)
  );

  const latestUpdatedAt = Object.values(sections)
    .map((s) => s.updatedAt)
    .filter(Boolean)
    .sort()
    .pop();

  const visibleSections = SECTIONS.filter((s) => {
    if (s.id === "news") return news.length > 0;
    return true;
  });

  const renderSectionContent = (
    sectionName: string,
    content: React.ReactNode,
  ) => {
    const state = sections[sectionName];
    if (!state || state.status === "idle" || state.status === "loading") {
      return <SectionSkeleton />;
    }
    if (state.status === "error") {
      return (
        <SectionErrorCard
          error={state.error!}
          onRetry={() => retrySection(market, sectionName)}
          loading={refreshingSection === sectionName}
        />
      );
    }
    return content;
  };

  return (
    <div style={{ minHeight: "100vh", background: "#000" }}>
      <Header market={market} onMarketChange={setMarket} onRefresh={() => refreshData(market)} refreshing={globalRefreshing} updatedAt={formatUpdatedAt(latestUpdatedAt)} onOpenPreferences={() => setPrefsOpen(true)} />
      <ProgressBar active={globalRefreshing} />
      {!initialLoading && (
        <SectionNav sections={visibleSections} activeId={activeId} onNavigate={handleNavigate} />
      )}
      <main
        style={{
          maxWidth: 1280,
          margin: "0 auto",
          padding: "40px 40px 80px",
          display: "flex",
          flexDirection: "column",
          gap: 48,
        }}
      >
        {initialLoading ? (
          <>
            <SectionSkeleton />
            <SectionSkeleton />
            <SectionSkeleton />
            <SectionSkeleton />
            <SectionSkeleton />
          </>
        ) : initialError ? (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <p style={{ color: "#8d969e", fontSize: 16, marginBottom: 16 }}>{t("error.loadFailed")}</p>
            <button
              onClick={() => fetchData(market)}
              style={{ background: "#494fdf", color: "#fff", border: "none", borderRadius: 8, padding: "8px 24px", cursor: "pointer", fontSize: 14 }}
            >
              {t("error.retry")}
            </button>
          </div>
        ) : (
          <>
            <section id="overview" ref={sectionRef("overview")}>
              {renderSectionContent("indices", (
                <>
                  <MarketOverview indices={indices} />
                  {calendar.length > 0 && (
                    <div style={{ marginTop: 32 }}>
                      {renderSectionContent("economic_calendar",
                        <EconomicCalendar calendar={calendar} />,
                      )}
                    </div>
                  )}
                  <div style={{ marginTop: 24 }}>
                    <MarketAnalysisPanel indices={indices} calendar={calendar} market={market} />
                  </div>
                </>
              ))}
            </section>
            {news.length > 0 && (
              <section id="news" ref={sectionRef("news")}>
                {renderSectionContent("news", <NewsList news={news} />)}
              </section>
            )}
            <section id="watchlist" ref={sectionRef("watchlist")}>
              {renderSectionContent("holdings",
                <WatchlistSection holdings={holdings.map((h: any) => ({ ...h, earnings_approaching: earningsSymbols.has(h.symbol) }))} market={market} onRefresh={() => fetchData(market)} />,
              )}
            </section>
            <section id="recommendations" ref={sectionRef("recommendations")}>
              {renderSectionContent("recommendations",
                <RecommendationsSection recommendations={recommendations.map((r: any) => ({ ...r, earnings_approaching: earningsSymbols.has(r.symbol) }))} market={market} />,
              )}
            </section>
          </>
        )}
      </main>
      <PreferencesModal open={prefsOpen} onClose={() => setPrefsOpen(false)} />
      {!initialLoading && !initialError && <ChatWidget market={market} data={{ indices, holdings, recommendations, news, economic_calendar: calendar, earnings_calendar: earningsCalendar }} />}
    </div>
  );
}
