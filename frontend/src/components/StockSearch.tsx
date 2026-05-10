import { useState, useCallback, useRef, useEffect } from "react";
import { Input, List, Button, Spin, App } from "antd";
import { PlusOutlined, CheckOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { searchStocks, type StockSearchResult } from "../api/stocks";

interface StockSearchProps {
  market: "us" | "cn";
  existingSymbols: string[];
  onAdd: (symbol: string, name: string) => void;
}

export default function StockSearch({ market, existingSymbols, onAdd }: StockSearchProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<StockSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const handleSearch = useCallback(
    (value: string) => {
      setQuery(value);
      clearTimeout(timerRef.current);
      if (!value.trim()) {
        setResults([]);
        return;
      }
      timerRef.current = setTimeout(async () => {
        setLoading(true);
        try {
          const { data } = await searchStocks(value.trim(), market);
          setResults(data.results);
        } catch {
          message.error(t("prefs.holdings.searchFailed"));
        } finally {
          setLoading(false);
        }
      }, 300);
    },
    [market, message, t]
  );

  const handleAdd = (item: StockSearchResult) => {
    if (existingSymbols.includes(item.symbol)) return;
    onAdd(item.symbol, item.name);
  };

  return (
    <div>
      <Input.Search
        placeholder={market === "us" ? t("prefs.holdings.searchUs") : t("prefs.holdings.searchCn")}
        value={query}
        onChange={(e) => handleSearch(e.target.value)}
        loading={loading}
        allowClear
      />
      {loading && <Spin style={{ display: "block", margin: "16px auto" }} />}
      {!loading && results.length > 0 && (
        <List
          size="small"
          style={{ maxHeight: 300, overflow: "auto", marginTop: 8 }}
          dataSource={results}
          renderItem={(item) => {
            const added = existingSymbols.includes(item.symbol);
            return (
              <List.Item
                style={{ padding: "4px 12px" }}
                actions={[
                  added ? (
                    <CheckOutlined style={{ color: "#52c41a" }} key="check" />
                  ) : (
                    <Button
                      type="link"
                      size="small"
                      icon={<PlusOutlined />}
                      onClick={() => handleAdd(item)}
                      key="add"
                    >
                      {t("prefs.holdings.add")}
                    </Button>
                  ),
                ]}
              >
                <span>
                  <strong>{item.symbol}</strong> — {item.name}
                </span>
              </List.Item>
            );
          }}
        />
      )}
    </div>
  );
}
