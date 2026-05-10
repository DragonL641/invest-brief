import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PlusOutlined } from "@ant-design/icons";
import { Modal, App } from "antd";
import StockCard from "./StockCard";
import StockSearch from "./StockSearch";
import { addHolding } from "../api/stocks";

interface WatchlistSectionProps {
  holdings: any[];
  market: string;
  onRefresh?: () => void;
}

export default function WatchlistSection({ holdings, market, onRefresh }: WatchlistSectionProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [modalOpen, setModalOpen] = useState(false);

  const handleAdd = async (symbol: string, name: string) => {
    try {
      await addHolding(market, symbol, name);
      message.success(t("watchlist.addSuccess"));
      setModalOpen(false);
      onRefresh?.();
    } catch (err: any) {
      if (err.response?.status === 409) {
        message.warning(t("watchlist.duplicate"));
      } else {
        message.error(t("watchlist.addFailed"));
      }
    }
  };

  return (
    <section>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <h2 style={{ color: "#fff", fontSize: 18, fontWeight: 600, margin: 0 }}>
          {t("watchlist.title")}
        </h2>
        <button
          onClick={() => setModalOpen(true)}
          style={{
            height: 32,
            background: "rgba(73,79,223,0.12)",
            border: "1px solid rgba(73,79,223,0.3)",
            borderRadius: 9999,
            color: "#494fdf",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "0 16px",
            transition: "background 0.2s",
          }}
        >
          <PlusOutlined style={{ fontSize: 12 }} />
          {t("watchlist.add")}
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {holdings.map((h, i) => (
          <StockCard key={h.symbol || i} stock={h} market={market} />
        ))}
        {holdings.length === 0 && (
          <div style={{ color: "#8d969e", fontSize: 14, padding: "40px 0", textAlign: "center" }}>
            --
          </div>
        )}
      </div>
      <Modal
        title={t("watchlist.addTitle")}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={480}
      >
        <StockSearch
          market={market as "us" | "cn"}
          existingSymbols={holdings.map((h) => h.symbol)}
          onAdd={handleAdd}
        />
      </Modal>
    </section>
  );
}
