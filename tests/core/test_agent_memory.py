from edith.agent import _called, _touched_records


def _call(name, arguments):
    return {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def test_turn_with_explicit_remember_is_detected():
    msgs = [_call("remember", '{"content": "likes tea"}'), {"role": "tool", "content": "ok"}]
    assert _called(msgs, "remember")
    assert not _called([_call("web_search", "{}")], "remember")


def test_touched_records_from_tool_args():
    msgs = [
        _call("update_todo_status", '{"todo_id": 4, "status": "done"}'),
        _call("create_todo", '{"title": "x", "goal_id": 0}'),
        _call("add_milestone", '{"goal_id": 2, "title": "y"}'),
        _call("broken", "not json"),
    ]
    assert _touched_records(msgs) == [("todo", 4), ("goal", 2)]
