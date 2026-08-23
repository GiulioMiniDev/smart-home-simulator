from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from smart_home_sim.application import replay as replay_module
from smart_home_sim.application.replay import ReplayService, _sensor_state_at
from smart_home_sim.domain.execution import ExecutionTrace
from smart_home_sim.domain.sensors import ObservableSensorLog, OracleMapping
from tools import benchmark_replay
from tools.benchmark_replay import WEEKLY_SOURCE, _benchmark_fixture, _completed_workspace


@pytest.mark.parametrize(
    ("periods", "duration_days"),
    [(2, 7), (8, 28), (104, 364)],
)
def test_benchmark_fixture_has_coherent_duration_runtime_coverage_and_causality(
    tmp_path: Path, periods: int, duration_days: int
) -> None:
    target = tmp_path / f"fixture-{duration_days}d"
    _benchmark_fixture(WEEKLY_SOURCE, target, periods=periods, duration_days=duration_days)

    source_trace = json.loads((WEEKLY_SOURCE / "execution-trace.json").read_text())
    trace = ExecutionTrace.model_validate_json((target / "execution-trace.json").read_text())
    observations = ObservableSensorLog.model_validate_json(
        (target / "observable-sensor-log.json").read_text()
    )
    oracle = OracleMapping.model_validate_json((target / "oracle-mapping.json").read_text())

    for field in (
        "activity_executions",
        "action_executions",
        "movements",
        "state_transitions",
        "resource_events",
        "runtime_events",
        "plan_deviations",
        "daily_summaries",
    ):
        source_count = len(source_trace[_camel(field)])
        if field == "runtime_events":
            source_count += 1  # Fixture-only coverage sentinel; source has no runtime events.
        assert len(getattr(trace, field)) == periods * source_count
        assert len(getattr(trace, field)) > 0
    assert trace.ended_at - trace.started_at == timedelta(days=duration_days)
    assert len(observations.records) == periods * len(
        json.loads((WEEKLY_SOURCE / "observable-sensor-log.json").read_text())["records"]
    )
    assert len(oracle.links) == len(observations.records)
    assert len({item.observation_id for item in observations.records}) == len(observations.records)
    assert len({item.activity_execution_id for item in trace.activity_executions}) == len(
        trace.activity_executions
    )
    assert {item.observation_id for item in oracle.links} == {
        item.observation_id for item in observations.records
    }
    action_ids = {item.action_execution_id for item in trace.action_executions}
    activity_ids = {item.activity_execution_id for item in trace.activity_executions}
    assert {item.action_execution_id for item in trace.movements} <= action_ids
    assert all(set(item.action_execution_ids) <= action_ids for item in oracle.links)
    assert all(set(item.activity_execution_ids) <= activity_ids for item in oracle.links)
    assert {item.event_id for item in trace.runtime_events} == {
        "benchmark_runtime_coverage_sentinel"
    }
    assert all(item.evaluated_at >= trace.started_at for item in trace.runtime_events)
    assert all(item.evaluated_at <= trace.ended_at for item in trace.runtime_events)
    workspace, run_id = _completed_workspace(
        target / "workspace", periods=periods, duration_days=duration_days, observable_only=True
    )
    daily_window = ReplayService(workspace).events(
        run_id,
        start=trace.started_at,
        end=trace.ended_at,
        kinds={"daily_summary"},
        limit=1,
    )
    assert daily_window.total == len(trace.daily_summaries) > 0
    assert len(daily_window.items) == 1
    assert daily_window.items[0].kind == "daily_summary"
    grouped: dict[str, list[object]] = {}
    for record in observations.records:
        grouped.setdefault(record.sensor_id, []).append(record)
    timelines = tuple(
        (sensor_id, tuple(item.observed_at for item in records), tuple(records))
        for sensor_id, records in sorted(grouped.items())
    )
    instant = observations.records[len(observations.records) // 2].observed_at
    assert _sensor_state_at(observations, oracle, instant, True) == _sensor_state_at(
        observations, oracle, instant, True, timelines
    )


def test_replay_frame_seek_applies_a_bounded_number_of_prior_deltas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late seek must use the index, never replay every earlier state transition."""
    workspace, run_id = _completed_workspace(
        tmp_path / "workspace", periods=8, duration_days=28, observable_only=True
    )
    replay = ReplayService(workspace)
    index = replay._index(run_id)
    calls = 0
    original = replay_module._apply_transition

    def counted(target: dict[str, object], transition: object) -> None:
        nonlocal calls
        calls += 1
        original(target, transition)  # type: ignore[arg-type]

    monkeypatch.setattr(replay_module, "_apply_transition", counted)

    replay.frame(run_id, at=index.trace_end - timedelta(microseconds=1))

    assert calls < 100


def test_benchmark_reports_nonzero_daily_summary_count_and_bounded_summary_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmark_replay, "FRAME_COUNT", 1)
    monkeypatch.setattr(benchmark_replay, "WINDOW_COUNT", 1)
    workspace, run_id = _completed_workspace(
        tmp_path / "workspace", periods=2, duration_days=7, observable_only=True
    )

    result = benchmark_replay._measure("weekly", workspace, run_id)

    assert result["dailySummaries"] > 0
    assert result["dailySummaryWindowTotal"] == result["dailySummaries"]
    assert 0 < result["dailySummaryWindowItems"] <= benchmark_replay.WINDOW_LIMIT


def _camel(field: str) -> str:
    head, *tail = field.split("_")
    return head + "".join(part.title() for part in tail)
