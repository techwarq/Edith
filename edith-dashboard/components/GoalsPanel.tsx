"use client";

import { Goal } from "@/lib/types";

export function GoalsPanel({ goals }: { goals: Goal[] }) {
  const active = goals.filter((g) => g.status === "active");

  if (active.length === 0) {
    return <div className="py-6 text-center text-xs text-muted">no active goals right now</div>;
  }

  return (
    <div className="flex flex-col gap-4">
      {active.map((g) => {
        const total = g.milestones.length;
        const done = g.milestones.filter((m) => !!m.done).length;
        const pct = total > 0 ? Math.round((done / total) * 100) : null;
        const next = g.milestones.find((m) => !m.done);

        return (
          <div key={g.id} className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[13px] font-medium text-foreground">{g.title}</span>
              <span className="text-[11px] text-muted tabular-nums shrink-0">{pct != null ? `${pct}%` : "active"}</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-panel-border overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-accent-blue to-accent-green transition-[width] duration-700"
                style={{ width: pct != null ? `${pct}%` : "100%", opacity: pct != null ? 1 : 0.35 }}
              />
            </div>
            <span className="text-[11px] text-muted">
              {next ? `Next: ${next.title}` : g.description ? truncate(g.description, 90) : g.target_date ? `by ${g.target_date}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}
