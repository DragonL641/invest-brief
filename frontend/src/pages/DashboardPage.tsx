import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton, App } from "antd";
import Header from "../components/Header";
import MarketOverview from "../components/MarketOverview";
import WatchlistSection from "../components/WatchlistSection";
import RecommendationsSection from "../components/RecommendationsSection";
import NewsList from "../components/NewsList";
import EconomicCalendar from "../components/EconomicCalendar";
import ChatFab from "../components/ChatFab";
import SectionNav from "../components/SectionNav";
import type { SectionDef } from "../components/SectionNav";
import DataErrorBanner from "../components/DataErrorBanner";
import type { FetchError } from "../components/DataErrorBanner";
import { getMarketData, refreshMarket } from "../api/data";
import { useAuth } from "../hooks/useAuth";

const SECTIONS: SectionDef[] = [
  { id: "overview", titleKey: "market.overview" },
  { id: "news", titleKey: "market.news" },
  { id: "calendar", titleKey: "market.calendar" },
  { id: "watchlist", titleKey: "watchlist.title" },
  { id: "recommendations", titleKey: "recommendations.title" },
];

function ProgressBar({ active, error }: { active: boolean; error?: boolean }) {
  if (!active && !error) return null;
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
          width: active ? "20%" : "100%",
          height: "100%",
          background: error ? "#ff4d4f" : "#494fdf",
          animation: active ? "indeterminate 1.2s ease-in-out infinite" : "none",
          transition: active ? "none" : "opacity 0.4s ease-out",
          opacity: active ? 1 : 0,
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
    <div style={{ background: "#16181a", borderRadius: 20, padding: 24 }}>
      <Skeleton active paragraph={{ rows: 2 }} title={{ width: "40%" }} />
    </div>
  );
}

export default function DashboardPage() {
  const [market, setMarket] = useState<"us" | "cn">("us");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [fetchErrors, setFetchErrors] = useState<FetchError[]>([]);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [activeId, setActiveId] = useState(SECTIONS[0].id);
  const spyDisabledRef = useRef(false);
  const sectionRefs = useRef<Map<string, HTMLElement>>(new Map());
  useAuth();
  const { t } = useTranslation();
  const { message } = App.useApp();

  const fetchData = (m: string) => {
    setLoading(true);
    setError(false);
    setBannerDismissed(false);
    getMarketData(m)
      .then((r) => {
        setData(r.data);
        setError(false);
        setFetchErrors(r.data?.errors || []);
      })
      .catch(() => {
        setError(true);
        setFetchErrors([]);
      })
      .finally(() => setLoading(false));
  };

  const refreshData = (m: string) => {
    setRefreshing(true);
    setRefreshError(false);
    setBannerDismissed(false);
    refreshMarket(m)
      .then((r) => {
        const d = r.data;
        if (d.status === "rate_limited") {
          message.warning(t("refresh.rateLimited"));
          return;
        }
        if (d.error) {
          message.error(t("refresh.failed"));
          setFetchErrors(d.errors || []);
          return;
        }
        setData(d);
        setError(false);
        setFetchErrors(d.errors || []);
        message.success(t("refresh.success"));
      })
      .catch(() => {
        setRefreshError(true);
        setFetchErrors([]);
        message.error(t("refresh.failed"));
        setTimeout(() => setRefreshError(false), 400);
      })
      .finally(() => setRefreshing(false));
  };

  useEffect(() => {
    fetchData(market);
  }, [market]);

  // Scroll spy via scroll event
  useEffect(() => {
    if (loading) return;
    const handleScroll = () => {
      if (spyDisabledRef.current) return;
      const anchor = 100;
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
  }, [loading, data]);

  const sectionRef = useCallback((id: string) => (el: HTMLElement | null) => {
    if (el) sectionRefs.current.set(id, el);
    else sectionRefs.current.delete(id);
  }, []);

  const handleNavigate = (id: string) => {
    const el = sectionRefs.current.get(id);
    if (!el) return;
    spyDisabledRef.current = true;
    setActiveId(id);
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    setTimeout(() => { spyDisabledRef.current = false; }, 500);
  };

  const indices = data?.indices || [];
  const holdings = data?.holdings || [];
  const news = data?.news || [];
  const recommendations = data?.recommendations || [];
  const calendar = data?.economic_calendar || [];

  // Only show nav items for sections that have data
  const visibleSections = SECTIONS.filter((s) => {
    if (s.id === "news") return news.length > 0;
    if (s.id === "calendar") return calendar.length > 0;
    return true;
  });

  return (
    <div style={{ minHeight: "100vh", background: "#000" }}>
      <Header market={market} onMarketChange={setMarket} onRefresh={() => refreshData(market)} refreshing={refreshing} updatedAt={formatUpdatedAt(data?.updated_at)} />
      <ProgressBar active={refreshing} error={refreshError} />
      <style>{`
        @media (max-width: 768px) {
          .dashboard-sidebar { display: none !important; }
          .dashboard-main { margin-left: 0 !important; }
        }
      `}</style>
      <div style={{ display: "flex", maxWidth: 1400, margin: "0 auto", padding: "0 40px" }}>
        <div className="dashboard-sidebar" style={{ background: "#0a0a0a" }}>
          {!loading && data && (
            <SectionNav sections={visibleSections} activeId={activeId} onNavigate={handleNavigate} />
          )}
        </div>
        <div
          className="dashboard-main"
          style={{
            flex: 1,
            maxWidth: 1200,
            padding: "32px 0 32px 40px",
            display: "flex",
            flexDirection: "column",
            gap: 32,
          }}
        >
          {!loading && fetchErrors.length > 0 && !bannerDismissed && (
            <DataErrorBanner errors={fetchErrors} onClose={() => setBannerDismissed(true)} />
          )}
          {loading ? (
            <>
              <SectionSkeleton />
              <SectionSkeleton />
              <SectionSkeleton />
              <SectionSkeleton />
              <SectionSkeleton />
            </>
          ) : error && !data ? (
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
                <MarketOverview indices={indices} />
              </section>
              {news.length > 0 && (
                <section id="news" ref={sectionRef("news")}>
                  <NewsList news={news} />
                </section>
              )}
              {calendar.length > 0 && (
                <section id="calendar" ref={sectionRef("calendar")}>
                  <EconomicCalendar calendar={calendar} />
                </section>
              )}
              <section id="watchlist" ref={sectionRef("watchlist")}>
                <WatchlistSection holdings={holdings} market={market} />
              </section>
              <section id="recommendations" ref={sectionRef("recommendations")}>
                <RecommendationsSection recommendations={recommendations} market={market} />
              </section>
            </>
          )}
        </div>
      </div>
      {!loading && data && <ChatFab market={market} data={data} />}
    </div>
  );
}
