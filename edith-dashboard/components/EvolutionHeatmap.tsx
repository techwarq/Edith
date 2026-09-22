"use client";

import { EvalMatrix } from "@/lib/useEvalMatrix";
import { EmptyChart } from "./TraceScatter";

function scoreColor(score: number) {
  // 0 -> red, 0.5 -> amber, 1 -> blue/green, interpolated in rgb space
  const stops = [
    { at: 0, c: [239, 93, 120] },
    { at: 0.5, c: [245, 185, 66] },
    { at: 1, c: [62, 207, 142] },
  ];
  let lo = stops[0];
  let hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (score >= stops[i].at && score <= stops[i + 1].at) {
      lo = stops[i];
      hi = stops[i + 1];
      break;
    }
  }
  const span = hi.at - lo.at || 1;
  const t = (score - lo.at) / span;
  const rgb = lo.c.map((v, i) => Math.round(v + (hi.c[i] - v) * t));
  return `rgb(${rgb.join(",")})`;
}

export function EvolutionHeatmap({ matrix }: { matrix: EvalMatrix }) {
  const { caseNames, runs } = matrix;
  if (runs.length === 0 || caseNames.length === 0) {
    return <EmptyChart label="no eval runs yet" />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[10px]">
        <thead>
          <tr>
            <th className="text-left font-normal text-muted pr-3 pb-1 sticky left-0 bg-panel">skill</th>
            {runs.map((r) => (
              <th key={r.id} className="font-normal text-muted px-1 pb-1 whitespace-nowrap">
                {new Date(r.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {caseNames.map((name) => (
            <tr key={name}>
              <td className="pr-3 py-0.5 text-foreground/80 sticky left-0 bg-panel whitespace-nowrap">
                {name.replaceAll("_", " ")}
              </td>
              {runs.map((r) => {
                const cell = matrix.cell(name, r.id);
                return (
                  <td key={r.id} className="p-0.5">
                    <div
                      className="h-6 min-w-8 rounded-sm flex items-center justify-center text-[9px] font-medium text-black/70"
                      style={{ background: cell ? scoreColor(cell.score) : "var(--panel-border)" }}
                      title={cell ? `${name}: ${cell.score.toFixed(2)}` : "no data"}
                    >
                      {cell ? cell.score.toFixed(1) : ""}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
