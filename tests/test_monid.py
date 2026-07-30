"""Tests for edith/tools/monid.py — in particular the truncation-flagging
fix (see the comment above _TRUNCATION_WARNING): live testing found Edith
inventing a specific NVIDIA valuation number that wasn't in the actual tool
output, because the provider had truncated the source article server-side
and nothing told her that. These tests pin the fix: any tool result
containing a truncation marker gets an explicit warning appended so the
model can't mistake a cut-off result for a complete one.
"""

from types import SimpleNamespace

from edith.tools import monid
from edith.tools.registry import ToolRegistry


def _fake_run(monkeypatch, stdout="", stderr="", returncode=0):
    def _fake(*args, **kwargs):
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    monkeypatch.setattr(monid.subprocess, "run", _fake)


def test_run_monid_flags_provider_truncated_output(monkeypatch):
    _fake_run(monkeypatch, stdout='{"text": "some article that got cut off mid-sent…(truncated)"}')

    result = monid._run_monid(["run", "-p", "x", "-e", "y"])

    assert "…(truncated)" in result
    assert "SYSTEM NOTE" in result
    assert "do not infer" in result


def test_run_monid_does_not_flag_complete_output(monkeypatch):
    _fake_run(monkeypatch, stdout='{"text": "a complete result with nothing missing"}')

    result = monid._run_monid(["run", "-p", "x", "-e", "y"])

    assert "SYSTEM NOTE" not in result


def test_run_monid_error_path_has_no_truncation_noise(monkeypatch):
    _fake_run(monkeypatch, stdout='{"error": "HTTP 400"}', returncode=1)

    result = monid._run_monid(["run", "-p", "x", "-e", "y"])

    assert result.startswith("ERROR:")
    assert "SYSTEM NOTE" not in result


def test_run_monid_not_installed(monkeypatch):
    def _raise(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(monid.subprocess, "run", _raise)

    result = monid._run_monid(["balance"])

    assert result == "ERROR: the monid CLI is not installed on this machine."


def test_run_monid_timeout(monkeypatch):
    import subprocess as real_subprocess

    def _raise(*args, **kwargs):
        raise real_subprocess.TimeoutExpired(cmd="monid", timeout=45)

    monkeypatch.setattr(monid.subprocess, "run", _raise)

    result = monid._run_monid(["run", "-p", "x", "-e", "y"])

    assert result.startswith("ERROR:")
    assert "timed out" in result


def test_own_truncate_marker_also_triggers_warning(monkeypatch):
    huge = "x" * (monid._OUTPUT_CHARS + 1)
    _fake_run(monkeypatch, stdout=huge)

    result = monid._run_monid(["run", "-p", "x", "-e", "y"])

    assert result.count("…(truncated)") == 1  # our own _truncate's marker
    assert "SYSTEM NOTE" in result


def test_monid_discover_formats_results(monkeypatch):
    import json

    _fake_run(
        monkeypatch,
        stdout=json.dumps(
            {
                "results": [
                    {"provider": "tikhub", "endpoint": "/x", "score": 0.9, "verified": True, "description": "Search tweets"},
                ]
            }
        ),
    )
    registry = ToolRegistry()
    monid.register(registry)

    result = registry.dispatch("monid_discover", {"query": "twitter posts", "limit": 5})

    assert "tikhub//x" in result
    assert "Search tweets" in result


def test_monid_run_caps_wait_seconds(monkeypatch):
    captured = {}

    def _fake(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="{}", stderr="", returncode=0)

    monkeypatch.setattr(monid.subprocess, "run", _fake)
    registry = ToolRegistry()
    monid.register(registry)

    registry.dispatch("monid_run", {"provider": "p", "endpoint": "e", "wait_seconds": 999})

    assert "-w" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("-w") + 1] == "60"  # clamped to the max
