from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
import simpy
from pydantic import ValidationError
from typer.testing import CliRunner

from smart_home_sim.cli import app
from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.domain.execution import (
    ActionExecution,
    ActivityExecution,
    MovementExecution,
)
from smart_home_sim.domain.models import ConditionOperator
from smart_home_sim.simulation.service import (
    NamedRandomStreams,
    ResourceCoordinator,
    SimulationEngine,
    _initial_runtime,
    _known_scenario_fact,
    _operator_matches,
    replay_files,
    simulate_bundle,
    simulate_file,
    validate_execution_trace,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json"
LEGACY_BUNDLE_PATH = ROOT / "examples/bundles/mario_week.simulation-bundle.json"
ACTION_CATALOG_PATH = ROOT / "src/smart_home_sim/catalogs/action-catalog-1.1.0.json"


@pytest.fixture(scope="module")
def bundle() -> SimulationBundle:
    return SimulationBundle.model_validate_json(BUNDLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result(bundle: SimulationBundle):
    return simulate_bundle(bundle)


def test_golden_week_executes_complete_vocabulary_and_closes_state(result) -> None:
    assert result.report.success
    assert result.trace is not None
    trace = result.trace
    assert result.report.semantic_digest == trace.semantic_digest
    assert result.report.summary.failed_activity_count == 0
    assert len(trace.activity_executions) == 172
    assert len(trace.action_executions) == 769
    assert len(trace.movements) == 202
    assert all(item.status != "failed" for item in trace.activity_executions)
    expected_actions = {
        item["actionType"]
        for item in json.loads(ACTION_CATALOG_PATH.read_text(encoding="utf-8"))["actions"]
    }
    assert {item.action_type for item in trace.action_executions} == expected_actions
    resident = trace.final_state.residents[0]
    assert resident.region_id == "bedroom"
    assert resident.facts["at_home"] is True
    assert not resident.held_resource_ids
    assert trace.final_state.resource_available_units == {
        "bed_01": 1,
        "fridge_01": 1,
        "kettle_01": 1,
        "kitchen_sink_01": 1,
        "shower_01": 1,
        "stove_01": 1,
        "television_01": 4,
        "toilet_01": 1,
        "washing_machine_01": 1,
    }


def test_golden_trace_is_deterministic_and_replays(bundle, result, tmp_path: Path) -> None:
    second = simulate_bundle(bundle)
    assert second.trace is not None and result.trace is not None
    assert second.trace.semantic_digest == result.trace.semantic_digest
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(result.trace.model_dump_json(by_alias=True), encoding="utf-8")
    replay = replay_files(BUNDLE_PATH, trace_path)
    assert replay.matches
    assert replay.actual_semantic_digest == replay.expected_semantic_digest


def test_legacy_bundle_fails_strict_runtime_precondition() -> None:
    result = simulate_file(LEGACY_BUNDLE_PATH)
    assert not result.report.success
    assert result.trace is None
    assert result.report.issues[0].code == "PRECONDITION_FAILED"
    assert "failed precondition" in result.report.issues[0].message


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"\xff", "FILE_ENCODING_ERROR"),
        (b'{"schemaVersion":"1.0.0",}', "JSON_SYNTAX"),
        (b'{"schemaVersion":"1.0.0","x":NaN}', "JSON_SYNTAX"),
        (b'{"schemaVersion":"1.0.0","x":1,"x":2}', "JSON_SYNTAX"),
        (b"[]", "STRUCTURE_INVALID"),
        (b'{"schemaVersion":"9.0.0"}', "UNSUPPORTED_SCHEMA_VERSION"),
        (b'{"schemaVersion":"1.0.0"}', "BUNDLE_INVALID"),
    ],
)
def test_simulation_file_failure_contract(tmp_path: Path, content: bytes, code: str) -> None:
    path = tmp_path / "input.json"
    path.write_bytes(content)
    result = simulate_file(path)
    assert result.trace is None
    assert not result.report.success
    assert result.report.issues[0].code == code


def test_simulation_file_io_limits(monkeypatch, tmp_path: Path) -> None:
    assert simulate_file(tmp_path / "missing.json").report.issues[0].code == "FILE_NOT_FOUND"
    assert simulate_file(tmp_path).report.issues[0].code == "FILE_READ_ERROR"
    path = tmp_path / "large.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("smart_home_sim.simulation.service.MAX_SCENARIO_BYTES", 0)
    assert simulate_file(path).report.issues[0].code == "FILE_TOO_LARGE"


def test_simulation_rejects_deep_json(tmp_path: Path) -> None:
    path = tmp_path / "deep.json"
    path.write_text("[" * 300 + "]" * 300, encoding="utf-8")
    assert simulate_file(path).report.issues[0].code == "JSON_NESTING_TOO_DEEP"


