import client from "./client";
export const getMarketData = (market: string) => client.get(`/data/${market}`);
export const refreshMarket = (market: string) => client.post(`/data/${market}/refresh`);
export const getStatus = () => client.get("/data/status");
