"use client";

import { Insight } from "@/lib/types";

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function InsightsPanel({ insights }: { insights: Insight[] }) {
  if (insights.length === 0) {
    return <div className="py-6 text-center text-xs text-muted">nothing new to surface yet</div>;
  }

  return (
    <div className="flex flex-col gap-3">
      {insights.map((i) => (
        <div key={i.id} className="flex gap-2.5">
          <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-accent-amber shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[12px] font-medium text-foreground">{i.title}</span>
              <span className="text-[10px] text-muted shrink-0">{timeAgo(i.created_at)}</span>
            </div>
            {i.body && <p className="text-[11px] text-muted mt-0.5 leading-snug">{i.body}</p>}
          </div>
        </div>
      ))}
    </div>
  );
}
