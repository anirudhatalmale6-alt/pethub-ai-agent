"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

async function apiFetch(path: string) {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

interface ToolStat {
  tool_name: string;
  total_executions: number;
  succeeded: number;
  failed: number;
  success_rate: number;
  avg_duration_ms: number;
}

export default function Dashboard() {
  const router = useRouter();
  const [health, setHealth] = useState<any>(null);
  const [usage, setUsage] = useState<any>(null);
  const [tools, setTools] = useState<any>(null);
  const [costs, setCosts] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [h, u, t, c] = await Promise.all([
        apiFetch("/api/monitoring/health"),
        apiFetch("/api/monitoring/usage?days=30"),
        apiFetch("/api/monitoring/tools?days=30"),
        apiFetch("/api/monitoring/costs?days=30"),
      ]);
      setHealth(h);
      setUsage(u);
      setTools(t);
      setCosts(c);
    } catch (err: any) {
      if (err.message === "unauthorized") router.push("/");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    if (!getToken()) { router.push("/"); return; }
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData, router]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-surface-950">
        <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-950 text-surface-200 p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-white">System Dashboard</h1>
            <p className="text-sm text-surface-300 mt-1">Real-time monitoring and analytics</p>
          </div>
          <div className="flex gap-3">
            <button onClick={loadData} className="px-4 py-2 bg-surface-900 border border-surface-200/10 rounded-lg text-sm text-surface-300 hover:text-white transition">
              Refresh
            </button>
            <a href="/" className="px-4 py-2 bg-brand-500 hover:bg-brand-600 text-white rounded-lg text-sm transition">
              Back to Chat
            </a>
          </div>
        </div>

        {/* System Health */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <StatCard
            label="System Status"
            value={health?.status === "healthy" ? "Healthy" : "Degraded"}
            color={health?.status === "healthy" ? "text-green-400" : "text-red-400"}
            sub={`Uptime: ${health?.uptime || "..."}`}
          />
          <StatCard label="Database" value={health?.services?.database || "..."} color={health?.services?.database === "connected" ? "text-green-400" : "text-red-400"} sub="PostgreSQL" />
          <StatCard label="Redis" value={health?.services?.redis || "..."} color={health?.services?.redis === "connected" ? "text-green-400" : "text-red-400"} sub="Task Queue" />
          <StatCard label="AI Model" value={health?.services?.openai_model || "..."} color="text-brand-500" sub={health?.environment || ""} />
        </div>

        {/* Usage & Costs */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="bg-surface-900 border border-surface-200/5 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-surface-300 uppercase tracking-wider mb-4">Usage (Last 30 Days)</h3>
            <div className="grid grid-cols-2 gap-4">
              <MiniStat label="Conversations" value={usage?.conversations || 0} />
              <MiniStat label="Total Messages" value={usage?.total_messages || 0} />
              <MiniStat label="User Messages" value={usage?.user_messages || 0} />
              <MiniStat label="AI Responses" value={usage?.assistant_messages || 0} />
              <MiniStat label="Tool Calls" value={usage?.tool_messages || 0} />
              <MiniStat label="Avg Msgs/Conv" value={usage?.avg_messages_per_conversation || 0} />
            </div>
          </div>

          <div className="bg-surface-900 border border-surface-200/5 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-surface-300 uppercase tracking-wider mb-4">Cost Estimates (Last 30 Days)</h3>
            <div className="grid grid-cols-2 gap-4">
              <MiniStat label="Input Tokens" value={(costs?.estimated_input_tokens || 0).toLocaleString()} />
              <MiniStat label="Output Tokens" value={(costs?.estimated_output_tokens || 0).toLocaleString()} />
              <MiniStat label="Input Cost" value={`$${costs?.cost_breakdown?.input_cost_usd || "0.00"}`} />
              <MiniStat label="Output Cost" value={`$${costs?.cost_breakdown?.output_cost_usd || "0.00"}`} />
              <BigStat label="Total Spend" value={`$${costs?.cost_breakdown?.total_cost_usd || "0.00"}`} />
              <BigStat label="Monthly Projection" value={`$${costs?.projections?.monthly_projected_usd || "0.00"}`} />
            </div>
            <p className="text-xs text-surface-300/50 mt-3">{costs?.pricing_note || ""}</p>
          </div>
        </div>

        {/* Tool Analytics */}
        <div className="bg-surface-900 border border-surface-200/5 rounded-xl p-5 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-surface-300 uppercase tracking-wider">Tool Performance</h3>
            <span className="text-xs text-surface-300">
              {tools?.total_executions || 0} total executions | {tools?.overall_success_rate || 0}% success rate
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-surface-300/70 border-b border-surface-200/5">
                  <th className="pb-2 font-medium">Tool</th>
                  <th className="pb-2 font-medium text-center">Executions</th>
                  <th className="pb-2 font-medium text-center">Success</th>
                  <th className="pb-2 font-medium text-center">Failed</th>
                  <th className="pb-2 font-medium text-center">Rate</th>
                  <th className="pb-2 font-medium text-center">Avg Time</th>
                </tr>
              </thead>
              <tbody>
                {(tools?.tools || []).map((t: ToolStat) => (
                  <tr key={t.tool_name} className="border-b border-surface-200/5">
                    <td className="py-2.5 font-mono text-xs text-white">{t.tool_name}</td>
                    <td className="py-2.5 text-center">{t.total_executions}</td>
                    <td className="py-2.5 text-center text-green-400">{t.succeeded}</td>
                    <td className="py-2.5 text-center text-red-400">{t.failed || "-"}</td>
                    <td className="py-2.5 text-center">
                      <span className={t.success_rate >= 90 ? "text-green-400" : t.success_rate >= 70 ? "text-yellow-400" : "text-red-400"}>
                        {t.success_rate}%
                      </span>
                    </td>
                    <td className="py-2.5 text-center text-surface-300">{t.avg_duration_ms}ms</td>
                  </tr>
                ))}
                {(tools?.tools || []).length === 0 && (
                  <tr><td colSpan={6} className="py-4 text-center text-surface-300/50">No tool executions yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Recent Errors */}
        {tools?.recent_errors?.length > 0 && (
          <div className="bg-surface-900 border border-red-500/20 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-red-400 uppercase tracking-wider mb-4">Recent Errors</h3>
            <div className="space-y-2">
              {tools.recent_errors.map((err: any, i: number) => (
                <div key={i} className="flex items-start gap-3 text-xs p-3 bg-red-500/5 rounded-lg">
                  <span className="font-mono text-red-400 shrink-0">{err.tool}</span>
                  <span className="text-surface-300 flex-1">{err.error}</span>
                  <span className="text-surface-300/50 shrink-0">{new Date(err.time).toLocaleString()}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color, sub }: { label: string; value: string; color: string; sub: string }) {
  return (
    <div className="bg-surface-900 border border-surface-200/5 rounded-xl p-4">
      <div className="text-xs text-surface-300/70 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-semibold ${color}`}>{value}</div>
      <div className="text-xs text-surface-300/50 mt-1">{sub}</div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="text-xs text-surface-300/70">{label}</div>
      <div className="text-lg font-semibold text-white">{value}</div>
    </div>
  );
}

function BigStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-surface-300/70">{label}</div>
      <div className="text-xl font-bold text-brand-500">{value}</div>
    </div>
  );
}
