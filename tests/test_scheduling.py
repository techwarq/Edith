"""Tests for edith/tools/scheduling.py. Doesn't touch a real Temporal Cloud —
get_client and edith.temporal.schedules' async functions are monkeypatched with
fakes, since the tool functions are plain sync wrappers (asyncio.run) around them."""

import pytest

from edith.temporal.client import TemporalNotConfigured
from edith.tools import scheduling
from edith.tools.registry import ToolRegistry


class FakeSettings:
    nightly_reflection_cron = "0 3 * * *"


@pytest.fixture
def registry():
    r = ToolRegistry()
    scheduling.register(r, FakeSettings())
    return r


async def _fake_get_client(settings):
    return "fake-client"


async def _raise_not_configured(settings):
    raise TemporalNotConfigured("Temporal Cloud isn't configured")


def test_schedule_job_success(registry, monkeypatch):
    calls = []

    async def fake_create(client, job_id, instruction, cron, end_at=None):
        calls.append((client, job_id, instruction, cron, end_at))

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "create_job_schedule", fake_create)

    result = registry.dispatch("schedule_job", {"job_id": "daily_check", "instruction": "check things", "cron": "0 9 * * *"})
    assert "Scheduled recurring job 'daily_check'" in result
    assert calls == [("fake-client", "daily_check", "check things", "0 9 * * *", None)]


def test_schedule_job_with_end_date(registry, monkeypatch):
    calls = []

    async def fake_create(client, job_id, instruction, cron, end_at=None):
        calls.append(end_at)

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "create_job_schedule", fake_create)

    result = registry.dispatch(
        "schedule_job",
        {"job_id": "week_plan", "instruction": "check things", "cron": "0 9 * * *", "end_date": "2026-07-29"},
    )
    assert "ending after 2026-07-29" in result
    assert calls[0] is not None
    assert calls[0].year == 2026 and calls[0].month == 7 and calls[0].day == 29


def test_schedule_job_bad_end_date(registry, monkeypatch):
    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    result = registry.dispatch(
        "schedule_job",
        {"job_id": "week_plan", "instruction": "check things", "cron": "0 9 * * *", "end_date": "not-a-date"},
    )
    assert result.startswith("ERROR:")


def test_schedule_job_not_configured(registry, monkeypatch):
    monkeypatch.setattr(scheduling, "get_client", _raise_not_configured)
    result = registry.dispatch("schedule_job", {"job_id": "x", "instruction": "y", "cron": "* * * * *"})
    assert result.startswith("ERROR:")


def test_schedule_job_duplicate(registry, monkeypatch):
    async def fake_create(client, job_id, instruction, cron, end_at=None):
        raise ValueError(f"A job named '{job_id}' already exists")

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "create_job_schedule", fake_create)

    result = registry.dispatch("schedule_job", {"job_id": "dup", "instruction": "y", "cron": "* * * * *"})
    assert "ERROR:" in result and "dup" in result


def test_schedule_once_success(registry, monkeypatch):
    calls = []

    async def fake_start_once(client, job_id, instruction, run_in_minutes):
        calls.append((job_id, instruction, run_in_minutes))

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "start_once", fake_start_once)

    result = registry.dispatch("schedule_once", {"job_id": "reminder", "instruction": "ping me", "run_in_minutes": 120})
    assert "once in 120 minute(s)" in result
    assert calls == [("reminder", "ping me", 120)]


def test_cancel_job_found_as_recurring(registry, monkeypatch):
    async def fake_cancel_schedule(client, job_id):
        return True

    async def fake_cancel_once(client, job_id):
        raise AssertionError("should not fall through to cancel_once")

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "cancel_job_schedule", fake_cancel_schedule)
    monkeypatch.setattr(scheduling.schedules, "cancel_once", fake_cancel_once)

    result = registry.dispatch("cancel_job", {"job_id": "daily_check"})
    assert result == "Cancelled 'daily_check'."


def test_cancel_job_falls_through_to_once(registry, monkeypatch):
    async def fake_cancel_schedule(client, job_id):
        return False

    async def fake_cancel_once(client, job_id):
        return True

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "cancel_job_schedule", fake_cancel_schedule)
    monkeypatch.setattr(scheduling.schedules, "cancel_once", fake_cancel_once)

    result = registry.dispatch("cancel_job", {"job_id": "reminder"})
    assert result == "Cancelled 'reminder'."


def test_cancel_job_not_found(registry, monkeypatch):
    async def fake_false(client, job_id):
        return False

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "cancel_job_schedule", fake_false)
    monkeypatch.setattr(scheduling.schedules, "cancel_once", fake_false)

    result = registry.dispatch("cancel_job", {"job_id": "ghost"})
    assert "No job named 'ghost'" in result


def test_list_jobs_empty(registry, monkeypatch):
    async def fake_empty(client):
        return []

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "list_job_schedules", fake_empty)
    monkeypatch.setattr(scheduling.schedules, "list_once_jobs", fake_empty)

    assert registry.dispatch("list_jobs", {}) == "No scheduled jobs."


def test_list_jobs_merges_recurring_and_once(registry, monkeypatch):
    async def fake_recurring(client):
        return [{"job_id": "daily_check"}]

    async def fake_once(client):
        return [{"job_id": "reminder"}]

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "list_job_schedules", fake_recurring)
    monkeypatch.setattr(scheduling.schedules, "list_once_jobs", fake_once)

    result = registry.dispatch("list_jobs", {})
    assert "(recurring) daily_check" in result
    assert "(one-off, pending) reminder" in result


def test_enable_nightly_reflection_success(registry, monkeypatch):
    calls = []

    async def fake_ensure(client):
        calls.append(client)

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "ensure_nightly_reflection_schedule", fake_ensure)

    result = registry.dispatch("enable_nightly_reflection", {})
    assert "Nightly reflection enabled" in result
    assert "0 3 * * *" in result
    assert calls == ["fake-client"]


def test_enable_nightly_reflection_not_configured(registry, monkeypatch):
    monkeypatch.setattr(scheduling, "get_client", _raise_not_configured)
    result = registry.dispatch("enable_nightly_reflection", {})
    assert result.startswith("ERROR:")


def test_disable_nightly_reflection_found(registry, monkeypatch):
    async def fake_cancel(client):
        return True

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "cancel_nightly_reflection", fake_cancel)

    assert registry.dispatch("disable_nightly_reflection", {}) == "Nightly reflection disabled."


def test_disable_nightly_reflection_not_enabled(registry, monkeypatch):
    async def fake_cancel(client):
        return False

    monkeypatch.setattr(scheduling, "get_client", _fake_get_client)
    monkeypatch.setattr(scheduling.schedules, "cancel_nightly_reflection", fake_cancel)

    assert registry.dispatch("disable_nightly_reflection", {}) == "Nightly reflection wasn't enabled."
