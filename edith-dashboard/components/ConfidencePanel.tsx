"use client";

import { EvalMatrix } from "@/lib/useEvalMatrix";

export function ConfidencePanel({ matrix }: { matrix: EvalMatrix }) {
  const latestRun = matrix.runs.at(-1);
  if (!latestRun) {
    return <div className="py-6 text-center text-xs text-muted">no eval run yet</div>;
  }

  const rows = matrix.caseNames
    .map((name) => ({ name, cell: matrix.cell(name, latestRun.id) }))
    .filter((r) => r.cell != null)
    .sort((a, b) => (b.cell!.score ?? 0) - (a.cell!.score ?? 0));

  return (
    <div className="flex flex-col gap-2.5">
      {rows.map((r) => {
        const pct = Math.round(r.cell!.score * 100);
        const low = pct < 50;
        return (
          <div key={r.name} className="flex items-center gap-3">
            <span className="flex-1 text-[11px] text-foreground/85 truncate">{r.name.replaceAll("_", " ")}</span>
            <div className="w-20 h-1.5 rounded-full bg-panel-border overflow-hidden shrink-0">
              <div
                className="h-full rounded-full"
                style={{ width: `${pct}%`, background: low ? "var(--accent-red)" : "var(--accent-green)" }}
              />
            </div>
            <span
              className={`w-9 text-right text-[11px] tabular-nums shrink-0 ${low ? "text-accent-red" : "text-foreground/80"}`}
            >
              {pct}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
