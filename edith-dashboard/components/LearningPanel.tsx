"use client";

import { PerformanceTrendPoint } from "@/lib/types";

function Delta({ today, yesterday, invert = false }: { today: number; yesterday: number; invert?: boolean }) {
  const diff = today - yesterday;
  if (Math.abs(diff) < 1e-9) return <span className="text-[10px] text-muted">flat</span>;
  const improved = invert ? diff > 0 : diff < 0;
  return (
    <span className={`text-[10px] ${improved ? "text-accent-green" : "text-accent-red"}`}>
      {diff > 0 ? "↑" : "↓"} {Math.abs(diff * 100).toFixed(1)}pt
    </span>
  );
}

export function LearningPanel({ trend }: { trend: PerformanceTrendPoint[] }) {
  const withTurns = trend.filter((t) => t.turn_count > 0);
  if (withTurns.length < 2) {
    return <div className="py-6 text-center text-xs text-muted">not enough days of data yet</div>;
  }
  const today = withTurns.at(-1)!;
  const yesterday = withTurns.at(-2)!;

  const rows = [
    { label: "Error rate", today: today.error_rate, yesterday: yesterday.error_rate },
    { label: "Tool hallucination", today: today.tool_hallucination_rate, yesterday: yesterday.tool_hallucination_rate },
    { label: "Redundant calls", today: today.redundant_tool_call_rate, yesterday: yesterday.redundant_tool_call_rate },
  ];

  return (
    <div className="flex flex-col gap-3">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between">
          <span className="text-[11px] text-muted">{r.label}</span>
          <div className="flex items-center gap-2 tabular-nums">
            <span className="text-[11px] text-foreground/60">{(r.yesterday * 100).toFixed(1)}%</span>
            <span className="text-muted">→</span>
            <span className="text-[11px] text-foreground">{(r.today * 100).toFixed(1)}%</span>
            <Delta today={r.today} yesterday={r.yesterday} />
          </div>
        </div>
      ))}
    </div>
  );
}
