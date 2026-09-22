"use client";

import { useEffect, useState } from "react";
import { TraceDetail } from "./types";

/** Polls for the most recent turn and, whenever it changes, fetches its full
 * span breakdown — this is the real reasoning trail (LLM call -> tool call ->
 * LLM call -> reply) that powers the live thought stream. */
export function useLatestTrace(intervalMs = 12000) {
  const [trace, setTrace] = useState<TraceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let lastId: string | null = null;

    async function load() {
      try {
        const listRes = await fetch("/api/edith/observability/traces?kind=turn&limit=1", { cache: "no-store" });
        const listJson = await listRes.json();
        if (!listRes.ok) throw new Error(listJson?.error ?? `HTTP ${listRes.status}`);
        const latest = listJson.traces?.[0];
        if (!latest) {
          if (!cancelled) setLoading(false);
          return;
        }
        if (latest.id === lastId) return;
        lastId = latest.id;

        const detailRes = await fetch(`/api/edith/observability/traces/${latest.id}`, { cache: "no-store" });
        const detailJson = await detailRes.json();
        if (!detailRes.ok) throw new Error(detailJson?.error ?? `HTTP ${detailRes.status}`);
        if (cancelled) return;
        setTrace(detailJson as TraceDetail);
        setLoading(false);
        setError(null);
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
  }, [intervalMs]);

  return { trace, loading, error };
}
