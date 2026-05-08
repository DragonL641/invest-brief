import { useState, useEffect } from "react";
import { Spin } from "antd";
import Header from "../components/Header";
import MarketOverview from "../components/MarketOverview";
import WatchlistSection from "../components/WatchlistSection";
import RecommendationsSection from "../components/RecommendationsSection";
import NewsList from "../components/NewsList";
import EconomicCalendar from "../components/EconomicCalendar";
import ChatFab from "../components/ChatFab";
import { getMarketData } from "../api/data";
import { useAuth } from "../hooks/useAuth";

export default function DashboardPage() {
  const [market, setMarket] = useState<"us" | "cn">("us");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  useAuth();

  const fetchData = (m: string) => {
    setLoading(true);
    getMarketData(m)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchData(market);
  }, [market]);

  if (loading || !data) {
    return <Spin size="large" style={{ display: "block", margin: "200px auto" }} />;
  }

  return (
    <div style={{ minHeight: "100vh", background: "#000" }}>
      <Header market={market} onMarketChange={setMarket} updatedAt={data.updated_at} />
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
        <MarketOverview indices={data.indices || []} />
        <WatchlistSection holdings={data.holdings || []} market={market} />
        <NewsList news={data.news || []} />
        <RecommendationsSection recommendations={data.recommendations || []} market={market} />
        <EconomicCalendar calendar={data.economic_calendar || []} />
      </div>
      <ChatFab market={market} data={data} />
    </div>
  );
}
