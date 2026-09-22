"""Monid integration — lets Edith discover and call third-party data
endpoints (web/social scraping, enrichment, search) via the `monid` CLI
(https://monid.ai), installed and authenticated on the host machine
(`monid keys list` shows the active key; config lives at ~/.config/monid).

Sonali explicitly chose fully-autonomous execution — including paid
endpoints — over gating runs through the pending_actions/approve flow that
send_email/create_calendar_event use. Cost exposure here is bounded by
Monid's own workspace budget/run-cap controls (app.monid.ai), not by an
in-chat approval step; a run can come back BLOCKED if a control trips.

Tool functions shell out to the CLI (synchronous subprocess, matching every
other tool in this registry) with `-j` for JSON output. discover results are
reformatted into compact lines for the model; inspect/run/runs_get/balance
are passed through as raw (truncated) JSON text since their schema varies
per endpoint and isn't worth guessing at.
"""

import json
import subprocess

from edith.tools.registry import ToolRegistry

MONID_TIMEOUT_SECONDS = 45  # CLI itself caps --wait at 120s; this is the subprocess hard ceiling around it
_OUTPUT_CHARS = 6000  # cap so one large scrape result can't blow out the tool-call context budget

# Live-observed 2026-07-21: a real monid_run against a Heurist Twitter-intelligence endpoint returned
# an article whose *content field* was cut off mid-sentence by the provider with "…(truncated)", well
# under our own _OUTPUT_CHARS cap — so the provider truncates server-side too, not just us. Edith still
# stated a specific, invented valuation figure attributed to "data retrieved via" that call, because
# nothing in the tool text told her the data was incomplete. This banner is the fix: flag truncation
# (ours or upstream — both use "(truncated)") right in the tool message itself, at the exact place the
# model reads it, rather than relying only on a general system-prompt honesty rule to catch it.
_TRUNCATION_WARNING = (
    "\n\n[SYSTEM NOTE: the result above was truncated/cut short (by Monid or by us) — treat it as "
    "incomplete. Only state facts, numbers, or quotes that literally appear above; do not infer, "
    "estimate, or fill in what the truncated part might have said.]"
)


def _truncate(text: str) -> str:
    return text if len(text) <= _OUTPUT_CHARS else text[:_OUTPUT_CHARS] + "…(truncated)"


def _flag_if_truncated(text: str) -> str:
    return text + _TRUNCATION_WARNING if "(truncated)" in text.lower() else text


def _run_monid(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["monid", *args, "-j"],
            capture_output=True,
            text=True,
            timeout=MONID_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return "ERROR: the monid CLI is not installed on this machine."
    except subprocess.TimeoutExpired:
        return f"ERROR: monid {' '.join(args)} timed out after {MONID_TIMEOUT_SECONDS}s."
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return f"ERROR: monid {' '.join(args)} failed: {output}"
    return _flag_if_truncated(_truncate(output))


def register(registry: ToolRegistry) -> None:
    def monid_discover(query: str, limit: int = 10) -> str:
        raw = _run_monid(["discover", "-q", query, "-l", str(limit)])
        if raw.startswith("ERROR"):
            return raw
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        results = data if isinstance(data, list) else data.get("results", [])
        if not results:
            return "No matching endpoints found."
        lines = [
            f"{r.get('provider')}/{r.get('endpoint')} (score={r.get('score')}, verified={r.get('verified')}): "
            f"{r.get('description', '')}"
            for r in results[:limit]
        ]
        return "\n".join(lines)

    def monid_inspect(provider: str, endpoint: str) -> str:
        return _run_monid(["inspect", "-p", provider, "-e", endpoint])

    def monid_run(
        provider: str,
        endpoint: str,
        body_json: str = "",
        query_json: str = "",
        path_json: str = "",
        wait_seconds: int = 30,
    ) -> str:
        args = ["run", "-p", provider, "-e", endpoint, "-w", str(max(1, min(wait_seconds, 60)))]
        if body_json:
            args += ["-i", body_json]
        if query_json:
            args += ["--query", query_json]
        if path_json:
            args += ["--path", path_json]
        return _run_monid(args)

    def monid_runs_get(run_id: str) -> str:
        return _run_monid(["runs", "get", "-r", run_id])

    def monid_balance() -> str:
        return _run_monid(["balance"])

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "monid_discover",
                "description": (
                    "Search Monid's catalog of hundreds of external data/tool endpoints (web scraping, "
                    "social media — Twitter/LinkedIn/etc, enrichment, search) by natural language. Always "
                    "run this before writing a custom scraper, calling a third-party API directly, or "
                    "telling the user you can't access something — a faster, ready-made endpoint often "
                    "already exists. Use a short noun-phrase query (e.g. 'twitter posts', not a full "
                    "sentence). Always call monid_inspect on a chosen result before monid_run."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Short noun-phrase search, e.g. 'linkedin posts'"},
                        "limit": {"type": "integer", "description": "Max results to return (default 10)"},
                    },
                    "required": ["query"],
                },
            },
        },
        monid_discover,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "monid_inspect",
                "description": (
                    "Get the input schema (pathParams, queryParams, body) for a Monid endpoint found via "
                    "monid_discover. Always call this before monid_run — never guess an endpoint's parameters."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "description": "Provider slug from monid_discover, e.g. 'apify'"},
                        "endpoint": {"type": "string", "description": "Endpoint path from monid_discover, e.g. '/apidojo/tweet-scraper'"},
                    },
                    "required": ["provider", "endpoint"],
                },
            },
        },
        monid_inspect,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "monid_run",
                "description": (
                    "Execute a Monid endpoint (after inspecting its schema with monid_inspect) and wait for "
                    "the result. Many endpoints are billed per result — pass a single search term/URL/hashtag "
                    "and a small limit (5-10) unless the user explicitly wants more; some parameters (e.g. "
                    "maxItems) apply per query, not per call, so multiple queries multiply cost. If the run "
                    "comes back BLOCKED, a workspace budget/run cap stopped it — tell the user they can "
                    "adjust that at app.monid.ai."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "endpoint": {"type": "string"},
                        "body_json": {"type": "string", "description": "JSON string for the body input, per monid_inspect's schema"},
                        "query_json": {"type": "string", "description": "JSON string for query params, per monid_inspect's schema"},
                        "path_json": {"type": "string", "description": "JSON string for path params, per monid_inspect's schema"},
                        "wait_seconds": {"type": "integer", "description": "How long to block for the result, 1-60 (default 30)"},
                    },
                    "required": ["provider", "endpoint"],
                },
            },
        },
        monid_run,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "monid_runs_get",
                "description": "Check the status/result of a previously started Monid run by its run ID.",
                "parameters": {
                    "type": "object",
                    "properties": {"run_id": {"type": "string"}},
                    "required": ["run_id"],
                },
            },
        },
        monid_runs_get,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "monid_balance",
                "description": "Check the remaining Monid workspace balance — use when the user asks about Monid spend/budget.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        monid_balance,
    )
