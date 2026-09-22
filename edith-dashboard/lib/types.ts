export type SpendingTotals = {
  cost_usd: number;
  prompt_tokens: number;
  completion_tokens: number;
  trace_count: number;
};

export type SpendingByDay = {
  date: string;
  cost_usd: number;
  prompt_tokens: number;
  completion_tokens: number;
  trace_count: number;
};

export type SpendingByModel = {
  model: string;
  cost_usd: number;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
};

export type SpendingBySession = {
  session_id: string;
  cost_usd: number;
  trace_count: number;
  last_active: string;
};

export type Spending = {
  totals: SpendingTotals;
  by_day: SpendingByDay[];
  by_model: SpendingByModel[];
  by_session: SpendingBySession[];
};

export type PerformanceOverview = {
  turn_count: number;
  error_count: number;
  avg_duration_ms: number;
  avg_cost_usd: number;
  error_rate: number;
  avg_tool_calls_per_turn: number;
};

export type PerformanceTrendPoint = {
  date: string;
  turn_count: number;
  error_count: number;
  avg_duration_ms: number;
  avg_cost_usd: number;
  avg_prompt_tokens: number;
  error_rate: number;
  avg_tool_calls_per_turn: number;
  tool_hallucination_rate: number;
  redundant_tool_call_rate: number;
};

export type ToolStat = {
  tool_name: string;
  calls: number;
  errors: number;
  avg_duration_ms: number;
  error_rate: number;
};

export type Trace = {
  id: string;
  session_id: string | null;
  kind: string;
  status: string;
  error: string | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cost_usd: number | null;
  input_preview: string;
  output_preview: string;
  tools_used: string[];
};

export type EvalRun = {
  id: string;
  model: string;
  started_at: string;
  ended_at: string | null;
  case_count: number;
  avg_score: number;
  passed_count: number;
};

export type EvalCase = {
  id: number;
  name: string;
  input: string;
  rubric: string;
  expect_tools: string[];
  created_at: string;
};

export type EvalResult = {
  id: number;
  run_id: string;
  case_id: number;
  case_name: string;
  score: number;
  passed: number | boolean;
  reasoning?: string;
  tools_called: string[];
};

export type EvalRunDetail = EvalRun & {
  results: EvalResult[];
};

export type Milestone = {
  id: number;
  goal_id: number;
  title: string;
  target_date: string | null;
  done: number | boolean;
  done_at: string | null;
  sort_order: number;
};

export type Goal = {
  id: number;
  title: string;
  description: string | null;
  target_date: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  milestones: Milestone[];
};

export type Todo = {
  id: number;
  title: string;
  note: string | null;
  status: "todo" | "in_progress" | "done" | string;
  due_date: string | null;
  goal_id: number | null;
  created_at: string;
  updated_at: string;
};

export type Insight = {
  id: number;
  kind: string;
  title: string;
  body: string | null;
  goal_id: number | null;
  created_at: string;
  seen_at: string | null;
};

export type Span = {
  id: number;
  trace_id: string;
  kind: "llm" | "tool" | string;
  name: string;
  input: string | null;
  output: string | null;
  status: string;
  error: string | null;
  started_at: string;
  duration_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cost_usd: number | null;
};

export type TraceDetail = Trace & {
  input: string;
  output: string;
  spans: Span[];
};
