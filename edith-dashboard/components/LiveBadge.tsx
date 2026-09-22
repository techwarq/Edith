"use client";

import { useEffect, useState } from "react";

export function LiveBadge({ updatedAt, error }: { updatedAt: number | null; error?: string | null }) {
  const [secondsAgo, setSecondsAgo] = useState<number | null>(null);

  useEffect(() => {
    if (!updatedAt) return;
    const tick = () => setSecondsAgo(Math.max(0, Math.floor((Date.now() - updatedAt) / 1000)));
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, [updatedAt]);

  if (error) {
    return (
      <span className="flex items-center gap-1.5 text-[10px] text-accent-red">
        <span className="h-1.5 w-1.5 rounded-full bg-accent-red" />
        {error}
      </span>
    );
  }

  return (
    <span className="flex items-center gap-1.5 text-[10px] text-muted">
      <span className="h-1.5 w-1.5 rounded-full bg-accent-green animate-pulse" />
      {secondsAgo == null ? "connecting…" : `live · synced ${secondsAgo}s ago`}
    </span>
  );
}
