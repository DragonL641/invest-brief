import { createContext, useContext, useState, useEffect, type ReactNode } from "react";
import { getMe } from "../api/auth";

interface User { id: number; email: string; name: string; language: string; markets: Record<string, any>; }
interface AuthContextType { user: User | null; loading: boolean; setUser: (u: User | null) => void; }

const AuthContext = createContext<AuthContextType>({ user: null, loading: true, setUser: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { setLoading(false); return; }
    getMe().then((r) => setUser(r.data)).catch(() => localStorage.removeItem("token")).finally(() => setLoading(false));
  }, []);

  return <AuthContext.Provider value={{ user, loading, setUser }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
