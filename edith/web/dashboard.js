// Observability / Goals / Insights dashboard tabs. Loaded after app.js and
// shares its global `token` (classic <script> tags, not modules, so this is
// intentional — same pattern the whole app already uses) plus its
// escapeHtml() helper for safe HTML injection of user/model-generated text.

const tabButtons = document.querySelectorAll(".tab-btn");
const screens = {
  overview: document.getElementById("overview-screen"),
  chat: document.getElementById("chat-screen"),
  monitor: document.getElementById("monitor-screen"),
  observability: document.getElementById("observability-screen"),
  goals: document.getElementById("goals-screen"),
  todos: document.getElementById("todos-screen"),
  insights: document.getElementById("insights-screen"),
  mcp: document.getElementById("mcp-screen"),
};

function switchTab(name) {
  tabButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === name));
  Object.entries(screens).forEach(([key, el]) => el.classList.toggle("active", key === name));
  if (name === "overview") loadOverview();
  else if (name === "monitor") loadMonitor();
  else if (name === "observability") loadObservability();
  else if (name === "goals") loadGoals();
  else if (name === "todos") loadTodos();
  else if (name === "insights") loadInsights();
  else if (name === "mcp") loadMcpServers();
}

tabButtons.forEach((btn) => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));

async function apiGet(path, params) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set("token", token);
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  }
  const resp = await fetch(url);
  if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error || `Request failed (${resp.status})`);
  return resp.json();
}

async function apiPost(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, ...(body || {}) }),
  });
  if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error || `Request failed (${resp.status})`);
  return resp.json();
}

function fmtUsd(value) {
  return "$" + (value || 0).toFixed(4).replace(/0+$/, "").replace(/\.$/, ".00");
}

function fmtPct(value) {
  return Math.round((value || 0) * 100) + "%";
}

// --- Overview: lands here on connect — recent activity, Edith's performance,
// and your own goal progress in one glanceable screen. Deeper drill-down
// (full trace/span detail, full goal CRUD, full insights feed) still lives
// in the dedicated tabs; this is the "what's going on" summary. -----------

