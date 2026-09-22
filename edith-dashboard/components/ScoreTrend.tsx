"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EvalRun } from "@/lib/types";
import { EmptyChart } from "./TraceScatter";

export function ScoreTrend({ runs }: { runs: EvalRun[] }) {
  if (runs.length === 0) return <EmptyChart label="no eval runs yet" />;

  const data = runs.map((r) => ({
    date: new Date(r.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    score: Math.round(r.avg_score * 1000) / 1000,
    passRate: r.case_count ? r.passed_count / r.case_count : 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--panel-border)" strokeDasharray="3 3" />
        <XAxis dataKey="date" tick={{ fill: "var(--muted)", fontSize: 10 }} stroke="var(--panel-border)" />
        <YAxis domain={[0, 1]} tick={{ fill: "var(--muted)", fontSize: 10 }} stroke="var(--panel-border)" />
        <Tooltip
          contentStyle={{ background: "#0c1018", border: "1px solid var(--panel-border)", fontSize: 11, borderRadius: 6 }}
          labelStyle={{ color: "var(--muted)" }}
        />
        <Line type="monotone" dataKey="score" name="avg score" stroke="var(--accent-blue)" strokeWidth={2} dot={{ r: 3 }} />
        <Line
          type="monotone"
          dataKey="passRate"
          name="pass rate"
          stroke="var(--accent-green)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
