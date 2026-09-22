"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { SpendingByDay, SpendingBySession } from "@/lib/types";
import { EmptyChart } from "./TraceScatter";

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function RetentionPanel({ byDay, bySession }: { byDay: SpendingByDay[]; bySession: SpendingBySession[] }) {
  const activeDays = byDay.filter((d) => d.trace_count > 0).length;
  const returningSessions = bySession.filter((s) => s.trace_count > 1).length;
  const avgTurnsPerSession = bySession.length
    ? bySession.reduce((sum, s) => sum + s.trace_count, 0) / bySession.length
    : 0;
  const lastActive = bySession[0]?.last_active;

  const chartData = byDay.map((d) => ({
    date: new Date(d.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    turns: d.trace_count,
  }));

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 text-center">
        <Stat label="sessions" value={String(bySession.length)} />
        <Stat label="active days" value={String(activeDays)} />
        <Stat label="repeat sessions" value={String(returningSessions)} />
        <Stat label="avg turns / session" value={avgTurnsPerSession.toFixed(1)} />
      </div>
      {lastActive && (
        <div className="flex items-center gap-1.5 text-[10px] text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-accent-green" />
          last session {timeAgo(lastActive)}
        </div>
      )}
      {chartData.length === 0 ? (
        <EmptyChart label="no activity yet" />
      ) : (
        <ResponsiveContainer width="100%" height={110}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <CartesianGrid stroke="var(--panel-border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: "var(--muted)", fontSize: 9 }} stroke="var(--panel-border)" />
            <YAxis tick={{ fill: "var(--muted)", fontSize: 9 }} stroke="var(--panel-border)" allowDecimals={false} />
            <Tooltip
              contentStyle={{ background: "#0c1018", border: "1px solid var(--panel-border)", fontSize: 11, borderRadius: 6 }}
              labelStyle={{ color: "var(--muted)" }}
              cursor={{ fill: "rgba(255,255,255,0.04)" }}
            />
            <Bar dataKey="turns" name="turns" fill="var(--accent-blue)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-panel-border bg-white/[0.02] py-2">
      <div className="text-base font-semibold tabular-nums">{value}</div>
      <div className="text-[9px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}
