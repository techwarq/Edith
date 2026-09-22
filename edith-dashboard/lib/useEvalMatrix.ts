"use client";

import { useEffect, useState } from "react";
import { EvalRun, EvalRunDetail } from "./types";

export type EvalMatrixCell = { score: number; passed: boolean } | null;
export type EvalMatrix = {
  caseNames: string[];
  runs: EvalRun[];
  cell: (caseName: string, runId: string) => EvalMatrixCell;
};

/** Builds a (case x run) score matrix by fetching each recent run's full
 * detail (which includes per-case results) — evals run roughly once a day,
 * so a slower poll interval than the live trace/spending panels is fine. */
export function useEvalMatrix(limit = 8, intervalMs = 60000) {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [details, setDetails] = useState<Record<string, EvalRunDetail>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const runsRes = await fetch(`/api/edith/observability/evals/runs?limit=${limit}`, { cache: "no-store" });
        const runsJson = await runsRes.json();
        if (!runsRes.ok) throw new Error(runsJson?.error ?? `HTTP ${runsRes.status}`);
        const runList: EvalRun[] = [...runsJson.runs].reverse();
        if (cancelled) return;
        setRuns(runList);

        const detailEntries = await Promise.all(
          runList.map(async (r) => {
            const res = await fetch(`/api/edith/observability/evals/runs/${r.id}`, { cache: "no-store" });
            const json = await res.json();
            return [r.id, json as EvalRunDetail] as const;
          })
        );
        if (cancelled) return;
        setDetails(Object.fromEntries(detailEntries));
        setLoading(false);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "fetch failed");
        setLoading(false);
      }
    }

    load();
    const id = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [limit, intervalMs]);

  const caseNameSet = new Set<string>();
  for (const d of Object.values(details)) {
    for (const r of d.results ?? []) caseNameSet.add(r.case_name);
  }

  const matrix: EvalMatrix = {
    caseNames: [...caseNameSet],
    runs,
    cell: (caseName, runId) => {
      const detail = details[runId];
      const result = detail?.results?.find((r) => r.case_name === caseName);
      if (!result) return null;
      return { score: result.score, passed: !!result.passed };
    },
  };

  return { matrix, loading, error };
}