function timeAgo(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

async function loadOverview() {
  const panel = document.getElementById("overview-panel");
  panel.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const [traces, performance, spending, evalRuns, goals, insights] = await Promise.all([
      apiGet("/api/observability/traces", { limit: 8, kind: "turn" }),
      apiGet("/api/observability/performance", { days: 7 }),
      apiGet("/api/observability/spending", { days: 30 }),
      apiGet("/api/observability/evals/runs", { limit: 1 }),
      apiGet("/api/goals", { status: "active" }),
      apiGet("/api/insights", { unseen_only: true, limit: 3 }),
    ]);
    renderOverview(panel, traces.traces, performance, spending.totals, evalRuns.runs[0], goals.goals, insights.insights);
  } catch (err) {
    panel.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function renderOverview(panel, traces, performance, totals, latestEvalRun, goals, insights) {
  const evalScore = latestEvalRun ? `${latestEvalRun.passed_count}/${latestEvalRun.case_count}` : "—";

  panel.innerHTML = `
    <h3>Edith's performance (7d)</h3>
    <div class="stat-row">
      <div class="stat-tile"><div class="stat-value">${fmtPct(performance.error_rate)}</div><div class="stat-label">Error rate</div></div>
      <div class="stat-tile"><div class="stat-value">${Math.round(performance.avg_duration_ms || 0)}ms</div><div class="stat-label">Avg latency</div></div>
      <div class="stat-tile"><div class="stat-value">${fmtUsd(totals.cost_usd)}</div><div class="stat-label">Spend (30d)</div></div>
      <div class="stat-tile"><div class="stat-value">${evalScore}</div><div class="stat-label">Last eval run</div></div>
    </div>

    <div class="card-grid" style="margin-top: 10px;">
      <div>
        <div class="panel-header"><h3>Tasks — what Edith's been doing</h3></div>
        <div id="overview-activity">${renderActivity(traces)}</div>
      </div>

      <div>
        <div class="panel-header"><h3>Your goals</h3><span class="see-all-link" data-goto="goals">See all →</span></div>
        ${
          goals.length
            ? goals.slice(0, 4).map(renderMiniGoal).join("")
            : '<div class="empty-state">No active goals — tell Edith what you\'re working toward, or add one in the Goals tab.</div>'
        }
      </div>

      <div>
        <div class="panel-header"><h3>Insights</h3><span class="see-all-link" data-goto="insights">See all →</span></div>
        ${
          insights.length
            ? insights.map((i) => `<div class="activity-item"><div class="activity-input">${INSIGHT_ICON[i.kind] || "💡"} ${escapeHtml(i.title)}</div><div class="activity-when">${timeAgo(i.created_at)}</div></div>`).join("")
            : '<div class="empty-state">Nothing flagged right now.</div>'
        }
      </div>
    </div>
  `;

  panel.querySelectorAll("[data-goto]").forEach((el) => el.addEventListener("click", () => switchTab(el.dataset.goto)));
}

function renderActivity(traces) {
  if (!traces.length) return '<div class="empty-state">No activity yet — say something in Chat.</div>';
  return traces
    .map(
      (t) => `
    <div class="activity-item${t.status === "error" ? " is-error" : ""}">
      <div class="panel-header"><div class="activity-when">${timeAgo(t.started_at)}</div><span>${t.status === "error" ? "⚠️" : "✓"}</span></div>
      <div class="activity-input">${escapeHtml(t.input_preview || "(no input)")}</div>
      ${t.output_preview ? `<div class="activity-output">${escapeHtml(t.output_preview)}</div>` : ""}
      ${t.tools_used.length ? `<div class="tool-chips">${t.tools_used.map((n) => `<span class="tool-chip">${escapeHtml(n)}</span>`).join("")}</div>` : ""}
    </div>`
    )
    .join("");
}

function renderMiniGoal(goal) {
  const done = goal.milestones.filter((m) => m.done).length;
  const total = goal.milestones.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  return `
    <div class="mini-goal">
      <div class="mini-goal-title">${escapeHtml(goal.title)}</div>
      <div class="mini-goal-meta">${total ? `${done}/${total} milestones` : "no milestones yet"}${goal.target_date ? " · due " + escapeHtml(goal.target_date) : ""}</div>
      ${total ? `<div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div><div class="progress-puck" style="left:${pct}%"></div></div>` : ""}
    </div>`;
}

// --- Observability ------------------------------------------------------
//
// "Is Edith getting worse or better" needs a trend, not a single-window
// average — two quiet weeks then one bad day look identical in an average
// but not in a trend. performance/trend and evals/trend back the sparklines,
// deltas, and the eval score chart below; performance_overview/list_eval_runs
// still back the plain snapshot numbers and the run list.

function _sparklinePoints(values, w, h, pad) {
  if (values.length < 2) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = (w - pad * 2) / (values.length - 1);
  return values.map((v, i) => [pad + i * step, pad + (1 - (v - min) / range) * (h - pad * 2)]);
}

function renderSparkline(values) {
  if (values.length < 2) return "";
  const w = 100, h = 26, pad = 3;
  const points = _sparklinePoints(values, w, h, pad);
  const path = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lastX, lastY] = points[points.length - 1];
  return `<svg class="stat-sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <path d="${path}"></path><circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="2.5"></circle>
  </svg>`;
}

// higherIsBetter: false for error rate / latency (down = good), true for eval score (up = good).
function renderDelta(current, previous, { higherIsBetter, formatter, suffix = "" }) {
  if (previous === null || previous === undefined || !isFinite(previous) || current === null) return "";
  const diff = current - previous;
  if (Math.abs(diff) < 1e-9) return `<div class="stat-delta is-flat">— no change vs prior period</div>`;
  const improved = higherIsBetter ? diff > 0 : diff < 0;
  const arrow = diff > 0 ? "▲" : "▼";
  return `<div class="stat-delta ${improved ? "is-good" : "is-bad"}">${arrow} ${formatter(Math.abs(diff))}${suffix} vs prior period</div>`;
}

// turn_count-weighted average of `key` over every row passed in — used both
// as the stat-tile headline (over the whole fetched window, so it's still a
// real number with as little as one day of data) and as a building block for
// splitTrendHalves's before/after comparison below.
function weightedAverage(trend, key) {
  const totalWeight = trend.reduce((s, r) => s + (r.turn_count || 0), 0);
  if (!totalWeight) return null;
  return trend.reduce((s, r) => s + (r[key] || 0) * (r.turn_count || 0), 0) / totalWeight;
}

// Splits a daily trend (oldest -> newest) into two halves and returns a
// turn_count-weighted average of `key` for each — "current" period vs the
// "prior" period immediately before it, both proportional to whatever window
// was fetched (e.g. ~15d vs ~15d out of a 30-day fetch). Only meaningful with
// >= 2 days of data (there's no "before" with a single day) — callers must
// use weightedAverage, not this, for a headline number that should still
// show something with sparse data.
function splitTrendHalves(trend, key) {
  if (trend.length < 2) return { current: null, previous: null };
  const mid = Math.ceil(trend.length / 2);
  return { current: weightedAverage(trend.slice(mid), key), previous: weightedAverage(trend.slice(0, mid), key) };
}

async function loadObservability() {
  const panel = document.getElementById("observability-panel");
  panel.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const [spending, performance, perfTrend, tools, traces, evalRuns, evalTrend] = await Promise.all([
      apiGet("/api/observability/spending", { days: 30 }),
      apiGet("/api/observability/performance", { days: 7 }),
      apiGet("/api/observability/performance/trend", { days: 30 }),
      apiGet("/api/observability/tools", { days: 30 }),
      apiGet("/api/observability/traces", { limit: 20 }),
      apiGet("/api/observability/evals/runs", { limit: 10 }),
      apiGet("/api/observability/evals/trend", { limit: 30 }),
    ]);
    renderObservability(panel, spending, performance, perfTrend.trend, tools, traces.traces, evalRuns.runs, evalTrend.trend);
  } catch (err) {
    panel.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function renderObservability(panel, spending, performance, perfTrend, tools, traces, evalRuns, evalTrend) {
  const totals = spending.totals;
  const maxDay = Math.max(1e-9, ...spending.by_day.map((d) => d.cost_usd));

  const errorHalves = splitTrendHalves(perfTrend, "error_rate");
  const latencyHalves = splitTrendHalves(perfTrend, "avg_duration_ms");
  const errorSpark = renderSparkline(perfTrend.map((d) => d.error_rate));
  const latencySpark = renderSparkline(perfTrend.map((d) => d.avg_duration_ms || 0));
  const errorDelta = renderDelta(errorHalves.current, errorHalves.previous, {
    higherIsBetter: false,
    formatter: (v) => (v * 100).toFixed(1),
    suffix: "pp",
  });
  const latencyDelta = renderDelta(latencyHalves.current, latencyHalves.previous, {
    higherIsBetter: false,
    formatter: (v) => Math.round(v),
    suffix: "ms",
  });

  // Trajectory health — not just "did the turn error," but how it got there:
  // tool calls per turn, calls to tools that don't exist (hallucinated, not
  // just failed), repeated identical calls within one turn (wasted cost),
  // and context size (the leading indicator behind the 2026-07-28 blank-
  // reply bug — a big prompt leaves less token budget for the real answer).
  const toolCallsHalves = splitTrendHalves(perfTrend, "avg_tool_calls_per_turn");
  const hallucinationHalves = splitTrendHalves(perfTrend, "tool_hallucination_rate");
  const redundantHalves = splitTrendHalves(perfTrend, "redundant_tool_call_rate");
  const contextHalves = splitTrendHalves(perfTrend, "avg_prompt_tokens");
  // Headline values use the whole fetched window (real number even with 1 day
  // of data) — only the delta badges need the two-halves split above, and
  // that one correctly stays blank until there's enough history to compare.
  const toolCallsNow = weightedAverage(perfTrend, "avg_tool_calls_per_turn") || 0;
  const hallucinationNow = weightedAverage(perfTrend, "tool_hallucination_rate") || 0;
  const redundantNow = weightedAverage(perfTrend, "redundant_tool_call_rate") || 0;
  const contextNow = weightedAverage(perfTrend, "avg_prompt_tokens") || 0;
  const toolCallsSpark = renderSparkline(perfTrend.map((d) => d.avg_tool_calls_per_turn || 0));
  const hallucinationSpark = renderSparkline(perfTrend.map((d) => d.tool_hallucination_rate || 0));
  const redundantSpark = renderSparkline(perfTrend.map((d) => d.redundant_tool_call_rate || 0));
  const contextSpark = renderSparkline(perfTrend.map((d) => d.avg_prompt_tokens || 0));
  const toolCallsDelta = renderDelta(toolCallsHalves.current, toolCallsHalves.previous, {
    higherIsBetter: false,
    formatter: (v) => v.toFixed(1),
    suffix: "/turn",
  });
  const hallucinationDelta = renderDelta(hallucinationHalves.current, hallucinationHalves.previous, {
    higherIsBetter: false,
    formatter: (v) => (v * 100).toFixed(1),
    suffix: "pp",
  });
  const redundantDelta = renderDelta(redundantHalves.current, redundantHalves.previous, {
    higherIsBetter: false,
    formatter: (v) => (v * 100).toFixed(1),
    suffix: "pp",
  });
  const contextDelta = renderDelta(contextHalves.current, contextHalves.previous, {
    higherIsBetter: false,
    formatter: (v) => Math.round(v).toLocaleString(),
    suffix: " tok",
  });

  panel.innerHTML = `
    <h3>Last 30 days</h3>
    <div class="stat-row">
      <div class="stat-tile"><div class="stat-value">${fmtUsd(totals.cost_usd)}</div><div class="stat-label">Total spend</div></div>
      <div class="stat-tile"><div class="stat-value">${totals.trace_count}</div><div class="stat-label">Turns</div></div>
      <div class="stat-tile">
        <div class="stat-value">${fmtPct(performance.error_rate)}</div><div class="stat-label">Error rate (7d)</div>
        ${errorDelta}${errorSpark}
      </div>
      <div class="stat-tile">
        <div class="stat-value">${Math.round(performance.avg_duration_ms || 0)}ms</div><div class="stat-label">Avg latency (7d)</div>
        ${latencyDelta}${latencySpark}
      </div>
    </div>

    <div class="eval-trend-header">
      <h3 style="margin:0">Eval score over time</h3>
    </div>
    <div class="eval-chart-wrap" id="eval-trend-chart">${renderEvalTrendChart(evalTrend)}</div>

    <h3>Agent trajectory health (30d)</h3>
    <div class="stat-row">
      <div class="stat-tile">
        <div class="stat-value">${toolCallsNow.toFixed(1)}</div><div class="stat-label">Tool calls / turn</div>
        ${toolCallsDelta}${toolCallsSpark}
      </div>
      <div class="stat-tile">
        <div class="stat-value">${fmtPct(hallucinationNow)}</div><div class="stat-label">Hallucinated tool calls</div>
        ${hallucinationDelta}${hallucinationSpark}
      </div>
      <div class="stat-tile">
        <div class="stat-value">${fmtPct(redundantNow)}</div><div class="stat-label">Redundant tool calls</div>
        ${redundantDelta}${redundantSpark}
      </div>
      <div class="stat-tile">
        <div class="stat-value">${Math.round(contextNow).toLocaleString()}</div><div class="stat-label">Avg context size (tokens)</div>
        ${contextDelta}${contextSpark}
      </div>
    </div>

    <h3>Spending by day</h3>
    ${
      spending.by_day.length
        ? spending.by_day
            .map(
              (d) => `
      <div class="bar-row">
        <span class="bar-label">${escapeHtml(d.date.slice(5))}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${Math.max(2, (d.cost_usd / maxDay) * 100)}%"></span></span>
        <span class="bar-value">${fmtUsd(d.cost_usd)}</span>
      </div>`
            )
            .join("")
        : '<div class="empty-state">No spend yet.</div>'
    }

    <h3>By model</h3>
    ${
      spending.by_model.length
        ? spending.by_model
            .map(
              (m) => `
      <div class="list-item">
        <div class="list-title">${escapeHtml(m.model)}</div>
        <div class="list-meta">${m.calls} call(s) · ${fmtUsd(m.cost_usd)} · ${m.prompt_tokens + m.completion_tokens} tokens</div>
      </div>`
            )
            .join("")
        : '<div class="empty-state">No model usage yet.</div>'
    }

    <h3>Tools (30d)</h3>
    ${
      tools.tools.length
        ? tools.tools
            .map(
              (t) => `
      <div class="list-item${t.error_rate > 0 ? " is-error" : ""}">
        <div class="list-title">${escapeHtml(t.tool_name)}</div>
        <div class="list-meta">${t.calls} call(s) · ${fmtPct(t.error_rate)} error rate · ${Math.round(t.avg_duration_ms || 0)}ms avg</div>
      </div>`
            )
            .join("")
        : '<div class="empty-state">No tool calls yet.</div>'
    }

    <div class="panel-header"><h3>Recent turns</h3><button class="refresh-btn" id="refresh-traces">Refresh</button></div>
    <div id="traces-list">${renderTraces(traces)}</div>

    <div class="panel-header"><h3>Evals</h3><button class="refresh-btn" id="run-evals-btn">Run evals</button></div>
    <div class="subtle-note">Also runs automatically every night — this button is only for checking sooner.</div>
    <div id="eval-runs-list">${renderEvalRuns(evalRuns)}</div>
  `;

  document.getElementById("refresh-traces").addEventListener("click", loadObservability);
  document.getElementById("run-evals-btn").addEventListener("click", runEvals);
  wireTraceExpanders(panel);
  wireEvalRunExpanders(panel);
  wireEvalTrendChart(document.getElementById("eval-trend-chart"));
}

function renderTraces(traces) {
  if (!traces.length) return '<div class="empty-state">No turns recorded yet.</div>';
  return traces
    .map(
      (t) => `
    <div class="list-item${t.status === "error" ? " is-error" : ""}" data-trace-id="${t.id}">
      <div class="list-title">${escapeHtml(t.input_preview || "(no input)")}</div>
      <div class="list-meta">${new Date(t.started_at).toLocaleString()} · ${fmtUsd(t.cost_usd)} · ${Math.round(t.duration_ms || 0)}ms${t.status === "error" ? " · ERROR" : ""}</div>
      <div class="list-detail" style="display:none"></div>
    </div>`
    )
    .join("");
}

function wireTraceExpanders(panel) {
  panel.querySelectorAll("#traces-list .list-item").forEach((item) => {
    item.addEventListener("click", async () => {
      const detail = item.querySelector(".list-detail");
      const isOpen = detail.style.display !== "none";
      if (isOpen) {
        detail.style.display = "none";
        return;
      }
      if (!detail.dataset.loaded) {
        try {
          const trace = await apiGet(`/api/observability/traces/${item.dataset.traceId}`);
          detail.innerHTML =
            `<div><strong>Output:</strong> ${escapeHtml(trace.output || "(none)")}</div>` +
            trace.spans
              .map(
                (s) =>
                  `<div class="span-row">[${s.kind}] ${escapeHtml(s.name)}${s.status === "error" ? " ⚠️" : ""} — ${Math.round(s.duration_ms || 0)}ms${s.cost_usd ? " · " + fmtUsd(s.cost_usd) : ""}</div>`
              )
              .join("");
          detail.dataset.loaded = "1";
        } catch (err) {
          detail.innerHTML = `Failed to load: ${escapeHtml(err.message)}`;
        }
      }
      detail.style.display = "block";
    });
  });
}

function renderEvalRuns(runs) {
  if (!runs.length) return '<div class="empty-state">No eval runs yet — click "Run evals", or wait for tonight\'s scheduled run.</div>';
  // runs is DESC (newest first), so runs[i + 1] is the run immediately before this one.
  return runs
    .map((r, i) => {
      const prev = runs[i + 1];
      const delta = prev
        ? renderDelta(r.avg_score, prev.avg_score, { higherIsBetter: true, formatter: (v) => (v * 100).toFixed(0), suffix: "%" })
        : "";
      return `
    <div class="list-item" data-run-id="${r.id}">
      <div class="list-title">${new Date(r.started_at).toLocaleString()}${r.model ? ` · ${escapeHtml(r.model)}` : ""}</div>
      <div class="list-meta">${r.passed_count}/${r.case_count} passed · avg score ${(r.avg_score || 0).toFixed(2)}</div>
      ${delta}
      <div class="list-detail" style="display:none"></div>
    </div>`;
    })
    .join("");
}

// Fixed 0-1 scale (not auto-scaled to the data's own min/max) so a flat line
// near the top reads as "consistently good" rather than being stretched into
// looking volatile — an eval score chart's honesty depends on a stable scale.
function renderEvalTrendChart(trend) {
  if (!trend.length) {
    return '<div class="empty-state">No eval runs yet — click "Run evals" below, or wait for tonight\'s scheduled run.</div>';
  }
  const w = 600, h = 140, padX = 10, padY = 18;
  const xOf = (i) => (trend.length > 1 ? padX + (i * (w - padX * 2)) / (trend.length - 1) : w / 2);
  const yOf = (v) => padY + (1 - v) * (h - padY * 2);

  const linePath = trend.map((r, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(r.avg_score).toFixed(1)}`).join(" ");

  const gridLines = [0, 0.5, 0.7, 1]
    .map((v) => `<line class="eval-chart-grid" x1="${padX}" x2="${w - padX}" y1="${yOf(v).toFixed(1)}" y2="${yOf(v).toFixed(1)}"></line>`)
    .join("");

  const dots = trend
    .map((r, i) => {
      const x = xOf(i).toFixed(1);
      const y = yOf(r.avg_score).toFixed(1);
      const dateLabel = new Date(r.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
      return `<circle class="eval-chart-dot" cx="${x}" cy="${y}" r="4"
        data-date="${escapeHtml(dateLabel)}" data-score="${(r.avg_score * 100).toFixed(0)}"
        data-passed="${r.passed_count}" data-cases="${r.case_count}" data-model="${escapeHtml(r.model || "unknown")}"></circle>`;
    })
    .join("");

  const last = trend[trend.length - 1];

  return `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      ${gridLines}
      <path class="eval-chart-line" d="${linePath}"></path>
      ${dots}
      <text class="eval-chart-label" x="${xOf(trend.length - 1).toFixed(1)}" y="${(yOf(last.avg_score) - 10).toFixed(1)}" text-anchor="end">${(last.avg_score * 100).toFixed(0)}%</text>
    </svg>
    <div class="eval-chart-tooltip"></div>
  `;
}

function wireEvalTrendChart(wrap) {
  if (!wrap) return;
  const tooltip = wrap.querySelector(".eval-chart-tooltip");
  if (!tooltip) return;
  wrap.querySelectorAll(".eval-chart-dot").forEach((dot) => {
    dot.addEventListener("mouseenter", () => {
      const wrapRect = wrap.getBoundingClientRect();
      const dotRect = dot.getBoundingClientRect();
      tooltip.innerHTML = `<strong>${dot.dataset.score}%</strong> · ${dot.dataset.passed}/${dot.dataset.cases} passed<br>${dot.dataset.date} · ${dot.dataset.model}`;
      tooltip.style.display = "block";
      // Center on the dot, then clamp so it can't overflow either edge of the
      // chart — the naive centered position clips for points near the ends
      // (e.g. the first/last run, which is exactly where you're most likely
      // to hover to see "what just happened").
      const dotCenterX = dotRect.left - wrapRect.left + dotRect.width / 2;
      const tooltipWidth = tooltip.offsetWidth;
      const minLeft = tooltipWidth / 2;
      const maxLeft = wrapRect.width - tooltipWidth / 2;
      const clampedX = Math.max(minLeft, Math.min(maxLeft, dotCenterX));
      tooltip.style.left = `${clampedX}px`;
      tooltip.style.top = `${dotRect.top - wrapRect.top}px`;
    });
    dot.addEventListener("mouseleave", () => {
      tooltip.style.display = "none";
    });
  });
}

function wireEvalRunExpanders(panel) {
  panel.querySelectorAll("#eval-runs-list .list-item").forEach((item) => {
    item.addEventListener("click", async () => {
      const detail = item.querySelector(".list-detail");
      const isOpen = detail.style.display !== "none";
      if (isOpen) {
        detail.style.display = "none";
        return;
      }
      if (!detail.dataset.loaded) {
        try {
          const run = await apiGet(`/api/observability/evals/runs/${item.dataset.runId}`);
          detail.innerHTML = run.results
            .map(
              (res) =>
                `<div class="span-row">${res.passed ? "✅" : "❌"} ${escapeHtml(res.case_name)} (${res.score.toFixed(2)}) — ${escapeHtml(res.judge_reasoning || "")}</div>`
            )
            .join("");
          detail.dataset.loaded = "1";
        } catch (err) {
          detail.innerHTML = `Failed to load: ${escapeHtml(err.message)}`;
        }
      }
      detail.style.display = "block";
    });
  });
}

async function runEvals() {
  const btn = document.getElementById("run-evals-btn");
  btn.textContent = "Running…";
  btn.disabled = true;
  try {
    await apiPost("/api/observability/evals/run", {});
    await loadObservability();
  } catch (err) {
    alert("Eval run failed: " + err.message);
    btn.textContent = "Run evals";
    btn.disabled = false;
  }
}

// --- Goals ---------------------------------------------------------------

async function loadGoals() {
  const panel = document.getElementById("goals-panel");
  panel.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const data = await apiGet("/api/goals");
    renderGoals(panel, data.goals);
  } catch (err) {
    panel.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function renderGoals(panel, goals) {
  panel.innerHTML = `
    <div class="new-goal-form">
      <input id="new-goal-title" type="text" placeholder="New goal title">
      <input id="new-goal-date" type="text" placeholder="Target date (optional)">
      <button id="new-goal-btn">Add</button>
    </div>
    <div id="goals-list" class="${goals.length ? "card-grid" : ""}">
      ${goals.length ? goals.map(renderGoalCard).join("") : '<div class="empty-state">No goals tracked yet — add one above, or ask Edith in chat.</div>'}
    </div>
  `;

  document.getElementById("new-goal-btn").addEventListener("click", async () => {
    const titleEl = document.getElementById("new-goal-title");
    const dateEl = document.getElementById("new-goal-date");
    const title = titleEl.value.trim();
    if (!title) return;
    try {
      await apiPost("/api/goals", { title, target_date: dateEl.value.trim() });
      loadGoals();
    } catch (err) {
      alert("Failed to create goal: " + err.message);
    }
  });

  wireGoalCardActions(panel);
}

const STATUS_ICON = { active: "○", done: "✓", dropped: "✕" };

function renderGoalCard(goal) {
  const done = goal.milestones.filter((m) => m.done).length;
  const total = goal.milestones.length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  return `
    <div class="goal-card" data-goal-id="${goal.id}">
      <div class="goal-card-top">
        <span class="goal-icon-badge">${STATUS_ICON[goal.status] || "🎯"}</span>
        ${total ? `<span class="fraction-pill">${done}/${total}</span>` : ""}
      </div>
      <div class="goal-title">${escapeHtml(goal.title)}</div>
      <div class="goal-meta">${goal.description ? escapeHtml(goal.description) : "no extra detail"}</div>
      ${
        total
          ? `<div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div><div class="progress-puck" style="left:${pct}%"></div></div>`
          : ""
      }
      <div class="goal-date-row"><span>${goal.status}</span><span>${goal.target_date ? "due " + escapeHtml(goal.target_date) : "no target date"}</span></div>
      <div class="milestones">
        ${goal.milestones
          .map(
            (m) => `
          <div class="milestone${m.done ? " done" : ""}">
            <input type="checkbox" data-milestone-id="${m.id}" ${m.done ? "checked" : ""}>
            <label>${escapeHtml(m.title)}</label>
          </div>`
          )
          .join("")}
      </div>
      <div class="add-milestone-form">
        <input type="text" placeholder="Add milestone" data-add-milestone="${goal.id}">
        <button data-add-milestone-btn="${goal.id}">Add</button>
      </div>
      <div class="goal-actions">
        ${goal.status !== "done" ? `<button data-goal-status="${goal.id}" data-status="done">Mark done</button>` : ""}
        ${goal.status !== "active" ? `<button data-goal-status="${goal.id}" data-status="active">Reactivate</button>` : ""}
        ${goal.status !== "dropped" ? `<button data-goal-status="${goal.id}" data-status="dropped">Drop</button>` : ""}
        <button data-goal-delete="${goal.id}">Delete</button>
      </div>
    </div>`;
}

function wireGoalCardActions(panel) {
  panel.querySelectorAll("input[type=checkbox][data-milestone-id]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      try {
        await apiPost(`/api/milestones/${cb.dataset.milestoneId}/complete`, { done: cb.checked });
        loadGoals();
      } catch (err) {
        alert("Failed to update milestone: " + err.message);
      }
    });
  });

  panel.querySelectorAll("[data-add-milestone-btn]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const goalId = btn.dataset.addMilestoneBtn;
      const input = panel.querySelector(`[data-add-milestone="${goalId}"]`);
      const title = input.value.trim();
      if (!title) return;
      try {
        await apiPost(`/api/goals/${goalId}/milestones`, { title });
        loadGoals();
      } catch (err) {
        alert("Failed to add milestone: " + err.message);
      }
    });
  });

  panel.querySelectorAll("[data-goal-status]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await apiPost(`/api/goals/${btn.dataset.goalStatus}/update`, { status: btn.dataset.status });
        loadGoals();
      } catch (err) {
        alert("Failed to update goal: " + err.message);
      }
    });
  });

  panel.querySelectorAll("[data-goal-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this goal and its milestones?")) return;
      try {
        await apiPost(`/api/goals/${btn.dataset.goalDelete}/delete`, {});
        loadGoals();
      } catch (err) {
        alert("Failed to delete goal: " + err.message);
      }
    });
  });
}

// --- Todos -----------------------------------------------------------------

async function loadTodos() {
  const panel = document.getElementById("todos-panel");
  panel.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const data = await apiGet("/api/todos");
    renderTodos(panel, data.todos);
  } catch (err) {
    panel.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function renderTodos(panel, todos) {
  panel.innerHTML = `
    <div class="new-goal-form">
      <input id="new-todo-title" type="text" placeholder="New todo">
      <input id="new-todo-date" type="text" placeholder="Due date (optional)">
      <button id="new-todo-btn">Add</button>
    </div>
    <div id="todos-list">
      ${todos.length ? todos.map(renderTodoCard).join("") : '<div class="empty-state">No todos yet — add one above, or ask Edith in chat.</div>'}
    </div>
  `;

  document.getElementById("new-todo-btn").addEventListener("click", async () => {
    const titleEl = document.getElementById("new-todo-title");
    const dateEl = document.getElementById("new-todo-date");
    const title = titleEl.value.trim();
    if (!title) return;
    try {
      await apiPost("/api/todos", { title, due_date: dateEl.value.trim() });
      loadTodos();
    } catch (err) {
      alert("Failed to create todo: " + err.message);
    }
  });

  wireTodoCardActions(panel);
}

const TODO_STATUS_LABEL = { todo: "To do", in_progress: "In progress", done: "Done" };
const TODO_NEXT_STATUS = { todo: "in_progress", in_progress: "done", done: "todo" };

function renderTodoCard(todo) {
  return `
    <div class="todo-card" data-todo-id="${todo.id}">
      <div class="todo-card-top">
        <div class="todo-title${todo.status === "done" ? " done" : ""}">${escapeHtml(todo.title)}</div>
        <span class="todo-status-pill ${todo.status}">${TODO_STATUS_LABEL[todo.status]}</span>
      </div>
      <div class="todo-meta">${todo.due_date ? "due " + escapeHtml(todo.due_date) : "no due date"}</div>
      ${todo.note ? `<div class="todo-note">${escapeHtml(todo.note)}</div>` : ""}
      <div class="todo-actions">
        <button data-todo-cycle="${todo.id}" data-next="${TODO_NEXT_STATUS[todo.status]}">Mark ${TODO_STATUS_LABEL[TODO_NEXT_STATUS[todo.status]].toLowerCase()}</button>
        <button data-todo-delete="${todo.id}">Delete</button>
      </div>
    </div>`;
}

function wireTodoCardActions(panel) {
  panel.querySelectorAll("[data-todo-cycle]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await apiPost(`/api/todos/${btn.dataset.todoCycle}/update`, { status: btn.dataset.next });
        loadTodos();
      } catch (err) {
        alert("Failed to update todo: " + err.message);
      }
    });
  });

  panel.querySelectorAll("[data-todo-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this todo?")) return;
      try {
        await apiPost(`/api/todos/${btn.dataset.todoDelete}/delete`, {});
        loadTodos();
      } catch (err) {
        alert("Failed to delete todo: " + err.message);
      }
    });
  });
}

// --- Insights --------------------------------------------------------------

const INSIGHT_ICON = { insight: "💡", goal_update: "🎯", observation: "👀" };

async function loadInsights() {
  const panel = document.getElementById("insights-panel");
  panel.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const [data, research] = await Promise.all([
      apiGet("/api/insights", { unseen_only: true, limit: 50 }),
      apiGet("/api/deep-research/runs", { limit: 3 }),
    ]);
    renderInsights(panel, data.insights, research.replies);
  } catch (err) {
    panel.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function renderInsights(panel, insights, researchReplies) {
  const insightsBody = !insights.length
    ? '<div class="empty-state">Nothing new — Edith will queue things here when she notices something worth flagging.</div>'
    : `<div class="card-grid">${insights
        .map(
          (i) => `
    <div class="insight-card" data-insight-id="${i.id}">
      <div class="insight-title">${INSIGHT_ICON[i.kind] || "💡"} ${escapeHtml(i.title)}</div>
      ${i.body ? `<div class="insight-body">${escapeHtml(i.body)}</div>` : ""}
      <div class="insight-meta">${new Date(i.created_at).toLocaleString()}</div>
      <button class="dismiss-btn" data-dismiss="${i.id}">Dismiss</button>
    </div>`
        )
        .join("")}</div>`;

  panel.innerHTML = `
    <div class="panel-header"><h3>Deep research</h3><button class="refresh-btn" id="run-deep-research-btn">Run deep research</button></div>
    <div class="subtle-note">Kicks off an overnight run: 3 rounds (broad scan, elimination, final synthesis) a couple hours apart, budget-capped. Lands here and as a push notification when the last round finishes.</div>
    <div id="deep-research-runs">${renderDeepResearchRuns(researchReplies)}</div>

    <div class="panel-header"><h3>Insights</h3></div>
    ${insightsBody}
  `;

  document.getElementById("run-deep-research-btn").addEventListener("click", runDeepResearch);

  panel.querySelectorAll("[data-dismiss]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await apiPost(`/api/insights/${btn.dataset.dismiss}/dismiss`, {});
        loadInsights();
      } catch (err) {
        alert("Failed to dismiss: " + err.message);
      }
    });
  });
}

function renderDeepResearchRuns(replies) {
  if (!replies.length) {
    return '<div class="empty-state">No job output yet — click "Run deep research" to kick one off overnight, or check back after tonight\'s scheduled jobs run.</div>';
  }
  // Same feed the /jobs chat command shows (nightly reflection + one-off jobs included) —
  // deep research output isn't tagged separately from other scheduled-job output.
  return replies
    .map(
      (r) => `
    <div class="list-item">
      <div class="list-meta">${new Date(r.created_at).toLocaleString()}</div>
      <div class="insight-body">${escapeHtml(r.content)}</div>
    </div>`
    )
    .join("");
}

async function runDeepResearch() {
  const btn = document.getElementById("run-deep-research-btn");
  btn.textContent = "Starting…";
  btn.disabled = true;
  try {
    await apiPost("/api/deep-research/run", {});
    btn.textContent = "Started ✓";
    setTimeout(() => {
      btn.textContent = "Run deep research";
      btn.disabled = false;
    }, 3000);
  } catch (err) {
    alert("Failed to start deep research: " + err.message);
    btn.textContent = "Run deep research";
    btn.disabled = false;
  }
}

// --- MCP servers (Integrations) --------------------------------------------
//
// Add any stdio-based MCP server (command + args, optional env vars) — its
// tools get discovered and merged into Edith's toolset on the next server
// restart, not immediately (see edith/tools/mcp_client.py).

async function loadMcpServers() {
  const panel = document.getElementById("mcp-panel");
  panel.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    const data = await apiGet("/api/mcp/servers");
    renderMcpServers(panel, data.servers);
  } catch (err) {
    panel.innerHTML = `<div class="empty-state">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function renderMcpServers(panel, servers) {
  panel.innerHTML = `
    <div class="subtle-note">Adding, removing, or toggling a server here takes effect the next time Edith's backend restarts — tools are discovered once at startup, not live.</div>
    <div class="new-mcp-form">
      <div class="new-mcp-form-row">
        <input id="new-mcp-name" type="text" placeholder="Name (e.g. web-search)">
        <input id="new-mcp-command" type="text" placeholder="Command (e.g. uvx)">
      </div>
      <div class="new-mcp-form-row">
        <input id="new-mcp-args" type="text" placeholder="Args, space-separated (e.g. heventure-search-mcp)">
      </div>
      <div class="new-mcp-form-row">
        <input id="new-mcp-env" type="text" placeholder="Env vars, optional (KEY=value, comma-separated)">
      </div>
      <div class="new-mcp-form-row">
        <button id="new-mcp-btn">Add server</button>
      </div>
    </div>
    <div id="mcp-list">
      ${servers.length ? servers.map(renderMcpCard).join("") : '<div class="empty-state">No MCP servers configured yet — add one above.</div>'}
    </div>
  `;

  document.getElementById("new-mcp-btn").addEventListener("click", async () => {
    const name = document.getElementById("new-mcp-name").value.trim();
    const command = document.getElementById("new-mcp-command").value.trim();
    const argsRaw = document.getElementById("new-mcp-args").value.trim();
    const envRaw = document.getElementById("new-mcp-env").value.trim();
    if (!name || !command) return;

    const args = argsRaw ? argsRaw.split(/\s+/) : [];
    let env = null;
    if (envRaw) {
      env = {};
      for (const pair of envRaw.split(",")) {
        const idx = pair.indexOf("=");
        if (idx === -1) continue;
        env[pair.slice(0, idx).trim()] = pair.slice(idx + 1).trim();
      }
    }

    try {
      await apiPost("/api/mcp/servers", { name, command, args, env });
      loadMcpServers();
    } catch (err) {
      alert("Failed to add server: " + err.message);
    }
  });

  wireMcpCardActions(panel);
}

function renderMcpCard(server) {
  const args = JSON.parse(server.args_json || "[]");
  const fullCommand = [server.command, ...args].join(" ");
  return `
    <div class="mcp-card" data-mcp-id="${server.id}">
      <div class="mcp-card-top">
        <div>
          <div class="mcp-name">${escapeHtml(server.name)}</div>
          <div class="mcp-command">${escapeHtml(fullCommand)}</div>
        </div>
        <label class="mcp-toggle-label">
          <input type="checkbox" data-mcp-toggle="${server.id}" ${server.enabled ? "checked" : ""}>
          enabled
        </label>
      </div>
      <div class="mcp-card-actions">
        <button data-mcp-delete="${server.id}">Delete</button>
      </div>
    </div>`;
}

function wireMcpCardActions(panel) {
  panel.querySelectorAll("[data-mcp-toggle]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      try {
        await apiPost(`/api/mcp/servers/${cb.dataset.mcpToggle}/toggle`, { enabled: cb.checked });
      } catch (err) {
        alert("Failed to update server: " + err.message);
        cb.checked = !cb.checked;
      }
    });
  });

  panel.querySelectorAll("[data-mcp-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this MCP server?")) return;
      try {
        await apiPost(`/api/mcp/servers/${btn.dataset.mcpDelete}/delete`, {});
        loadMcpServers();
      } catch (err) {
        alert("Failed to delete server: " + err.message);
      }
    });
  });
}

