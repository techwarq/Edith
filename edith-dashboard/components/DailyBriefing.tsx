"use client";

import { Todo } from "@/lib/types";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function DailyBriefing({
  name,
  todosDoneToday,
  turnsToday,
  toolCallsToday,
}: {
  name: string;
  todosDoneToday: Todo[];
  turnsToday: number;
  toolCallsToday: number;
}) {
  const hasWins = todosDoneToday.length > 0;

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">
        {greeting()}, {name}.
      </h1>
      <p className="text-sm text-muted mt-1">
        {turnsToday > 0
          ? `Today I've had ${turnsToday} conversation${turnsToday === 1 ? "" : "s"} and run ${toolCallsToday} tool call${toolCallsToday === 1 ? "" : "s"} on your behalf.`
          : "No activity yet today — I'll fill this in as we go."}
      </p>

      {hasWins && (
        <ul className="mt-4 flex flex-col gap-1.5">
          {todosDoneToday.map((t) => (
            <li key={t.id} className="flex items-center gap-2 text-[13px]">
              <span className="text-accent-green">✓</span>
              <span className="text-foreground/90">{t.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
