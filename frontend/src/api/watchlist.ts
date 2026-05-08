import client from "./client";
export const getWatchlist = () => client.get("/watchlist");
export const addWatchlist = (symbol: string, name: string, market: string) => client.post("/watchlist", { symbol, name, market });
export const deleteWatchlist = (id: string) => client.delete(`/watchlist/${id}`);
