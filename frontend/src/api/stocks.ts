import client from "./client";

export interface StockSearchResult {
  symbol: string;
  name: string;
}

export interface IndustryItem {
  key: string;
  label: string;
}

export const searchStocks = (q: string, market: string) =>
  client.get<{ results: StockSearchResult[] }>("/stocks/search", { params: { q, market } });

export const getIndustries = (market: string) =>
  client.get<{ industries: IndustryItem[] }>("/stocks/industries", { params: { market } });

export const addHolding = (market: string, symbol: string, name: string) =>
  client.post("/preferences/holding", { market, symbol, name });
