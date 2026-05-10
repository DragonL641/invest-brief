import client from "./client";
export const getMarketData = (market: string) => client.get(`/data/${market}`);
export const refreshMarket = (market: string) => client.post(`/data/${market}/refresh`);
export const refreshSection = (market: string, section: string) => client.post(`/data/${market}/refresh/${section}`);
export const getStatus = () => client.get("/data/status");
