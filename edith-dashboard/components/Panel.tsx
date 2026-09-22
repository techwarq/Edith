import { ReactNode } from "react";

export function Panel({
  title,
  subtitle,
  headerAccent = "blue",
  className = "",
  children,
}: {
  title: string;
  subtitle?: string;
  headerAccent?: "blue" | "red" | "none";
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={`flex flex-col rounded-lg border border-panel-border bg-panel/80 backdrop-blur-sm overflow-hidden ${className}`}
    >
      {headerAccent !== "none" && (
        <header
          className={`flex items-baseline justify-between px-4 py-2.5 border-b border-panel-border ${
            headerAccent === "red" ? "bg-accent-red/10" : "bg-white/[0.03]"
          }`}
        >
          <h2
            className={`text-[11px] font-semibold tracking-[0.14em] uppercase ${
              headerAccent === "red" ? "text-accent-red" : "text-foreground/90"
            }`}
          >
            {title}
          </h2>
          {subtitle && <span className="text-[10px] text-muted">{subtitle}</span>}
        </header>
      )}
      <div className="flex-1 min-h-0 p-4">{children}</div>
    </section>
  );
}
