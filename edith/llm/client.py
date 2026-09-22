"""OpenRouter chat-completions wrapper with a tool-calling loop.

Design constraints (see plan doc for rationale):
- Non-streaming only for v1.
- Malformed tool-call JSON / unknown tool names are caught and turned into
  `role: "tool"` error replies — never raised — so the tool_calls/tool
  message pairing contract is never broken.
- Iteration-capped; on cap, forces a plain-text answer with tools disabled.
- Retries transient errors with backoff; fails fast on auth errors and
  insufficient-credit (402) errors; retries once (with trimmed history,
  handled by the caller) on context-length errors; retries other 400s too
  (they're usually the model itself generating malformed tool-call JSON
  upstream, which is stochastic and often succeeds on retry).

Streaming was tried and reverted 2026-07-19: measured directly against the
real API, Gemini's chat models (both the OpenAI-compat endpoint and the
native genai SDK) deliver the entire response in one or two bursts right at
the end of generation rather than incrementally, and Gemini's TTS has a
~6.6s fixed cost per call regardless of text length — so neither streamed
completions nor per-sentence TTS chunking reduced time-to-first-audio; it
only added API calls. Don't re-attempt without new evidence one of those
provider-side constraints has changed.
"""

import json
import logging
import time
from typing import Any, Callable, Optional

import openai

from edith.config import MAX_RESPONSE_TOKENS, MAX_TOOL_ITERATIONS, OPENROUTER_BASE_URL
from edith.observability.tracing import Recorder

logger = logging.getLogger("edith.llm")

ToolDispatch = Callable[[str, dict], str]

EMPTY_RESPONSE_FALLBACK = (
    "Sorry — I worked through that but ran out of room to write out the answer. "
    "Try asking again, or breaking it into smaller steps."
)


class ContextLengthExceeded(Exception):
    pass


def make_client(api_key: str, base_url: str = OPENROUTER_BASE_URL) -> openai.OpenAI:
    """Works with any OpenAI-compatible endpoint — OpenRouter (default) or
    Gemini's compat endpoint (base_url=GEMINI_BASE_URL). Same wire format,
    same tool-calling loop, same retry logic below — just a different host."""
    return openai.OpenAI(base_url=base_url, api_key=api_key)


def _is_context_length_error(e: Exception) -> bool:
    text = str(e).lower()
    return "context_length" in text or "maximum context length" in text or "context length" in text


def _sanitize_for_api(messages: list[dict]) -> list[dict]:
    """Strip/coerce fields the official OpenAI schema allows but some
    OpenRouter-routed providers reject under stricter validation. OpenAI's own
    backend is lenient about all of this, which is why these only surface
    after switching models — this is the single place to patch the next one
    rather than chasing it through every call site that builds a message.

    - `name` on tool-role messages: kept in our own in-memory/DB representation
      (useful for logging and the /history command), but Alibaba's DashScope
      backend (Qwen models) 400s on the extra field.
    - `content: None` on assistant messages: valid for a tool-calls-only
      message, but DashScope 400s with "The content field is a required
      field" — coerce to "" as a last-resort safety net here, on top of the
      write/read-side fixes in run_completion_with_tools and
      edith/memory/store.py's _row_to_openai_message.
    """
    sanitized = []
    for m in messages:
        if m.get("role") == "tool" and "name" in m:
            m = {k: v for k, v in m.items() if k != "name"}
        if m.get("role") == "assistant" and m.get("content") is None:
            m = {**m, "content": ""}
        sanitized.append(m)
    return sanitized


