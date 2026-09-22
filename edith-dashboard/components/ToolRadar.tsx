"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { ToolStat } from "@/lib/types";
import { EmptyChart } from "./TraceScatter";

export function ToolRadar({ tools }: { tools: ToolStat[] }) {
  const top = [...tools].sort((a, b) => b.calls - a.calls).slice(0, 8);
  if (top.length === 0) return <EmptyChart label="no tool calls yet" />;

  const data = top.map((t) => ({
    tool: t.tool_name,
    calls: t.calls,
    reliabilityPct: Math.round((1 - t.error_rate) * 100),
  }));

  return (
    <ResponsiveContainer width="100%" height={240}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="var(--panel-border)" />
        <PolarAngleAxis dataKey="tool" tick={{ fill: "var(--muted)", fontSize: 10 }} />
        <PolarRadiusAxis tick={false} axisLine={false} />
        <Radar name="calls" dataKey="calls" stroke="var(--accent-blue)" fill="var(--accent-blue)" fillOpacity={0.32} />
        <Tooltip
          contentStyle={{ background: "#0c1018", border: "1px solid var(--panel-border)", fontSize: 11, borderRadius: 6 }}
          labelStyle={{ color: "var(--foreground)" }}
          formatter={(value, name, item) => {
            if (name === "calls") {
              const reliability = (item?.payload as { reliabilityPct?: number })?.reliabilityPct;
              return [`${value} calls · ${reliability ?? "–"}% reliable`, ""];
            }
            return [value, name];
          }}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}