def test_replay_rejects_invalid_expected_trace(tmp_path: Path) -> None:
    path = tmp_path / "trace.json"
    path.write_text("{}", encoding="utf-8")
    report = replay_files(BUNDLE_PATH, path)
    assert not report.matches
    assert report.expected_semantic_digest == "0" * 64
    assert report.simulation_report.issues[0].code == "STRUCTURE_INVALID"


def test_named_streams_are_stable_and_independent() -> None:
    left = NamedRandomStreams(42)
    right = NamedRandomStreams(42)
    assert left.stream("a") is left.stream("a")
    assert left.stream("a").random() == right.stream("a").random()
    assert (
        NamedRandomStreams(42).stream("a").random() != NamedRandomStreams(42).stream("b").random()
    )


def test_resource_coordinator_preempts_and_resumes_atomically() -> None:
    env = simpy.Environment()
    coordinator = ResourceCoordinator(env, {"shared": 1})
    events: list[tuple[str, int]] = []

    def low_priority():
        allocation = yield coordinator.request(
            allocation_id="low",
            activity_id="low",
            actor_id="resident_low",
            priority=10,
            requirements={"shared": 1},
        )
        events.append(("low_acquired", int(env.now)))
        try:
            yield env.timeout(10)
        except simpy.Interrupt as interruption:
            assert interruption.cause["kind"] == "resource_preemption"
            events.append(("low_preempted", int(env.now)))
            allocation = yield coordinator.request(
                allocation_id="low",
                activity_id="low",
                actor_id="resident_low",
                priority=10,
                requirements={"shared": 1},
            )
            events.append(("low_reacquired", int(env.now)))
        coordinator.release(allocation)

    def high_priority():
        yield env.timeout(1)
        allocation = yield coordinator.request(
            allocation_id="high",
            activity_id="high",
            actor_id="resident_high",
            priority=90,
            requirements={"shared": 1},
        )
        events.append(("high_acquired", int(env.now)))
        yield env.timeout(2)
        coordinator.release(allocation)

    env.process(low_priority())
    env.process(high_priority())
    env.run()
    assert events == [
        ("low_acquired", 0),
        ("low_preempted", 1),
        ("high_acquired", 1),
        ("low_reacquired", 3),
    ]
    assert coordinator.available("shared") == 1
    with pytest.raises(RuntimeError):
        coordinator.request(
            allocation_id="invalid",
            activity_id="invalid",
            actor_id="invalid",
            priority=1,
            requirements={"shared": 1},
        )


def _resource_contention_bundle(bundle, high_priority_delay: timedelta):
    source_activity = bundle.canonical_plan.days[0].activities[0]
    low = source_activity.model_copy(update={"priority": 10, "sequence_index": 0})
    high_id = "test_high_priority_wake"
    high = source_activity.model_copy(
        update={
            "source_activity_id": high_id,
            "actor_id": "resident_priority",
            "priority": 100,
            "sequence_index": 1,
            "scheduled_start": source_activity.scheduled_start + high_priority_delay,
            "scheduled_end": source_activity.scheduled_end + high_priority_delay,
        }
    )
    plan_day = bundle.canonical_plan.days[0].model_copy(
        update={"activities": [low, high], "contingencies": [], "omitted_activities": []}
    )
    plan = bundle.canonical_plan.model_copy(update={"days": [plan_day]})
    resident = bundle.scenario.residents[0]
    second_resident = resident.model_copy(update={"resident_id": "resident_priority"})
    initial = bundle.scenario.initial_state.residents[0]
    second_initial = initial.model_copy(update={"resident_id": "resident_priority"})
    initial_state = bundle.scenario.initial_state.model_copy(
        update={"residents": [initial, second_initial]}
    )
    scenario = bundle.scenario.model_copy(
        update={
            "residents": [resident, second_resident],
            "initial_state": initial_state,
            "runtime_event_candidates": [],
        }
    )
    source_bindings = [
        item for item in bundle.action_bindings if item.source_activity_id == "d1_a01"
    ]
    high_bindings = [
        item.model_copy(update={"source_activity_id": high_id, "actor_id": "resident_priority"})
        for item in source_bindings
    ]
    kinetics = bundle.resident_kinematics[0]
    second_kinetics = kinetics.model_copy(update={"resident_id": "resident_priority"})
    return bundle.model_copy(
        update={
            "scenario": scenario,
            "canonical_plan": plan,
            "resident_kinematics": [kinetics, second_kinetics],
            "action_bindings": [*source_bindings, *high_bindings],
        }
    )


