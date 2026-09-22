from types import SimpleNamespace

import httpx
import openai

from edith.llm import client as llm_client
from edith.tools.registry import ToolRegistry


def make_bad_request_error(message: str) -> openai.BadRequestError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(400, request=request, json={"error": {"message": message}})
    return openai.BadRequestError(message, response=response, body={"error": {"message": message}})


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def make_response(content=None, tool_calls=None):
    tc_objs = None
    if tool_calls:
        tc_objs = [
            SimpleNamespace(
                id=tc["id"],
                function=SimpleNamespace(name=tc["name"], arguments=tc["arguments"]),
                extra_content=tc.get("extra_content"),
            )
            for tc in tool_calls
        ]
    message = SimpleNamespace(content=content, tool_calls=tc_objs)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_run_completion_no_tool_calls():
    client = FakeClient([make_response(content="Hello!")])
    registry = ToolRegistry()
    text, new_msgs = llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )
    assert text == "Hello!"
    assert new_msgs == [{"role": "assistant", "content": "Hello!"}]


def test_tool_reply_name_field_stripped_before_sending_to_api():
    # Some OpenRouter-routed providers (e.g. Qwen via DashScope) 400 on a
    # "name" field on role="tool" messages, which isn't in the official
    # OpenAI schema. It must never reach client.chat.completions.create.
    registry = ToolRegistry()
    registry.register({"type": "function", "function": {"name": "echo", "parameters": {}}}, lambda **kw: "echoed")
    responses = [
        make_response(tool_calls=[{"id": "call_1", "name": "echo", "arguments": "{}"}]),
        make_response(content="done"),
    ]
    client = FakeClient(responses)
    llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )
    second_call_messages = client.chat.completions.calls[1]["messages"]
    tool_messages = [m for m in second_call_messages if m["role"] == "tool"]
    assert tool_messages and all("name" not in m for m in tool_messages)


def test_run_completion_with_successful_tool_call():
    registry = ToolRegistry()
    registry.register(
        {"type": "function", "function": {"name": "echo", "parameters": {"type": "object", "properties": {}}}},
        lambda **kw: "echoed",
    )
    responses = [
        make_response(tool_calls=[{"id": "call_1", "name": "echo", "arguments": "{}"}]),
        make_response(content="done"),
    ]
    client = FakeClient(responses)
    text, new_msgs = llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )
    assert text == "done"
    tool_msgs = [m for m in new_msgs if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "echoed"


def test_malformed_tool_arguments_does_not_crash():
    registry = ToolRegistry()
    registry.register(
        {"type": "function", "function": {"name": "echo", "parameters": {}}},
        lambda **kw: "echoed",
    )
    responses = [
        make_response(tool_calls=[{"id": "call_1", "name": "echo", "arguments": "{not valid json"}]),
        make_response(content="recovered"),
    ]
    client = FakeClient(responses)
    text, new_msgs = llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )
    assert text == "recovered"
    tool_msgs = [m for m in new_msgs if m["role"] == "tool"]
    assert "ERROR" in tool_msgs[0]["content"]


def test_unknown_tool_does_not_crash():
    registry = ToolRegistry()
    responses = [
        make_response(tool_calls=[{"id": "call_1", "name": "nonexistent", "arguments": "{}"}]),
        make_response(content="ok"),
    ]
    client = FakeClient(responses)
    text, new_msgs = llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )
    assert text == "ok"
    tool_msgs = [m for m in new_msgs if m["role"] == "tool"]
    assert "unknown tool" in tool_msgs[0]["content"]


def test_tool_exception_does_not_crash():
    registry = ToolRegistry()

    def boom(**kw):
        raise ValueError("kaboom")

    registry.register({"type": "function", "function": {"name": "boom", "parameters": {}}}, boom)
    responses = [
        make_response(tool_calls=[{"id": "call_1", "name": "boom", "arguments": "{}"}]),
        make_response(content="recovered"),
    ]
    client = FakeClient(responses)
    text, new_msgs = llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )
    assert text == "recovered"
    tool_msgs = [m for m in new_msgs if m["role"] == "tool"]
    assert "kaboom" in tool_msgs[0]["content"]


