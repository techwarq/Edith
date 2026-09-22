"use client";

import { useState } from "react";
import { Panel } from "@/components/Panel";
import { KpiCard } from "@/components/KpiCard";
import { Gauge } from "@/components/Gauge";
import { DotMetricRow } from "@/components/DotMetricRow";
import { TraceScatter, EmptyChart } from "@/components/TraceScatter";
import { ToolRadar } from "@/components/ToolRadar";
import { EvolutionHeatmap } from "@/components/EvolutionHeatmap";
import { ScoreTrend } from "@/components/ScoreTrend";
import { RetentionPanel } from "@/components/RetentionPanel";
import { RangeFilter } from "@/components/RangeFilter";
import { LiveBadge } from "@/components/LiveBadge";
import { DailyBriefing } from "@/components/DailyBriefing";
import { GoalsPanel } from "@/components/GoalsPanel";
import { ThoughtStream } from "@/components/ThoughtStream";
import { InsightsPanel } from "@/components/InsightsPanel";
import { ConfidencePanel } from "@/components/ConfidencePanel";
import { LearningPanel } from "@/components/LearningPanel";
import { useEdithData } from "@/lib/useEdithData";
import { useEvalMatrix } from "@/lib/useEvalMatrix";
import { useLatestTrace } from "@/lib/useLatestTrace";
import { Goal, Insight, PerformanceOverview, PerformanceTrendPoint, Spending, Todo, Trace, ToolStat } from "@/lib/types";

function clamp01(x: number) {
  return Math.max(0, Math.min(1, x));
}

function fmtCompact(n: number) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 }).format(n);
}

function isToday(iso: string) {
  return iso.slice(0, 10) === new Date().toISOString().slice(0, 10);
}

