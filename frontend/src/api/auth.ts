import client from "./client";
export const login = (email: string, password: string) => client.post("/auth/login", { email, password });
export const logout = () => client.post("/auth/logout");
export const getMe = () => client.get("/auth/me");