def test_iteration_cap_forces_final_answer(monkeypatch):
    monkeypatch.setattr(llm_client, "MAX_TOOL_ITERATIONS", 2)
    registry = ToolRegistry()
    registry.register({"type": "function", "function": {"name": "loop_tool", "parameters": {}}}, lambda **kw: "again")

    responses = [
        make_response(tool_calls=[{"id": "call_1", "name": "loop_tool", "arguments": "{}"}]),
        make_response(tool_calls=[{"id": "call_2", "name": "loop_tool", "arguments": "{}"}]),
        make_response(content="forced final"),
    ]
    client = FakeClient(responses)
    text, new_msgs = llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )
    assert text == "forced final"
    # the final call must have been made without tools
    last_call = client.chat.completions.calls[-1]
    assert "tools" not in last_call or last_call["tools"] is None


def test_non_context_length_400_is_retried_and_can_succeed():
    # Confirmed live: a qwen3-coder-next request 400'd across multiple OpenRouter
    # providers with "Extra data" / "Can only get item pairs from a mapping" style
    # JSON errors — the model generating malformed tool-call JSON upstream, not a
    # structurally bad request from us. The identical request succeeded on retry.
    responses = [
        make_bad_request_error("Extra data: line 1 column 84 (char 83)"),
        make_response(content="worked on retry"),
    ]
    client = FakeClient(responses)
    registry = ToolRegistry()

    text, new_msgs = llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )

    assert text == "worked on retry"
    assert len(client.chat.completions.calls) == 2


def test_context_length_400_is_not_retried_by_call_openrouter_chat():
    # Context-length errors are the one 400 variant NOT retried here — the
    # caller (agent.py) handles it by trimming history and retrying itself.
    responses = [make_bad_request_error("This model's maximum context length is 8192 tokens.")]
    client = FakeClient(responses)

    try:
        llm_client.call_openrouter_chat(client, [{"role": "user", "content": "hi"}], None, "test-model")
        assert False, "expected ContextLengthExceeded"
    except llm_client.ContextLengthExceeded:
        pass

    assert len(client.chat.completions.calls) == 1  # no retry — raised immediately


def test_gemini_thought_signature_preserved_across_tool_loop_iterations():
    # Gemini requires its thought_signature echoed back on resubmission for
    # multi-turn tool use, or the next call 400s with "Function call is
    # missing a thought_signature" — confirmed live against the real API.
    registry = ToolRegistry()
    registry.register({"type": "function", "function": {"name": "save_fact", "parameters": {}}}, lambda **kw: "saved")

    signature_blob = {"google": {"thought_signature": "opaque-signature-value"}}
    responses = [
        make_response(
            tool_calls=[{"id": "call_1", "name": "save_fact", "arguments": "{}", "extra_content": signature_blob}]
        ),
        make_response(content="done"),
    ]
    client = FakeClient(responses)

    llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )

    # The second call's resubmitted history must include the assistant message
    # with the tool_call's extra_content intact, or Gemini rejects the request.
    second_call_messages = client.chat.completions.calls[1]["messages"]
    assistant_msg = next(m for m in second_call_messages if m["role"] == "assistant" and m.get("tool_calls"))
    assert assistant_msg["tool_calls"][0]["extra_content"] == signature_blob


def test_non_gemini_tool_calls_have_no_extra_content_field():
    # OpenRouter/OpenAI tool calls never populate extra_content — confirm we
    # don't add a spurious empty field for them.
    registry = ToolRegistry()
    registry.register({"type": "function", "function": {"name": "save_fact", "parameters": {}}}, lambda **kw: "saved")

    responses = [
        make_response(tool_calls=[{"id": "call_1", "name": "save_fact", "arguments": "{}"}]),
        make_response(content="done"),
    ]
    client = FakeClient(responses)

    llm_client.run_completion_with_tools(
        client, [{"role": "user", "content": "hi"}], registry.schemas(), "test-model", registry.dispatch
    )

    second_call_messages = client.chat.completions.calls[1]["messages"]
    assistant_msg = next(m for m in second_call_messages if m["role"] == "assistant" and m.get("tool_calls"))
    assert "extra_content" not in assistant_msg["tool_calls"][0]

