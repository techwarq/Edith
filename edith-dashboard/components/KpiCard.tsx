export function KpiCard({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="rounded-md border border-panel-border bg-white/[0.03] px-3 py-3 flex flex-col gap-1">
      <span className="text-xl font-semibold tabular-nums text-foreground">
        {value}
        {unit && <span className="text-xs text-muted ml-1 font-normal">{unit}</span>}
      </span>
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
    </div>
  );
}