export default function Home() {
  const [days, setDays] = useState(30);

  const spending = useEdithData<Spending>(`observability/spending?days=${days}`, 20000);
  const performance = useEdithData<PerformanceOverview>(`observability/performance?days=${days}`, 20000);
  const trend = useEdithData<{ trend: PerformanceTrendPoint[] }>(`observability/performance/trend?days=${days}`, 30000);
  const tools = useEdithData<{ tools: ToolStat[] }>(`observability/tools?days=${days}`, 30000);
  const traces = useEdithData<{ traces: Trace[] }>(`observability/traces?kind=turn&limit=150`, 20000);
  const goals = useEdithData<{ goals: Goal[] }>(`goals`, 30000);
  const todos = useEdithData<{ todos: Todo[] }>(`todos`, 30000);
  const insights = useEdithData<{ insights: Insight[] }>(`insights?unseen_only=false&limit=20`, 30000);
  const { matrix, error: matrixError } = useEvalMatrix(8, 60000);
  const { trace: liveTrace } = useLatestTrace(12000);

  const totals = spending.data?.totals;
  const overview = performance.data;
  const latestTrend = trend.data?.trend?.at(-1);
  const toolList = tools.data?.tools ?? [];
  const traceList = traces.data?.traces ?? [];
  const latestRun = matrix.runs.at(-1);
  const trendSeries = trend.data?.trend ?? [];

  const edithScore = latestRun ? latestRun.avg_score * 10 : overview ? (1 - overview.error_rate) * 10 : 0;

  const todosDoneToday = (todos.data?.todos ?? []).filter((t) => t.status === "done" && isToday(t.updated_at));
  const turnsToday = latestTrend && isToday(`${latestTrend.date}T00:00:00Z`) ? latestTrend.turn_count : 0;
  const toolCallsToday = turnsToday ? Math.round(turnsToday * (latestTrend?.avg_tool_calls_per_turn ?? 0)) : 0;

  return (
    <div className="min-h-screen w-full px-4 py-4 sm:px-6 sm:py-6 flex flex-col gap-6 max-w-[1600px] mx-auto">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-md bg-accent-blue/15 border border-accent-blue/30 flex items-center justify-center text-accent-blue font-bold">
            E
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Edith</h1>
            <p className="text-[11px] text-muted">a living picture of how she&rsquo;s evolving</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <LiveBadge updatedAt={spending.updatedAt} error={spending.error} />
          <RangeFilter days={days} onChange={setDays} />
        </div>
      </header>

      {/* hero: what edith has done today */}
      <DailyBriefing name="Sonali" todosDoneToday={todosDoneToday} turnsToday={turnsToday} toolCallsToday={toolCallsToday} />

      {/* goals + live reasoning */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Current Goals" subtitle="progress toward what matters">
          <GoalsPanel goals={goals.data?.goals ?? []} />
        </Panel>
        <Panel title="Live Thought Stream" subtitle="watching her reason, live">
          <ThoughtStream trace={liveTrace} />
        </Panel>
      </div>

      {/* what she noticed + how much to trust her */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="What I've Noticed" subtitle="surfaced by Edith, unprompted">
          <InsightsPanel insights={insights.data?.insights ?? []} />
        </Panel>
        <Panel title="Confidence by Skill" subtitle={latestRun ? `latest eval · ${new Date(latestRun.started_at).toLocaleDateString()}` : undefined}>
          <ConfidencePanel matrix={matrix} />
        </Panel>
      </div>

      {/* learning + capability evolution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Learning" subtitle="today vs. yesterday">
          <LearningPanel trend={trendSeries} />
        </Panel>
        <Panel title="Eval Score Trend" subtitle="how she's evolving">
          <ScoreTrend runs={matrix.runs} />
        </Panel>
      </div>

      <Panel title="Capability Evolution" subtitle="eval score per skill, run over run">
        {matrixError ? <EmptyChart label={matrixError} /> : <EvolutionHeatmap matrix={matrix} />}
      </Panel>

      {/* demoted: raw operating metrics */}
      <div className="flex items-center gap-3 pt-2">
        <span className="text-[10px] tracking-[0.2em] uppercase text-muted">Operations</span>
        <span className="h-px flex-1 bg-panel-border" />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="turns" value={totals ? fmtCompact(totals.trace_count) : "–"} />
        <KpiCard label="sessions" value={spending.data ? String(spending.data.by_session.length) : "–"} />
        <KpiCard label="cost" value={totals ? `$${totals.cost_usd.toFixed(2)}` : "–"} />
        <KpiCard label="tokens" value={totals ? fmtCompact(totals.prompt_tokens + totals.completion_tokens) : "–"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)] gap-4 items-start">
        <Panel title="Edith Score">
          <div className="flex flex-col items-center gap-2">
            <Gauge value={edithScore} />
          </div>
        </Panel>
        <Panel title="Trace Scatterplot" subtitle="cost vs. duration">
          <TraceScatter traces={traceList} />
        </Panel>
        <Panel title="Tool Radar" subtitle="calls vs. reliability">
          <ToolRadar tools={toolList} />
        </Panel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Average Metric Points" subtitle="lower = better">
          <div className="flex flex-col gap-3">
            <DotMetricRow
              label="Error rate"
              pct={overview ? clamp01(overview.error_rate / 0.2) : 0}
              display={overview ? `${(overview.error_rate * 100).toFixed(1)}%` : "–"}
            />
            <DotMetricRow
              label="Tool hallucination"
              pct={latestTrend ? clamp01(latestTrend.tool_hallucination_rate / 0.1) : 0}
              display={latestTrend ? `${(latestTrend.tool_hallucination_rate * 100).toFixed(1)}%` : "–"}
            />
            <DotMetricRow
              label="Redundant calls"
              pct={latestTrend ? clamp01(latestTrend.redundant_tool_call_rate / 0.2) : 0}
              display={latestTrend ? `${(latestTrend.redundant_tool_call_rate * 100).toFixed(1)}%` : "–"}
            />
            <DotMetricRow
              label="Tool calls / turn"
              pct={overview ? clamp01(overview.avg_tool_calls_per_turn / 5) : 0}
              display={overview ? overview.avg_tool_calls_per_turn.toFixed(2) : "–"}
            />
            <DotMetricRow
              label="Avg latency"
              pct={overview ? clamp01(overview.avg_duration_ms / 1000 / 60) : 0}
              display={overview ? `${(overview.avg_duration_ms / 1000).toFixed(1)}s` : "–"}
            />
            <DotMetricRow
              label="Prompt context"
              pct={latestTrend ? clamp01(latestTrend.avg_prompt_tokens / 200000) : 0}
              display={latestTrend ? fmtCompact(latestTrend.avg_prompt_tokens) : "–"}
            />
          </div>
        </Panel>
        <Panel title="Retention" subtitle="usage over time">
          <RetentionPanel byDay={spending.data?.by_day ?? []} bySession={spending.data?.by_session ?? []} />
        </Panel>
      </div>

      <footer className="text-center text-[10px] text-muted pb-2">
        data from edith-production · refreshed automatically
      </footer>
    </div>
  );
}
