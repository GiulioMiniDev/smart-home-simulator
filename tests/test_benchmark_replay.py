from __future__ import annotations

import json
from pathlib import Path

from smart_home_sim.application.replay import _sensor_state_at
from smart_home_sim.domain.execution import ExecutionTrace
from smart_home_sim.domain.sensors import ObservableSensorLog, OracleMapping
from tools.benchmark_replay import WEEKLY_SOURCE, _expanded_fixture


def test_expanded_fixture_retains_each_family_and_remaps_causality(tmp_path: Path) -> None:
    target = tmp_path / "year"
    _expanded_fixture(WEEKLY_SOURCE, target, periods=2)

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
        assert len(getattr(trace, field)) == 2 * len(source_trace[_camel(field)])
    assert len(observations.records) == 2 * len(
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


def _camel(field: str) -> str:
    head, *tail = field.split("_")
    return head + "".join(part.title() for part in tail)
