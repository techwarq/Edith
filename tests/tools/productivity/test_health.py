from datetime import datetime, timedelta, timezone

import pytest

from edith.memory.records import planning
from edith.memory.storage import sqlite


@pytest.fixture
def conn(tmp_path):
    c = sqlite.connect(tmp_path / "test.db")
    yield c
    c.close()


def _today(offset_days: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=offset_days)).strftime("%Y-%m-%d")


def test_store_metrics_writes_rows(conn):
    written = planning.store_metrics(
        conn,
        [
            {"type": "steps", "date": _today(), "value": 8500, "unit": "count"},
            {"type": "weight", "date": _today(), "value": 90.2, "unit": "kg"},
        ],
    )
    assert written == 2
    assert planning.latest_metric(conn, "weight") == {
        "type": "weight", "date": _today(), "value": 90.2, "unit": "kg"
    }


def test_store_metrics_upserts_on_type_and_date(conn):
    planning.store_metrics(conn, [{"type": "steps", "date": _today(), "value": 5000, "unit": "count"}])
    planning.store_metrics(conn, [{"type": "steps", "date": _today(), "value": 9000, "unit": "count"}])

    recent = planning.get_recent_metrics(conn, "steps", days=1)
    assert len(recent) == 1  # overwritten, not duplicated
    assert recent[0]["value"] == 9000


def test_store_metrics_skips_unrecognized_type(conn):
    written = planning.store_metrics(conn, [{"type": "sleep", "date": _today(), "value": 420, "unit": "minutes"}])
    assert written == 0
    assert planning.latest_metric(conn, "sleep") is None


def test_get_recent_metrics_excludes_old_data(conn):
    planning.store_metrics(
        conn,
        [
            {"type": "steps", "date": _today(), "value": 8000, "unit": "count"},
            {"type": "steps", "date": _today(60), "value": 2000, "unit": "count"},
        ],
    )
    recent = planning.get_recent_metrics(conn, "steps", days=7)
    assert len(recent) == 1
    assert recent[0]["value"] == 8000


def test_latest_metric_returns_none_when_absent(conn):
    assert planning.latest_metric(conn, "weight") is None


def test_summarize_empty_reports_nothing_synced(conn):
    summary = planning.summarize_health(conn)
    assert "No health data has been synced yet" in summary
    assert "/health login" in summary


def test_summarize_includes_weight_and_step_average(conn):
    planning.store_metrics(
        conn,
        [
            {"type": "weight", "date": _today(), "value": 90.0, "unit": "kg"},
            {"type": "steps", "date": _today(1), "value": 8000, "unit": "count"},
            {"type": "steps", "date": _today(), "value": 10000, "unit": "count"},
        ],
    )
    summary = planning.summarize_health(conn)
    assert "90.0 kg" in summary
    assert "9000" in summary  # average of 8000/10000


def test_summarize_includes_workout_count(conn):
    planning.store_metrics(
        conn,
        [
            {"type": "workouts", "date": _today(), "value": 45, "unit": "minutes"},
            {"type": "workouts", "date": _today(2), "value": 30, "unit": "minutes"},
        ],
    )
    summary = planning.summarize_health(conn)
    assert "Workouts logged in the last 7 days: 2" in summary
