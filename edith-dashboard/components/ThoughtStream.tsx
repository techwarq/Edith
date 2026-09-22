"use client";

import { TraceDetail } from "@/lib/types";

function argPreview(input: string | null): string {
  if (!input) return "";
  try {
    const parsed = JSON.parse(input);
    const firstVal = Object.values(parsed)[0];
    const s = typeof firstVal === "string" ? firstVal : JSON.stringify(firstVal);
    return s.length > 60 ? s.slice(0, 60) + "…" : s;
  } catch {
    return input.length > 60 ? input.slice(0, 60) + "…" : input;
  }
}

function truncate(s: string | null, n = 140): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function ThoughtStream({ trace }: { trace: TraceDetail | null }) {
  if (!trace) {
    return <div className="py-8 text-center text-xs text-muted">waiting for the next turn…</div>;
  }

  const toolSpans = trace.spans.filter((s) => s.kind === "tool");
  const failed = trace.status === "error";

  return (
    <div className="flex flex-col gap-0.5" key={trace.id}>
      <div className="flex items-baseline justify-between mb-3">
        <span className="text-[10px] text-muted">session · {timeAgo(trace.started_at)}</span>
        <span className="text-[10px] text-muted">{((trace.duration_ms ?? 0) / 1000).toFixed(1)}s</span>
      </div>

      <Step dot="user" animKey={`${trace.id}-user`}>
        <span className="text-muted">User</span> {trace.input}
      </Step>

      {toolSpans.map((s, i) => (
        <div key={s.id} className="contents">
          <Step dot="tool" animKey={`${trace.id}-tool-${i}-call`} delay={(i + 1) * 90}>
            <span className="text-accent-blue">Calling {s.name}</span>
            {argPreview(s.input) && <span className="text-muted"> · {argPreview(s.input)}</span>}
          </Step>
          <Step dot="result" animKey={`${trace.id}-tool-${i}-result`} delay={(i + 1) * 90 + 45}>
            <span className="text-muted">{truncate(s.output)}</span>
          </Step>
        </div>
      ))}

      <Step
        dot={failed ? "error" : "reply"}
        animKey={`${trace.id}-reply`}
        delay={(toolSpans.length + 1) * 90}
        last
      >
        <span className={failed ? "text-accent-red" : "text-accent-green"}>
          {failed ? "Error" : "Replied"}
        </span>{" "}
        {truncate(trace.output, 200)}
      </Step>
    </div>
  );
}

function Step({
  dot,
  children,
  animKey,
  delay = 0,
  last = false,
}: {
  dot: "user" | "tool" | "result" | "reply" | "error";
  children: React.ReactNode;
  animKey: string;
  delay?: number;
  last?: boolean;
}) {
  const color =
    dot === "user"
      ? "bg-muted"
      : dot === "tool"
      ? "bg-accent-blue"
      : dot === "error"
      ? "bg-accent-red"
      : dot === "reply"
      ? "bg-accent-green"
      : "bg-panel-border";

  return (
    <div
      key={animKey}
      className="flex gap-2.5 py-1.5 opacity-0 animate-[fadeInUp_0.4s_ease_forwards]"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex flex-col items-center pt-1">
        <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${color}`} />
        {!last && <span className="w-px flex-1 bg-panel-border mt-1" style={{ minHeight: 10 }} />}
      </div>
      <p className="text-[12px] leading-snug pb-1">{children}</p>
    </div>
  );
}
