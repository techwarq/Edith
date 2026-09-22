const RANGES = [7, 30, 90] as const;

export function RangeFilter({ days, onChange }: { days: number; onChange: (d: number) => void }) {
  return (
    <div className="flex items-center gap-1 rounded-md border border-panel-border bg-white/[0.03] p-0.5">
      {RANGES.map((r) => (
        <button
          key={r}
          onClick={() => onChange(r)}
          className={`px-2.5 py-1 text-[11px] rounded transition-colors ${
            days === r ? "bg-accent-blue text-black font-medium" : "text-muted hover:text-foreground"
          }`}
        >
          {r}d
        </button>
      ))}
    </div>
  );
}