def call_openrouter_chat(
    client: openai.OpenAI,
    messages: list[dict],
    tools: Optional[list[dict]],
    model: str,
    max_retries: int = 3,
):
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": _sanitize_for_api(messages),
        "max_tokens": MAX_RESPONSE_TOKENS,
    }
    if tools:
        kwargs["tools"] = tools

    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except openai.AuthenticationError:
            raise  # bad key — never retry
        except openai.BadRequestError as e:
            if _is_context_length_error(e):
                raise ContextLengthExceeded(str(e)) from e
            # Not a context-length issue — this is usually the model itself
            # generating malformed tool-call JSON upstream (seen across
            # multiple OpenRouter-routed providers for qwen3-coder-next: "Extra
            # data", "Can only get item pairs from a mapping", etc.), which is
            # stochastic and often succeeds on retry — confirmed live, the
            # identical request that 400'd once worked fine moments later.
            # Worth retrying, unlike a genuinely malformed request from us.
            if attempt == max_retries - 1:
                raise
            logger.warning("OpenRouter 400 (likely upstream malformed generation), retrying: %s", e)
            time.sleep(2**attempt)
        except openai.RateLimitError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt)
        except openai.APIStatusError as e:
            if e.status_code == 402:
                raise  # insufficient credits — permanent, never retry
            if attempt == max_retries - 1:
                raise
            logger.warning("OpenRouter API error (attempt %d): %s", attempt + 1, e)
            time.sleep(2**attempt)
        except openai.APIError as e:
            if attempt == max_retries - 1:
                raise
            logger.warning("OpenRouter API error (attempt %d): %s", attempt + 1, e)
            time.sleep(2**attempt)


# Human-readable status for each tool, shown live in the UI while the tool loop runs
# (see server.py's _run_with_progress) so the user sees what Edith is doing, not just a
# spinner. Falls back to a humanized version of the tool name for anything not listed here.
TOOL_STATUS = {
    "web_search": "Searching the web",
    "semantic_search": "Searching memory",
    "search_history": "Searching past conversations",
    "save_fact": "Saving a note",
    "update_fact": "Updating a note",
    "forget_fact": "Forgetting a note",
    "recall_fact": "Looking up a note",
    "gmail_search": "Searching Gmail",
    "gmail_read": "Reading an email",
    "drive_search": "Searching Drive",
    "drive_read_file": "Reading a Drive file",
    "create_drive_file": "Saving a Drive file",
    "calendar_list_events": "Checking your calendar",
    "create_calendar_event": "Adding a calendar event",
    "docs_read": "Reading a Doc",
    "sheets_read": "Reading a Sheet",
    "send_email": "Sending an email",
    "whatsapp_list_chats": "Checking WhatsApp",
    "whatsapp_read_chat": "Reading a WhatsApp chat",
    "send_whatsapp_message": "Sending a WhatsApp message",
    "get_health_summary": "Checking your health data",
    "browse_url": "Browsing the web",
    "fill_form": "Filling out a form",
}


def _tool_status(name: str) -> str:
    return TOOL_STATUS.get(name, name.replace("_", " ").capitalize())