// --- Monitor ("Situation Monitor" tab) --------------------------------------
//
// Deliberately its own dense, dark, monospace visual world (see the `.mon-*`
// classes/tokens in index.html) — not Edith's rounded light/dark app theme.
// Revenue (Dodo Payments), analytics (Vercel), and shipping log (GitHub) each
// call a live external API on the backend on every load — no local caching —
// and each independently reports {configured:false} rather than erroring
// when its own credentials aren't set, so one missing integration never
// blocks the rest of the tab. Ideas + Bugs is real CRUD (no external source);
// Social media summarizes what /skill-talk and save_social_skill have saved.

function fmtMoney(value) {
  const n = Number(value || 0);
  return "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function monTile(value, label, note) {
  return `<div class="mon-tile"><div class="mon-tile-value">${value}</div><div class="mon-tile-label">${label}</div>${note ? `<div class="mon-tile-note">${note}</div>` : ""}</div>`;
}

function monTileEmpty(label, note) {
  return `<div class="mon-tile"><div class="mon-tile-value is-empty">—</div><div class="mon-tile-label">${label}</div><div class="mon-tile-note">${escapeHtml(note)}</div></div>`;
}

function monTileError(label, note) {
  return `<div class="mon-tile"><div class="mon-tile-value is-empty">—</div><div class="mon-tile-label">${escapeHtml(label)}</div><div class="mon-tile-note is-error">${escapeHtml(note)}</div></div>`;
}

