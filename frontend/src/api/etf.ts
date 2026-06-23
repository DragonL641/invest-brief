import client from "./client";

export const searchETF = (q: string) =>
  client.get("/etf/search", { params: { q } });

export const analyzeETF = (symbol: string) =>
  client.get(`/etf/analyze/${symbol}`);

export const analyzeBatch = (symbols: string) =>
  client.get("/etf/batch", { params: { symbols } });

export const getWatchlist = () => client.get("/etf/watchlist");

export const addToWatchlist = (symbol: string) =>
  client.post("/etf/watchlist", { symbol });

export const removeFromWatchlist = (symbol: string) =>
  client.delete(`/etf/watchlist/${symbol}`);