def _execute_tool_call(
    tool_call,
    dispatch: ToolDispatch,
    recorder: Optional[Recorder] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    name = tool_call.function.name
    reply = {"role": "tool", "tool_call_id": tool_call.id, "name": name}
    t0 = time.monotonic()
    try:
        args = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError as e:
        reply["content"] = f"ERROR: malformed tool arguments: {e}"
        if recorder:
            recorder.record_tool_span(name, {}, reply["content"], (time.monotonic() - t0) * 1000, status="error", error=str(e))
        return reply

    try:
        result = dispatch(name, args, on_progress)
        reply["content"] = result if isinstance(result, str) else json.dumps(result)
        status, error = "ok", None
        if isinstance(reply["content"], str) and reply["content"].startswith("ERROR"):
            status, error = "error", reply["content"]
    except Exception as e:  # noqa: BLE001 — tool errors must degrade, never crash the loop
        logger.exception("Tool '%s' raised", name)
        reply["content"] = f"ERROR executing tool '{name}': {e}"
        status, error = "error", str(e)
    if recorder:
        recorder.record_tool_span(name, args, reply["content"], (time.monotonic() - t0) * 1000, status=status, error=error)
    return reply


def _record_llm_span(recorder: Optional[Recorder], model: str, resp, duration_ms: float, output_preview: Optional[str]) -> None:
    if not recorder:
        return
    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    recorder.record_llm_span(model, prompt_tokens, completion_tokens, output_preview, duration_ms)


def run_completion_with_tools(
    client: openai.OpenAI,
    messages: list[dict],
    tools: Optional[list[dict]],
    model: str,
    dispatch: ToolDispatch,
    on_progress: Optional[Callable[[str], None]] = None,
    recorder: Optional[Recorder] = None,
) -> tuple[str, list[dict]]:
    """Runs the call -> execute-tools -> resubmit loop.

    Returns (final_text, new_messages) where new_messages is everything
    generated during this call (assistant + tool messages), for the caller
    to persist. on_progress, if given, is called with a human-readable status
    string right before each tool call executes (e.g. "Searching the web") —
    lets a caller (server.py) surface live "what is Edith doing" status to
    the UI without this module knowing anything about how it's displayed.
    recorder, if given, records one span per LLM call and per tool call (see
    edith/observability/tracing.py) — optional so existing callers/tests that
    don't care about tracing are unaffected.
    """
    working = list(messages)
    new_messages: list[dict] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        t0 = time.monotonic()
        resp = call_openrouter_chat(client, working, tools, model)
        msg = resp.choices[0].message
        _record_llm_span(recorder, model, resp, (time.monotonic() - t0) * 1000, msg.content)

        tool_calls = msg.tool_calls or None
        # content=None is valid per the OpenAI spec for a tool-calls-only assistant
        # message, but Alibaba's DashScope backend (Qwen models via OpenRouter) 400s
        # with "The content field is a required field" on null content — coerce to
        # "" instead, which every provider accepts. See _row_to_openai_message in
        # edith/memory/store.py for the matching fix on the history-replay side
        # (old rows already persisted with NULL content hit the same 400 otherwise).
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if tool_calls:
            tc_dicts = []
            for tc in tool_calls:
                tc_dict: dict[str, Any] = {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                # Gemini attaches a thought_signature here and requires it echoed
                # back on resubmission for multi-turn tool use — omitting it 400s
                # with "Function call is missing a thought_signature". Not a
                # standard OpenAI field, so this is a no-op for OpenRouter/OpenAI,
                # which never populate it.
                extra_content = getattr(tc, "extra_content", None)
                if extra_content:
                    tc_dict["extra_content"] = extra_content
                tc_dicts.append(tc_dict)
            assistant_msg["tool_calls"] = tc_dicts
        working.append(assistant_msg)
        new_messages.append(assistant_msg)

        if not tool_calls:
            # A thinking-capable model (Gemini 3.5 Flash) can burn its whole
            # max_tokens budget on internal reasoning and never emit visible
            # content — msg.content is then None despite a real, non-trivial
            # completion_tokens count. Silently returning "" used to reach the
            # user as a blank chat bubble with no indication anything went
            # wrong; surface it instead so it's at least actionable.
            return msg.content or EMPTY_RESPONSE_FALLBACK, new_messages

        for tc in tool_calls:
            if on_progress:
                on_progress(_tool_status(tc.function.name))
            reply = _execute_tool_call(tc, dispatch, recorder, on_progress)
            working.append(reply)
            new_messages.append(reply)
        # loop resubmits with tool replies appended

    # iteration cap hit: force a plain-text answer, tools disabled
    working.append(
        {
            "role": "user",
            "content": "(system: tool-call limit reached — answer now with what you have, no more tool calls)",
        }
    )
    t0 = time.monotonic()
    resp = call_openrouter_chat(client, working, tools=None, model=model)
    final = resp.choices[0].message.content or EMPTY_RESPONSE_FALLBACK
    _record_llm_span(recorder, model, resp, (time.monotonic() - t0) * 1000, final)
    final_msg = {"role": "assistant", "content": final}
    new_messages.append(final_msg)
    return final, new_messages
