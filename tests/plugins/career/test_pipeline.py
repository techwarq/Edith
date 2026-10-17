import pytest

from edith.config import JOB_SEARCH_SCHEDULE_ID
from edith.plugins.career import pipeline
from edith.temporal.client import TemporalNotConfigured
from edith.tools.base import ToolContext
from edith.tools.registry import ToolRegistry


@pytest.fixture
def registry():
    r = ToolRegistry(ToolContext())
    r.register_module(pipeline)
    return r


async def _fake_get_client(settings):
    return "fake-client"


async def _raise_not_configured(settings):
    raise TemporalNotConfigured("Scheduling isn't set up")


def test_instruction_is_built_from_the_profile(example_career_profile):
    text = pipeline.job_search_instruction(3)
    assert "Alex Doe, Full-stack / AI Engineer" in text
    assert example_career_profile["jobs"]["target_roles"] in text


def test_enable_jobs_pipeline_schedules_profile_instruction(registry, monkeypatch):
    calls = []

    async def fake_ensure(client, schedule_id, instruction, cron):
        calls.append((client, schedule_id, instruction))

    monkeypatch.setattr(pipeline, "get_client", _fake_get_client)
    monkeypatch.setattr(pipeline.schedules, "ensure_instruction_schedule", fake_ensure)

    assert "Job-search pipeline enabled" in registry.dispatch("enable_jobs_pipeline", {})
    assert calls[0][:2] == ("fake-client", JOB_SEARCH_SCHEDULE_ID)
    assert "Alex Doe" in calls[0][2]


def test_enable_jobs_pipeline_needs_profile(registry, monkeypatch, tmp_path):
    monkeypatch.setenv("EDITH_CAREER_PROFILE", str(tmp_path / "missing.json"))
    assert registry.dispatch("enable_jobs_pipeline", {}).startswith("ERROR: The career plugin needs your profile")


def test_enable_jobs_pipeline_not_configured(registry, monkeypatch):
    monkeypatch.setattr(pipeline, "get_client", _raise_not_configured)
    assert registry.dispatch("enable_jobs_pipeline", {}).startswith("ERROR:")


@pytest.mark.parametrize("existed,expected", [(True, "Job-search pipeline disabled."), (False, "Job-search pipeline wasn't enabled.")])
def test_disable_jobs_pipeline(registry, monkeypatch, existed, expected):
    async def fake_cancel(client, schedule_id):
        assert schedule_id == JOB_SEARCH_SCHEDULE_ID
        return existed

    monkeypatch.setattr(pipeline, "get_client", _fake_get_client)
    monkeypatch.setattr(pipeline.schedules, "cancel_schedule", fake_cancel)
    assert registry.dispatch("disable_jobs_pipeline", {}) == expected