// Deterministic color per project/repo label (same tag colors every reload)
// — six-color palette from the `.mon-tag-N` CSS custom properties, cycled by
// a stable hash of the label so it doesn't depend on insertion order.
const MON_TAG_COUNT = 6;
function monTagColor(label) {
  let hash = 0;
  for (let i = 0; i < label.length; i++) hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
  return `var(--mon-tag-${hash % MON_TAG_COUNT})`;
}

function monTag(label) {
  return `<span class="mon-tag" style="color:${monTagColor(label)}">${escapeHtml(label)}</span>`;
}

async function loadMonitor() {
  const panel = document.getElementById("monitor-panel");
  panel.innerHTML = '<div class="mon-empty">Loading…</div>';
  try {
    const [revenue, analytics, shipping, social, ideasBugs] = await Promise.all([
      apiGet("/api/monitor/revenue"),
      apiGet("/api/monitor/analytics"),
      apiGet("/api/monitor/shipping"),
      apiGet("/api/monitor/social"),
      apiGet("/api/monitor/ideas-bugs", { status: "open" }),
    ]);
    renderMonitor(panel, revenue, analytics, shipping, social, ideasBugs.items);
  } catch (err) {
    panel.innerHTML = `<div class="mon-empty">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function renderMonitor(panel, revenue, analytics, shipping, social, ideasBugs) {
  panel.innerHTML = `
    <div class="mon-row">
      <div class="mon-section-title">Revenue</div>
      <div class="mon-stat-row">${renderRevenueStats(revenue)}</div>
    </div>

    <div class="mon-row mon-grid">
      <div class="mon-panel">
        <div class="mon-section-title">Analytics</div>
        <div class="mon-stat-row" id="monitor-analytics">${renderAnalyticsStats(analytics)}</div>
        ${renderVercelProjectForm(analytics.projects || [])}
      </div>

      <div class="mon-panel">
        <div class="mon-section-title">Shipping log</div>
        <div id="monitor-shipping">${renderShippingLog(shipping)}</div>
        ${renderShippingRepoForm(shipping.repos || [])}
      </div>

      <div class="mon-panel">
        <div class="mon-section-title">Ideas + bugs</div>
        ${renderIdeaBugForm()}
        <div id="monitor-ideas-bugs">${renderIdeasBugs(ideasBugs)}</div>
      </div>
    </div>

    <div class="mon-row mon-grid">
      <div class="mon-panel">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <div class="mon-section-title" style="margin-bottom:0">Live news</div>
          <button class="mon-refresh" id="monitor-news-refresh">Refresh</button>
        </div>
        <div class="mon-form"><input id="monitor-news-topic" type="text" placeholder="Topic (optional)"></div>
        <div id="monitor-news" style="margin-top:8px;"><div class="mon-empty">Click Refresh to fetch the latest headlines.</div></div>
      </div>

      <div class="mon-panel">
        <div class="mon-section-title">Social media</div>
        <div id="monitor-social">${renderSocialSummary(social)}</div>
      </div>
    </div>
  `;

  wireMonitorActions(panel);
}

function renderRevenueStats(revenue) {
  const tiles = [];
  if (!revenue.configured) {
    ["Gross revenue", "MRR", "Net revenue", "Last payment"].forEach((label) => tiles.push(monTileEmpty(label, "Dodo Payments not connected")));
  } else if (revenue.error) {
    ["Gross revenue", "MRR", "Net revenue", "Last payment"].forEach((label) => tiles.push(monTileError(label, "Dodo Payments error")));
  } else {
    tiles.push(monTile(fmtMoney(revenue.gross_revenue_usd), "Gross revenue"));
    tiles.push(monTile(fmtMoney(revenue.mrr_usd), "MRR"));
    tiles.push(monTile(fmtMoney(revenue.net_revenue_usd), "Net revenue"));
    const lp = revenue.last_payment;
    const lpNote = lp ? `${lp.customer_name ? escapeHtml(lp.customer_name) + " · " : ""}${timeAgo(lp.created_at)}` : "";
    tiles.push(monTile(lp ? fmtMoney(lp.amount_usd) : "—", "Last payment", lpNote));
  }
  return tiles.join("");
}

// analytics.projects is one entry per tracked Vercel project (see
// track_vercel_project) — a personal dashboard tracking several apps needs a
// tile per app, not one blended number, so unlike revenue (a single Dodo
// account) this renders a variable-length stat row.
function renderAnalyticsStats(analytics) {
  if (!analytics.configured) {
    return monTileEmpty("Pageviews (30d)", "No Vercel projects tracked yet");
  }
  if (!analytics.projects.length) {
    return monTileEmpty("Pageviews (30d)", "Vercel Analytics not connected");
  }
  return analytics.projects
    .map((p) =>
      p.error
        ? monTileError(p.label, "Vercel error")
        : monTile(p.pageviews.toLocaleString(), `${escapeHtml(p.label)} · ${p.days}d`)
    )
    .join("");
}

function renderVercelProjectForm(projects) {
  const chips = projects
    .map((p) => `<span class="mon-chip">${monTag(p.label)}<button data-remove-vercel-project="${escapeHtml(p.project_id)}" title="Stop tracking">×</button></span>`)
    .join("");
  return `
    ${chips ? `<div style="margin-top:12px;">${chips}</div>` : ""}
    <div class="mon-form">
      <input id="monitor-vercel-input" type="text" placeholder="Vercel project ID (prj_...)">
      <input id="monitor-vercel-label" type="text" placeholder="Label (optional)">
      <button class="mon-btn" id="monitor-vercel-add">Track</button>
    </div>
  `;
}

function renderShippingLog(shipping) {
  if (!shipping.configured) {
    return '<div class="mon-empty">No repos tracked yet — add one below to see recent commits.</div>';
  }
  if (!shipping.commits || !shipping.commits.length) {
    return '<div class="mon-empty">No recent commits found for the tracked repo(s).</div>';
  }
  return shipping.commits
    .map(
      (c) => `
    <div class="mon-list-row">
      <span class="mon-mono-id">${escapeHtml(c.sha)}</span>
      <span class="mon-main" title="${escapeHtml(c.message)}">${escapeHtml(c.message)}</span>
      <span class="mon-side">${monTag(c.label)} · ${timeAgo(c.date)}</span>
    </div>`
    )
    .join("");
}

function renderShippingRepoForm(repos) {
  const chips = repos
    .map((r) => `<span class="mon-chip">${monTag(r.label)}<button data-remove-repo="${escapeHtml(r.repo)}" title="Stop tracking">×</button></span>`)
    .join("");
  return `
    ${chips ? `<div style="margin-top:12px;">${chips}</div>` : ""}
    <div class="mon-form">
      <input id="monitor-repo-input" type="text" placeholder="owner/name (GitHub repo)">
      <input id="monitor-repo-label" type="text" placeholder="Label (optional)">
      <button class="mon-btn" id="monitor-repo-add">Track</button>
    </div>
  `;
}

function renderIdeaBugForm() {
  return `
    <div class="mon-form">
      <input id="monitor-ib-title" type="text" placeholder="Idea or bug title">
      <input id="monitor-ib-project" type="text" placeholder="Project (optional)">
      <select id="monitor-ib-kind">
        <option value="idea">Idea</option>
        <option value="bug">Bug</option>
      </select>
      <button class="mon-btn" id="monitor-ib-add">Add</button>
    </div>
  `;
}

function renderIdeasBugs(items) {
  if (!items.length) return '<div class="mon-empty">Nothing logged yet — add one above, or tell Edith in chat.</div>';
  return items.map(renderIdeaBugCard).join("");
}

function renderIdeaBugCard(item) {
  return `
    <div class="mon-item-card" data-item-id="${item.id}">
      <div class="mon-item-top">
        <span class="mon-item-title"><span class="mon-badge ${item.kind}">${item.kind}</span> ${escapeHtml(item.title)}</span>
        <span class="mon-item-meta">${timeAgo(item.created_at)}</span>
      </div>
      ${item.project ? `<div style="margin-top:4px;">${monTag(item.project)}</div>` : ""}
      ${item.note ? `<div class="mon-item-note">${escapeHtml(item.note)}</div>` : ""}
      <div class="mon-item-actions">
        <button data-resolve-ib="${item.id}">Resolve</button>
        <button data-delete-ib="${item.id}">Delete</button>
      </div>
    </div>`;
}

function renderNews(text) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return '<div class="mon-empty">No headlines found.</div>';
  return lines.map((l) => `<div class="mon-news-item">${escapeHtml(l)}</div>`).join("");
}

function renderSocialSummary(social) {
  const strategy = social.content_strategy || [];
  const skills = social.skills || [];
  if (!strategy.length && !skills.length) {
    return '<div class="mon-empty">Nothing saved yet — use /skill-talk in chat to tell Edith about your content goals.</div>';
  }
  const row = (title, meta) => `<div class="mon-list-row"><span class="mon-main">${escapeHtml(title)}</span><span class="mon-side" title="${escapeHtml(meta)}">${escapeHtml(meta.length > 40 ? meta.slice(0, 40) + "…" : meta)}</span></div>`;
  const strategyBlock = strategy.length
    ? strategy.map((f) => row(f.key, f.value)).join("")
    : '<div class="mon-empty">No content strategy saved yet — use /skill-talk.</div>';
  const skillsBlock = skills.length
    ? skills.map((s) => row(s.title, s.preview)).join("")
    : '<div class="mon-empty">No skill files saved yet.</div>';
  return `<div class="mon-section-title" style="margin-top:0">Content strategy</div>${strategyBlock}<div class="mon-section-title" style="margin-top:16px">Skill files</div>${skillsBlock}`;
}

function wireMonitorActions(panel) {
  document.getElementById("monitor-vercel-add").addEventListener("click", async () => {
    const idEl = document.getElementById("monitor-vercel-input");
    const labelEl = document.getElementById("monitor-vercel-label");
    const projectId = idEl.value.trim();
    if (!projectId) return;
    try {
      await apiPost("/api/monitor/analytics/projects", { project_id: projectId, label: labelEl.value.trim() });
      loadMonitor();
    } catch (err) {
      alert("Failed to track project: " + err.message);
    }
  });

  panel.querySelectorAll("[data-remove-vercel-project]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await apiPost("/api/monitor/analytics/projects/delete", { project_id: btn.dataset.removeVercelProject });
        loadMonitor();
      } catch (err) {
        alert("Failed to untrack project: " + err.message);
      }
    });
  });

  document.getElementById("monitor-repo-add").addEventListener("click", async () => {
    const repoEl = document.getElementById("monitor-repo-input");
    const labelEl = document.getElementById("monitor-repo-label");
    const repo = repoEl.value.trim();
    if (!repo) return;
    try {
      await apiPost("/api/monitor/shipping/repos", { repo, label: labelEl.value.trim() });
      loadMonitor();
    } catch (err) {
      alert("Failed to track repo: " + err.message);
    }
  });

  panel.querySelectorAll("[data-remove-repo]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await apiPost("/api/monitor/shipping/repos/delete", { repo: btn.dataset.removeRepo });
        loadMonitor();
      } catch (err) {
        alert("Failed to untrack repo: " + err.message);
      }
    });
  });

  document.getElementById("monitor-ib-add").addEventListener("click", async () => {
    const titleEl = document.getElementById("monitor-ib-title");
    const projectEl = document.getElementById("monitor-ib-project");
    const kindEl = document.getElementById("monitor-ib-kind");
    const title = titleEl.value.trim();
    if (!title) return;
    try {
      await apiPost("/api/monitor/ideas-bugs", { kind: kindEl.value, title, project: projectEl.value.trim() });
      loadMonitor();
    } catch (err) {
      alert("Failed to add: " + err.message);
    }
  });

  panel.querySelectorAll("[data-resolve-ib]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await apiPost(`/api/monitor/ideas-bugs/${btn.dataset.resolveIb}/resolve`, {});
        loadMonitor();
      } catch (err) {
        alert("Failed to resolve: " + err.message);
      }
    });
  });

  panel.querySelectorAll("[data-delete-ib]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this?")) return;
      try {
        await apiPost(`/api/monitor/ideas-bugs/${btn.dataset.deleteIb}/delete`, {});
        loadMonitor();
      } catch (err) {
        alert("Failed to delete: " + err.message);
      }
    });
  });

  document.getElementById("monitor-news-refresh").addEventListener("click", async () => {
    const btn = document.getElementById("monitor-news-refresh");
    const newsEl = document.getElementById("monitor-news");
    const topic = document.getElementById("monitor-news-topic").value.trim();
    btn.textContent = "Loading…";
    btn.disabled = true;
    try {
      const data = await apiGet("/api/monitor/news", { topic });
      newsEl.innerHTML = renderNews(data.text);
    } catch (err) {
      newsEl.innerHTML = `<div class="mon-empty">Failed to load: ${escapeHtml(err.message)}</div>`;
    }
    btn.textContent = "Refresh";
    btn.disabled = false;
  });
}