def test_engine_traces_resource_preemption_during_initial_acquisition(bundle) -> None:
    result = simulate_bundle(_resource_contention_bundle(bundle, timedelta()))
    assert result.report.success, result.report.issues
    assert result.trace is not None
    assert any(item.operation == "preempted" for item in result.trace.resource_events)
    low_execution = next(
        item for item in result.trace.activity_executions if item.source_activity_id == "d1_a01"
    )
    assert low_execution.status == "deviated"
    assert any(item.cause_id == "resource:bed_01" for item in result.trace.plan_deviations)


def test_engine_suspends_and_resumes_live_action_after_resource_preemption(bundle) -> None:
    result = simulate_bundle(_resource_contention_bundle(bundle, timedelta(minutes=1)))
    assert result.report.success, result.report.issues
    assert result.trace is not None
    low_execution = next(
        item for item in result.trace.activity_executions if item.source_activity_id == "d1_a01"
    )
    low_action = next(
        item
        for item in result.trace.action_executions
        if item.activity_execution_id == low_execution.activity_execution_id
    )
    operations = [
        item.operation
        for item in result.trace.resource_events
        if item.activity_execution_id == low_execution.activity_execution_id
    ]
    assert sorted(operations) == sorted(
        [
            "requested",
            "acquired",
            "preempted",
            "requested",
            "acquired",
            "released",
        ]
    )
    assert low_execution.status == "deviated"
    assert low_action.status == "completed"
    assert low_execution.actual_end - low_execution.actual_start == timedelta(minutes=10)
    assert low_action.ended_at - low_action.started_at == timedelta(minutes=7, seconds=30)


@pytest.mark.parametrize(
    ("operator", "present", "actual", "expected", "matches"),
    [
        (ConditionOperator.exists, True, None, None, True),
        (ConditionOperator.not_exists, False, None, None, True),
        (ConditionOperator.truthy, True, 1, None, True),
        (ConditionOperator.falsy, True, 0, None, True),
        (ConditionOperator.eq, True, "a", "a", True),
        (ConditionOperator.ne, True, "a", "b", True),
        (ConditionOperator.gt, True, 2, 1, True),
        (ConditionOperator.gte, True, 2, 2, True),
        (ConditionOperator.lt, True, 1, 2, True),
        (ConditionOperator.lte, True, 2, 2, True),
        (ConditionOperator.in_, True, "a", ["a"], True),
        (ConditionOperator.not_in, True, "b", ["a"], True),
        (ConditionOperator.eq, False, None, None, False),
    ],
)
def test_runtime_condition_operators(operator, present, actual, expected, matches) -> None:
    assert _operator_matches(operator, present, actual, expected) is matches


def test_runtime_fact_resolution_is_strict_and_source_aware(bundle) -> None:
    state = _initial_runtime(bundle)
    actor_id = bundle.scenario.residents[0].resident_id
    resident = state.residents[actor_id]
    resident.facts["medicationAvailableDoses"] = 2
    state.invalidated_facts.add("invalidated_fact")
    state.completed_activities.add("completed_activity")
    state.environment_facts["environment_fact"] = "present"

    assert _known_scenario_fact(state, actor_id, "invalidated_fact") == (True, False)
    assert _known_scenario_fact(state, actor_id, "medication_available") == (True, True)
    assert _known_scenario_fact(state, actor_id, "completed_activity_executed") == (True, True)
    assert _known_scenario_fact(state, actor_id, "day_fact", day_facts={"day_fact": "present"}) == (
        True,
        "present",
    )
    assert _known_scenario_fact(state, actor_id, "environment_fact") == (True, "present")
    assert _known_scenario_fact(state, actor_id, "unknown_fact") == (False, None)


def test_trace_invariant_validator_detects_reference_and_final_state_errors(bundle, result) -> None:
    assert result.trace is not None
    trace = result.trace
    bad_action = trace.action_executions[0].model_copy(update={"activity_execution_id": "missing"})
    bad_final = trace.final_state.model_copy(update={"resource_available_units": {}})
    bad_trace = trace.model_copy(
        update={
            "action_executions": [bad_action, *trace.action_executions[1:]],
            "final_state": bad_final,
        }
    )
    issues = validate_execution_trace(bad_trace, bundle)
    assert {item.code for item in issues} == {"TRACE_INVARIANT_FAILED"}
    assert any("unknown activity" in item.message for item in issues)
    assert any("capacity" in item.message for item in issues)
    assert any("digest" in item.message.lower() for item in issues)


