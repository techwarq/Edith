"""Tests for edith/temporal/schedules.py's own logic (idempotent create, not-found
handling, duplicate detection) against a fake in-memory Client — not real Temporal
Cloud. Full workflow execution semantics are Temporal SDK's own responsibility;
these tests cover the business logic edith actually adds on top."""

import asyncio

import pytest
from temporalio.service import RPCError, RPCStatusCode

from edith.config import JOB_SEARCH_SCHEDULE_ID, NIGHTLY_REFLECTION_SCHEDULE_ID
from edith.temporal import schedules


def not_found_error():
    return RPCError("not found", RPCStatusCode.NOT_FOUND, b"")


class FakeScheduleHandle:
    def __init__(self, client, schedule_id):
        self._client = client
        self.id = schedule_id

    async def describe(self):
        if self.id not in self._client.created_schedules:
            raise not_found_error()
        return self._client.created_schedules[self.id]

    async def delete(self):
        if self.id not in self._client.created_schedules:
            raise not_found_error()
        del self._client.created_schedules[self.id]


class FakeWorkflowHandle:
    def __init__(self, client, workflow_id):
        self._client = client
        self.id = workflow_id

    async def cancel(self, **kwargs):
        if self.id not in self._client.started_workflows:
            raise not_found_error()
        del self._client.started_workflows[self.id]


class FakeAsyncIterator:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class Item:
    def __init__(self, id_):
        self.id = id_


class FakeClient:
    def __init__(self):
        self.created_schedules: dict[str, object] = {}
        self.started_workflows: dict[str, object] = {}

    def get_schedule_handle(self, id):
        return FakeScheduleHandle(self, id)

    async def create_schedule(self, id, schedule, **kwargs):
        self.created_schedules[id] = schedule
        return FakeScheduleHandle(self, id)

    async def list_schedules(self, query=None, **kwargs):
        prefix = query.split("'")[1] if query else ""
        return FakeAsyncIterator([Item(i) for i in self.created_schedules if i.startswith(prefix)])

    def get_workflow_handle(self, id):
        return FakeWorkflowHandle(self, id)

    async def start_workflow(self, workflow, arg=None, *, id, args=None, **kwargs):
        self.started_workflows[id] = (arg if args is None else args, kwargs)
        return FakeWorkflowHandle(self, id)

    def list_workflows(self, query=None, **kwargs):
        # Real temporalio Client.list_workflows returns an async iterator directly
        # (not a coroutine) — plain def here, matching edith/temporal/schedules.py's
        # `async for wf in client.list_workflows(query)` (no await).
        prefix = query.split("'")[1] if query else ""
        return FakeAsyncIterator([Item(i) for i in self.started_workflows if i.startswith(prefix)])


def test_ensure_nightly_reflection_schedule_creates_once():
    client = FakeClient()
    asyncio.run(schedules.ensure_nightly_reflection_schedule(client))
    assert NIGHTLY_REFLECTION_SCHEDULE_ID in client.created_schedules

    # second call is a no-op (idempotent) — schedule object identity unchanged
    existing = client.created_schedules[NIGHTLY_REFLECTION_SCHEDULE_ID]
    asyncio.run(schedules.ensure_nightly_reflection_schedule(client))
    assert client.created_schedules[NIGHTLY_REFLECTION_SCHEDULE_ID] is existing


def test_cancel_nightly_reflection_when_not_enabled():
    client = FakeClient()
    assert asyncio.run(schedules.cancel_nightly_reflection(client)) is False


def test_enable_then_disable_nightly_reflection():
    client = FakeClient()
    asyncio.run(schedules.ensure_nightly_reflection_schedule(client))
    assert NIGHTLY_REFLECTION_SCHEDULE_ID in client.created_schedules

    assert asyncio.run(schedules.cancel_nightly_reflection(client)) is True
    assert NIGHTLY_REFLECTION_SCHEDULE_ID not in client.created_schedules
    # disabling again is a no-op, not an error
    assert asyncio.run(schedules.cancel_nightly_reflection(client)) is False


def test_create_job_schedule_rejects_duplicate():
    client = FakeClient()
    asyncio.run(schedules.create_job_schedule(client, "my_job", "do the thing", "0 9 * * *"))
    with pytest.raises(ValueError, match="my_job"):
        asyncio.run(schedules.create_job_schedule(client, "my_job", "do it again", "0 9 * * *"))


def test_cancel_job_schedule():
    client = FakeClient()
    asyncio.run(schedules.create_job_schedule(client, "my_job", "do the thing", "0 9 * * *"))
    assert asyncio.run(schedules.cancel_job_schedule(client, "my_job")) is True
    assert asyncio.run(schedules.cancel_job_schedule(client, "my_job")) is False


def test_list_job_schedules():
    client = FakeClient()
    asyncio.run(schedules.create_job_schedule(client, "job_a", "a", "0 9 * * *"))
    asyncio.run(schedules.create_job_schedule(client, "job_b", "b", "0 10 * * *"))

    job_ids = {j["job_id"] for j in asyncio.run(schedules.list_job_schedules(client))}
    assert job_ids == {"job_a", "job_b"}


def test_start_once_and_cancel_once():
    client = FakeClient()
    asyncio.run(schedules.start_once(client, "reminder", "ping me", 5))
    assert asyncio.run(schedules.cancel_once(client, "reminder")) is True
    assert asyncio.run(schedules.cancel_once(client, "reminder")) is False


def test_list_once_jobs():
    client = FakeClient()
    asyncio.run(schedules.start_once(client, "reminder", "ping me", 5))
    job_ids = {j["job_id"] for j in asyncio.run(schedules.list_once_jobs(client))}
    assert job_ids == {"reminder"}


def test_start_deep_research_passes_budget_and_sleep_hours():
    client = FakeClient()
    asyncio.run(schedules.start_deep_research(client, 1.0, 2.0))
    [(args, kwargs)] = client.started_workflows.values()
    assert args == [1.0, 2.0]
    assert kwargs["task_queue"]


def test_start_deep_research_ids_are_unique_per_call():
    client = FakeClient()
    asyncio.run(schedules.start_deep_research(client, 1.0, 2.0))
    asyncio.run(schedules.start_deep_research(client, 1.0, 2.0))
    assert len(client.started_workflows) == 2
    assert all(i.startswith(schedules.DEEP_RESEARCH_WORKFLOW_PREFIX) for i in client.started_workflows)


def test_ensure_job_search_schedule_creates_once():
    client = FakeClient()
    asyncio.run(schedules.ensure_job_search_schedule(client, "30 4-13 * * 1-5", 3))
    assert JOB_SEARCH_SCHEDULE_ID in client.created_schedules

    existing = client.created_schedules[JOB_SEARCH_SCHEDULE_ID]
    asyncio.run(schedules.ensure_job_search_schedule(client, "30 4-13 * * 1-5", 3))
    assert client.created_schedules[JOB_SEARCH_SCHEDULE_ID] is existing


def test_cancel_job_search_schedule_when_not_enabled():
    client = FakeClient()
    assert asyncio.run(schedules.cancel_job_search_schedule(client)) is False


def test_enable_then_disable_job_search_schedule():
    client = FakeClient()
    asyncio.run(schedules.ensure_job_search_schedule(client, "30 4-13 * * 1-5", 3))
    assert JOB_SEARCH_SCHEDULE_ID in client.created_schedules

    assert asyncio.run(schedules.cancel_job_search_schedule(client)) is True
    assert JOB_SEARCH_SCHEDULE_ID not in client.created_schedules
    assert asyncio.run(schedules.cancel_job_search_schedule(client)) is False
