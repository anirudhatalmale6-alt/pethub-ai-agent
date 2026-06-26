"use client";

import { useState, useEffect } from "react";
import { login, register, logout } from "@/lib/api";
import ChatApp from "@/components/ChatApp";

export default function Home() {
  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const stored = localStorage.getItem("user");
    if (stored) {
      try { setUser(JSON.parse(stored)); } catch {}
    }
    setLoading(false);
  }, []);

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const fn = authMode === "login" ? login : register;
      const data = await fn(username, password);
      setUser(data);
    } catch (err: any) {
      setError(err.message || "Authentication failed");
    }
  };

  const handleLogout = () => {
    logout();
    setUser(null);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-surface-950">
        <div className="w-full max-w-sm p-8">
          <div className="text-center mb-8">
            <div className="w-12 h-12 bg-brand-500 rounded-xl mx-auto mb-4 flex items-center justify-center">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <h1 className="text-xl font-semibold text-white">PetHub AI Agent</h1>
            <p className="text-sm text-surface-300 mt-1">Sign in to your operations dashboard</p>
          </div>

          <form onSubmit={handleAuth} className="space-y-4">
            <input
              type="text"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-3 bg-surface-900 border border-surface-200/10 rounded-lg text-white placeholder:text-surface-300 focus:outline-none focus:border-brand-500 transition"
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 bg-surface-900 border border-surface-200/10 rounded-lg text-white placeholder:text-surface-300 focus:outline-none focus:border-brand-500 transition"
            />
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <button
              type="submit"
              className="w-full py-3 bg-brand-500 hover:bg-brand-600 text-white rounded-lg font-medium transition"
            >
              {authMode === "login" ? "Sign In" : "Create Account"}
            </button>
          </form>

          <p className="text-center text-sm text-surface-300 mt-4">
            {authMode === "login" ? "No account? " : "Already have an account? "}
            <button
              onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
              className="text-brand-500 hover:underline"
            >
              {authMode === "login" ? "Create one" : "Sign in"}
            </button>
          </p>
        </div>
      </div>
    );
  }

  return <ChatApp user={user} onLogout={handleLogout} />;
}
