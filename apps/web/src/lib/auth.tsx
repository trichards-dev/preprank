"use client";

import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8002";

interface User {
  id: number;
  email: string;
  first_name: string | null;
  last_name: string | null;
  subscription_tier: string;
  subscription_expires: string | null;
  is_admin?: boolean;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, firstName: string, lastName: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  getToken: () => string | null;
  isPremium: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const getToken = useCallback(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("preprank_token");
  }, []);

  const refreshUser = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setUser({ ...data, is_admin: data.is_admin ?? false });
      } else {
        localStorage.removeItem("preprank_token");
        localStorage.removeItem("preprank_refresh");
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const login = async (email: string, password: string) => {
    const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Login failed");
    }
    const data = await res.json();
    localStorage.setItem("preprank_token", data.access_token);
    localStorage.setItem("preprank_refresh", data.refresh_token);
    await refreshUser();
  };

  const register = async (email: string, password: string, firstName: string, lastName: string) => {
    const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, first_name: firstName, last_name: lastName }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Registration failed");
    }
    const data = await res.json();
    localStorage.setItem("preprank_token", data.access_token);
    localStorage.setItem("preprank_refresh", data.refresh_token);
    await refreshUser();
  };

  const logout = () => {
    localStorage.removeItem("preprank_token");
    localStorage.removeItem("preprank_refresh");
    setUser(null);
  };

  const isPremium = !!user && ["premium_monthly", "season_pass", "annual"].includes(user.subscription_tier);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser, getToken, isPremium }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
}
