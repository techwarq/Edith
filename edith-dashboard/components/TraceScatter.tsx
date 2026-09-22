"use client";

import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Trace } from "@/lib/types";

export function TraceScatter({ traces }: { traces: Trace[] }) {
  const points = traces
    .filter((t) => t.duration_ms != null && t.cost_usd != null)
    .map((t) => ({
      duration_s: (t.duration_ms ?? 0) / 1000,
      cost_cents: (t.cost_usd ?? 0) * 100,
      status: t.status,
      id: t.id,
      tools: t.tools_used.join(", ") || "none",
    }));

  const ok = points.filter((p) => p.status !== "error");
  const err = points.filter((p) => p.status === "error");

  const medianDuration = median(points.map((p) => p.duration_s));
  const medianCost = median(points.map((p) => p.cost_cents));

  if (points.length === 0) {
    return <EmptyChart label="no recent traces yet" />;
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="var(--panel-border)" strokeDasharray="3 3" />
        <XAxis
          type="number"
          dataKey="duration_s"
          name="duration"
          unit="s"
          tick={{ fill: "var(--muted)", fontSize: 10 }}
          stroke="var(--panel-border)"
        />
        <YAxis
          type="number"
          dataKey="cost_cents"
          name="cost"
          unit="¢"
          tick={{ fill: "var(--muted)", fontSize: 10 }}
          stroke="var(--panel-border)"
        />
        <ZAxis range={[40, 40]} />
        {medianDuration != null && <ReferenceLine x={medianDuration} stroke="var(--panel-border)" strokeDasharray="2 4" />}
        {medianCost != null && <ReferenceLine y={medianCost} stroke="var(--panel-border)" strokeDasharray="2 4" />}
        <Tooltip
          cursor={{ strokeDasharray: "3 3", stroke: "var(--panel-border)" }}
          contentStyle={{ background: "#0c1018", border: "1px solid var(--panel-border)", fontSize: 11, borderRadius: 6 }}
          labelStyle={{ color: "var(--muted)" }}
          formatter={(value, name) => [typeof value === "number" ? value.toFixed(2) : String(value), String(name)]}
        />
        <Scatter name="ok" data={ok} fill="var(--accent-blue)" fillOpacity={0.75} />
        <Scatter name="error" data={err} fill="var(--accent-red)" fillOpacity={0.9} />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

function median(nums: number[]): number | null {
  if (!nums.length) return null;
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function EmptyChart({ label }: { label: string }) {
  return <div className="h-[220px] flex items-center justify-center text-xs text-muted">{label}</div>;
}
