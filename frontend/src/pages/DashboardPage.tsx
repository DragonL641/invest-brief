import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton, App } from "antd";
import Header from "../components/Header";
import MarketOverview from "../components/MarketOverview";
import WatchlistSection from "../components/WatchlistSection";
import RecommendationsSection from "../components/RecommendationsSection";
import NewsList from "../components/NewsList";
import EconomicCalendar from "../components/EconomicCalendar";
import ChatFab from "../components/ChatFab";
import { getMarketData, refreshMarket } from "../api/data";
import { useAuth } from "../hooks/useAuth";

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

function formatUpdatedAt(iso: string | undefined, locale: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const y = d.getFullYear();
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return locale === "ko-KR"
    ? `${y}.${m}.${day} ${hh}:${mm}`
    : `${y}年${m}月${day}日 ${hh}:${mm}`;
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
  useAuth();
  const { t, i18n } = useTranslation();
  const { message } = App.useApp();

  const fetchData = (m: string) => {
    setLoading(true);
    setError(false);
    getMarketData(m)
      .then((r) => {
        setData(r.data);
        setError(false);
      })
      .catch(() => {
        setError(true);
      })
      .finally(() => setLoading(false));
  };

  const refreshData = (m: string) => {
    setRefreshing(true);
    setRefreshError(false);
    refreshMarket(m)
      .then((r) => {
        const d = r.data;
        if (d.status === "rate_limited") {
          message.warning(t("refresh.rateLimited"));
          return;
        }
        if (d.error) {
          message.error(t("refresh.failed"));
          return;
        }
        setData(d);
        setError(false);
        message.success(t("refresh.success"));
      })
      .catch(() => {
        setRefreshError(true);
        message.error(t("refresh.failed"));
        setTimeout(() => setRefreshError(false), 400);
      })
      .finally(() => setRefreshing(false));
  };

  useEffect(() => {
    fetchData(market);
  }, [market]);

  const indices = data?.indices || [];
  const holdings = data?.holdings || [];
  const news = data?.news || [];
  const recommendations = data?.recommendations || [];
  const calendar = data?.economic_calendar || [];

  return (
    <div style={{ minHeight: "100vh", background: "#000" }}>
      <Header market={market} onMarketChange={setMarket} onRefresh={() => refreshData(market)} refreshing={refreshing} updatedAt={formatUpdatedAt(data?.updated_at, i18n.language)} />
      <ProgressBar active={refreshing} error={refreshError} />
      <div
        style={{
          maxWidth: 1200,
          margin: "0 auto",
          padding: "32px 40px",
          display: "flex",
          flexDirection: "column",
          gap: 32,
        }}
      >
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
            <p style={{ color: "#8d969e", fontSize: 16, marginBottom: 16 }}>数据加载失败，请稍后重试</p>
            <button
              onClick={() => fetchData(market)}
              style={{ background: "#494fdf", color: "#fff", border: "none", borderRadius: 8, padding: "8px 24px", cursor: "pointer", fontSize: 14 }}
            >
              重试
            </button>
          </div>
        ) : (
          <>
            <MarketOverview indices={indices} />
            <WatchlistSection holdings={holdings} market={market} />
            <NewsList news={news} />
            <RecommendationsSection recommendations={recommendations} market={market} />
            <EconomicCalendar calendar={calendar} />
          </>
        )}
      </div>
      {!loading && data && <ChatFab market={market} data={data} />}
    </div>
  );
}