def test_trace_invariant_validator_reports_all_cross_reference_failures(bundle, result) -> None:
    assert result.trace is not None
    trace = result.trace
    activity = trace.activity_executions[0].model_copy(
        update={"action_execution_ids": [], "deviation_ids": ["missing_deviation"]}
    )
    movement = trace.movements[0]
    invalid_waypoint = movement.waypoints[0].model_copy(update={"region_id": "missing_region"})
    invalid_movement = movement.model_copy(
        update={"action_execution_id": "missing_action", "waypoints": [invalid_waypoint]}
    )
    resident = trace.final_state.residents[0].model_copy(update={"held_resource_ids": ["bed_01"]})
    final_state = trace.final_state.model_copy(update={"residents": [resident]})
    invalid_trace = trace.model_copy(
        update={
            "activity_executions": [activity, *trace.activity_executions[1:]],
            "action_executions": [trace.action_executions[0], *trace.action_executions],
            "movements": [invalid_movement, *trace.movements[1:]],
            "final_state": final_state,
        }
    )

    messages = [item.message for item in validate_execution_trace(invalid_trace, bundle)]
    assert any("Duplicate action identifiers" in message for message in messages)
    assert any("inconsistent action references" in message for message in messages)
    assert any("unknown deviation" in message for message in messages)
    assert any("unknown action" in message for message in messages)
    assert any("leaves region geometry" in message for message in messages)
    assert any("retains a resource" in message for message in messages)


def test_trace_invariant_validator_rejects_obstacles_and_non_monotonic_time(bundle, result) -> None:
    assert result.trace is not None
    trace = result.trace
    movement = trace.movements[0]
    obstacle = bundle.home_model.obstacles[0]
    vertices = obstacle.boundary.vertices
    obstacle_position = movement.waypoints[0].position.model_copy(
        update={
            "x": sum(point.x for point in vertices) / len(vertices),
            "y": sum(point.y for point in vertices) / len(vertices),
        }
    )
    obstacle_waypoint = movement.waypoints[0].model_copy(
        update={"region_id": obstacle.region_id, "position": obstacle_position}
    )
    obstacle_movement = movement.model_copy(update={"waypoints": [obstacle_waypoint]})
    obstacle_trace = trace.model_copy(
        update={"movements": [obstacle_movement, *trace.movements[1:]]}
    )
    assert any(
        "enters an obstacle" in item.message
        for item in validate_execution_trace(obstacle_trace, bundle)
    )

    early_waypoint = movement.waypoints[0].model_copy(
        update={"at": movement.started_at - timedelta(microseconds=1)}
    )
    early_movement = movement.model_copy(update={"waypoints": [early_waypoint]})
    early_trace = trace.model_copy(update={"movements": [early_movement, *trace.movements[1:]]})
    assert any(
        "non-monotonic waypoint time" in item.message
        for item in validate_execution_trace(early_trace, bundle)
    )


def test_public_execution_models_reject_inconsistent_intervals(result) -> None:
    assert result.trace is not None
    action = result.trace.action_executions[0]
    with pytest.raises(ValidationError):
        ActionExecution.model_validate(
            {
                **action.model_dump(mode="python"),
                "started_at": action.ended_at,
                "ended_at": action.started_at,
            }
        )
    activity = result.trace.activity_executions[0]
    with pytest.raises(ValidationError):
        ActivityExecution.model_validate(
            {
                **activity.model_dump(mode="python"),
                "status": "failed",
                "failure_code": None,
            }
        )
    movement = result.trace.movements[0]
    with pytest.raises(ValidationError):
        MovementExecution.model_validate(
            {
                **movement.model_dump(mode="python"),
                "started_at": movement.ended_at,
                "ended_at": movement.started_at,
            }
        )


def test_cli_simulate_and_replay_are_atomic(result, tmp_path: Path) -> None:
    runner = CliRunner()
    trace_path = tmp_path / "trace.json"
    report_path = tmp_path / "report.json"
    invocation = runner.invoke(
        app,
        [
            "simulate",
            str(BUNDLE_PATH),
            "--output",
            str(trace_path),
            "--report-output",
            str(report_path),
        ],
    )
    assert invocation.exit_code == 0, invocation.output
    assert trace_path.exists() and report_path.exists()
    replay_path = tmp_path / "replay.json"
    invocation = runner.invoke(
        app,
        [
            "replay",
            str(BUNDLE_PATH),
            str(trace_path),
            "--output",
            str(replay_path),
        ],
    )
    assert invocation.exit_code == 0, invocation.output
    assert json.loads(replay_path.read_text())["matches"] is True


def test_cli_rejects_output_conflicts(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["simulate", str(BUNDLE_PATH), "--output", str(BUNDLE_PATH)],
    )
    assert result.exit_code == 2
    result = runner.invoke(
        app,
        ["replay", str(BUNDLE_PATH), str(BUNDLE_PATH), "--output", str(BUNDLE_PATH)],
    )
    assert result.exit_code == 2


def test_engine_failure_never_returns_partial_trace(bundle, monkeypatch) -> None:
    def fail(_self):
        raise RuntimeError("boom")

    monkeypatch.setattr(SimulationEngine, "run", fail)
    result = simulate_bundle(bundle)
    assert result.trace is None
    assert result.report.issues[0].code == "SIMULATION_FAILED"
