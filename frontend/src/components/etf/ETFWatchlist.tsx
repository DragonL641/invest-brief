import React, { useState, useEffect, useCallback } from "react";
import { Button, Input, message, Empty, Spin, Modal } from "antd";
import { PlusOutlined, DeleteOutlined, SearchOutlined } from "@ant-design/icons";
import { getWatchlist, addToWatchlist, removeFromWatchlist, analyzeBatch, searchETF } from "../../api/etf";
import ETFCard from "./ETFCard";

interface ETFItem {
  symbol: string;
  name: string;
  price?: number;
  change_pct?: number;
  premium_rate?: number;
  main_net_flow?: number;
  ai_conclusion?: string;
  dimension_summary?: Record<string, Record<string, number>>;
  error?: boolean;
}

function ETFWatchlist({ onViewDetail }: { onViewDetail: (symbol: string) => void }) {
  const [watchlist, setWatchlist] = useState<ETFItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [searchVal, setSearchVal] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);

  const fetchWatchlist = useCallback(async () => {
    setLoading(true);
    try {
      const wlRes = await getWatchlist();
      const wl = wlRes.data?.watchlist || [];
      const symbols = wl.map((w: any) => w.symbol).join(",");

      let batch: any[] = [];
      if (symbols) {
        try {
          const batchRes = await analyzeBatch(symbols);
          batch = batchRes.data?.results || [];
        } catch {
          // batch analysis failed, continue without it
        }
      }

      const batchMap = new Map(batch.map((b: any) => [b.symbol, b]));
      const items: ETFItem[] = wl.map((w: any) => {
        const b = batchMap.get(w.symbol) || {};
        return { symbol: w.symbol, name: w.name, ...b };
      });
      setWatchlist(items);
    } catch {
      setWatchlist([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchWatchlist(); }, [fetchWatchlist]);

  const handleSearch = async () => {
    const q = searchVal.trim();
    if (!q) return;
    setSearching(true);
    try {
      const res = await searchETF(q);
      const results = res.data?.results || [];
      setSearchResults(results);
      if (results.length === 0) message.info("未找到匹配的 ETF");
    } catch {
      setSearchResults([]);
      message.error("搜索失败");
    } finally {
      setSearching(false);
    }
  };

  const handleConfirmAdd = async (symbol: string) => {
    try {
      await addToWatchlist(symbol);
      message.success("已添加");
      setModalOpen(false);
      setSearchVal("");
      setSearchResults([]);
      fetchWatchlist();
    } catch {
      message.error("添加失败");
    }
  };

  const handleRemove = async (symbol: string) => {
    try {
      await removeFromWatchlist(symbol);
      setWatchlist((prev) => prev.filter((w) => w.symbol !== symbol));
    } catch {
      message.error("移除失败");
    }
  };

  const closeModal = () => {
    setModalOpen(false);
    setSearchVal("");
    setSearchResults([]);
  };

  if (loading) return <Spin style={{ display: "block", margin: "40px auto" }} />;

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          添加自选
        </Button>
      </div>

      {watchlist.length === 0 ? (
        <Empty description="暂无自选ETF，请添加" style={{ marginTop: 40 }} />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}>
          {watchlist.map((etf) => (
            <div key={etf.symbol} style={{ position: "relative" }}>
              <ETFCard
                symbol={etf.symbol}
                name={etf.name}
                price={etf.price}
                change_pct={etf.change_pct}
                premium_rate={etf.premium_rate}
                main_net_flow={etf.main_net_flow}
                ai_conclusion={etf.ai_conclusion}
                dimension_summary={etf.dimension_summary}
                onViewDetail={onViewDetail}
              />
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={(e) => { e.stopPropagation(); handleRemove(etf.symbol); }}
                style={{ position: "absolute", top: 8, right: 8, opacity: 0.5, zIndex: 1 }}
              />
            </div>
          ))}
        </div>
      )}

      <Modal
        open={modalOpen}
        onCancel={closeModal}
        title="添加 ETF 自选"
        footer={null}
        styles={{
          header: { background: "#111", borderBottom: "1px solid rgba(255,255,255,0.08)" },
          body: { background: "#111", padding: "16px 24px" },
        }}
      >
        <Input.Search
          placeholder="输入 ETF 代码或名称搜索"
          value={searchVal}
          onChange={(e) => setSearchVal(e.target.value)}
          onSearch={handleSearch}
          loading={searching}
          enterButton={<SearchOutlined />}
          style={{ marginBottom: 16 }}
        />
        {searchResults.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {searchResults.map((r: any) => {
              const up = (r.change_pct ?? 0) >= 0;
              return (
                <div
                  key={r.symbol}
                  onClick={() => handleConfirmAdd(r.symbol)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 12px",
                    background: "rgba(255,255,255,0.04)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 8,
                    cursor: "pointer",
                    transition: "background 0.2s",
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,0.08)"; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,0.04)"; }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ color: "#fff", fontWeight: 600, fontSize: 14 }}>{r.name}</div>
                    <div style={{ color: "#8d969e", fontSize: 12, marginTop: 2 }}>{r.symbol}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ color: up ? "#52c41a" : "#cf1322", fontWeight: 600 }}>
                      ¥{r.price?.toFixed(3) ?? "-"}
                    </div>
                    <div style={{ color: up ? "#52c41a" : "#cf1322", fontSize: 12 }}>
                      {up ? "+" : ""}{r.change_pct?.toFixed(2) ?? "-"}%
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Modal>
    </div>
  );
}

export default React.memo(ETFWatchlist);
