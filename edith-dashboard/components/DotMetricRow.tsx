export function DotMetricRow({
  label,
  pct,
  display,
  good = "low",
}: {
  label: string;
  /** 0..1 position along the track */
  pct: number;
  display: string;
  /** whether a low or high pct is the desirable direction, colors the dot */
  good?: "low" | "high";
}) {
  const clamped = Math.max(0.02, Math.min(0.98, pct));
  const isGood = good === "low" ? clamped < 0.4 : clamped > 0.6;
  const isBad = good === "low" ? clamped > 0.7 : clamped < 0.3;
  const color = isBad ? "var(--accent-red)" : isGood ? "var(--accent-blue)" : "var(--accent-amber)";

  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 text-[11px] text-muted leading-tight">{label}</span>
      <div className="relative flex-1 h-[3px] rounded-full bg-panel-border">
        <span
          className="absolute top-1/2 h-2.5 w-2.5 -translate-y-1/2 -translate-x-1/2 rounded-full ring-2 ring-panel"
          style={{ left: `${clamped * 100}%`, background: color }}
        />
      </div>
      <span className="w-14 shrink-0 text-right text-[11px] tabular-nums text-foreground/80">{display}</span>
    </div>
  );
}
