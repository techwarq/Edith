"use client";

import { useEffect, useRef, useState } from "react";

type State<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  updatedAt: number | null;
};

/** Polls a proxied Edith API path on an interval so the dashboard reflects
 * live production data without a full page reload. The proxy route injects
 * the token server-side, so nothing here ever touches the secret. */
export function useEdithData<T>(path: string | null, intervalMs = 20000): State<T> {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true, updatedAt: null });
  const pathRef = useRef(path);
  pathRef.current = path;

  useEffect(() => {
    if (!path) return;
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch(`/api/edith/${path}`, { cache: "no-store" });
        const json = await res.json();
        if (cancelled) return;
        if (!res.ok) {
          setState((s) => ({ ...s, error: json?.error ?? `HTTP ${res.status}`, loading: false }));
          return;
        }
        setState({ data: json as T, error: null, loading: false, updatedAt: Date.now() });
      } catch (e) {
        if (cancelled) return;
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : "fetch failed", loading: false }));
      }
    }

    load();
    const id = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [path, intervalMs]);

  return state;
}
