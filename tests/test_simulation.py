from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import pytest
import simpy
from pydantic import ValidationError
from typer.testing import CliRunner

from smart_home_sim.cli import app
from smart_home_sim.domain.behavior import ProcessNode, ProcessNodeKind
from smart_home_sim.domain.environment import (
    EntityCapability,
    HomeEntity,
    HomeObstacle,
    InteractionPoint,
    Point2D,
    Polygon2D,
    SimulationBundle,
    TraversalMode,
)
from smart_home_sim.domain.execution import (
    ActionExecution,
    ActivityExecution,
    MovementExecution,
)
from smart_home_sim.domain.models import Condition, ConditionOperator
from smart_home_sim.environment.navigation import NavigationPath, NavigationWaypoint
from smart_home_sim.simulation.service import (
    _AMBULATORY_POSTURES,
    _SEATING_FURNITURE,
    _TRANSIENT_REGIONS,
    EXECUTION_PACE_MAX_FACTOR,
    EXECUTION_PACE_MIN_FACTOR,
    PUNCTUAL_ACTION_SECONDS,
    RETURN_NODE_ID,
    NamedRandomStreams,
    ResidentRuntime,
    ResourceCoordinator,
    SimulationEngine,
    _initial_runtime,
    _known_scenario_fact,
    _operator_matches,
    _phase_durations,
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
    # 769 authored actions plus the walks the engine adds to leave a service room it has nothing
    # else to do in: they belong to the activity that just ended, so the count of activities is
    # untouched and no intent is invented. The count moves when anything changes where a gap falls
    # — the transition pause moved it by one — which is why the activity count above is the
    # invariant and this is a reading. It moved from 794 to 796 when the committed bundle was
    # rebuilt: the one in the repository predated the change that stopped a carried item counting
    # as somewhere to walk to, so two of the walks it recorded were not walks the code still plans.
    # The movement count below fell from 224 for the same reason, and both readings are what the
    # code at that commit already produced once the bundle was rebuilt from its own inputs.
    assert len(trace.action_executions) == 796
    assert len(trace.movements) == 205
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


def test_a_service_room_is_left_when_the_plan_has_nothing_next(result) -> None:
    """The two hours in the bathroom, and why they are not a labelling problem.

    A shower used to end with `deactivate{shower_water}` and nothing after it, so the resident held
    that spot until the next thing in the plan came for her — 2 h 16 m on the first day of one
    generated year, 65 minutes a day in the bathroom across the whole of it, and the presence model
    faithfully emitting a person's worth of bathroom motion the whole time.

    The walk out belongs to the activity that just ended, which is both what the trace contract
    requires and the honest reading: coming out of the bathroom is part of finishing the shower.
    Nothing new appears in the ground truth.
    """
    trace = result.trace
    returns = [item for item in trace.action_executions if item.node_id == RETURN_NODE_ID]
    assert returns

    activities = {item.activity_execution_id: item for item in trace.activity_executions}
    movements = {item.action_execution_id: item for item in trace.movements}
    for action in returns:
        # It hangs off a real activity, and that activity claims it.
        owner = activities[action.activity_execution_id]
        assert action.action_execution_id in owner.action_execution_ids
        assert owner.actual_start <= action.started_at <= owner.actual_end
        movement = movements[action.action_execution_id]
        assert movement.origin_region_id in _TRANSIENT_REGIONS
        assert movement.destination_region_id not in _TRANSIENT_REGIONS


def test_the_wait_sits_down_rather_than_standing_for_hours(result) -> None:
    """What a body does with time nobody planned: it sits.

    Posture and nothing else, deliberately. A posture change needs no action to hang off, so the
    gaps stay unlabelled — nobody planned anything there and the ground truth should say so — while
    the log stops describing a person standing still for hours. The presence-pulse rate is read
    from the posture at every pulse, so this is the whole of the correction on the sensor side.
    """
    trace = result.trace
    settled = [
        item
        for item in trace.state_transitions
        if item.fact == "posture" and item.causality.cause_type == "plan"
    ]
    assert settled
    assert all(str(item.value) not in _AMBULATORY_POSTURES for item in settled)

    # Every one of them falls in a gap: no activity was running when the resident sat down.
    spans = [(item.actual_start, item.actual_end) for item in trace.activity_executions]
    for item in settled:
        assert not any(start < item.at < end for start, end in spans)

    # And none of them invented an activity to hang off: the causes are activity ids that exist.
    known = {item.activity_execution_id for item in trace.activity_executions}
    assert all(item.causality.cause_id in known for item in settled)


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
    assert result.report.issues[0].details["activityId"]
    assert result.report.issues[0].details["actionType"]
    assert result.report.issues[0].details["fact"]
    assert "expected" in result.report.issues[0].details
    assert "actual" in result.report.issues[0].details


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
    # Execution pace scales the planned durations, so pin what preemption is actually about: the
    # suspension neither stretches the activity nor truncates the resumed action. Each is checked
    # against its own planned length because the phase split rounds and an action is floored by
    # its movement time, so the two do not scale by exactly the same factor.
    executed_seconds = (low_execution.actual_end - low_execution.actual_start).total_seconds()
    action_seconds = (low_action.ended_at - low_action.started_at).total_seconds()
    assert 600 * EXECUTION_PACE_MIN_FACTOR <= executed_seconds <= 600 * EXECUTION_PACE_MAX_FACTOR
    assert 450 * EXECUTION_PACE_MIN_FACTOR <= action_seconds <= 450 * EXECUTION_PACE_MAX_FACTOR


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


def test_execution_pace_breaks_whole_minute_durations(bundle: SimulationBundle) -> None:
    """Realised durations must not all be whole minutes.

    Plans are authored in minutes, and while execution reproduced them exactly every activity in
    an exported log lasted a whole number of minutes: `(actualEnd - actualStart) % 60 == 0` held
    for 4819 of 4821 activities in a year-long run. One modulo told a reader the log was generated.
    Pace makes the plan the intention rather than the stopwatch, so the realised duration lands
    off the grid while staying centred on what was planned.
    """
    result = simulate_bundle(bundle)
    assert result.trace is not None
    durations = [
        item.actual_end - item.actual_start
        for item in result.trace.activity_executions
        if item.actual_end > item.actual_start
    ]
    assert len(durations) > 10
    microseconds = [
        item.days * 86_400_000_000 + item.seconds * 1_000_000 + item.microseconds
        for item in durations
    ]
    assert not any(value % 60_000_000 == 0 for value in microseconds)
    planned = [
        item.planned_end - item.planned_start
        for item in result.trace.activity_executions
        if item.actual_end > item.actual_start
    ]
    # Centred on the plan, not drifting away from it.
    ratio = sum(microseconds) / sum(
        item.days * 86_400_000_000 + item.seconds * 1_000_000 + item.microseconds
        for item in planned
    )
    assert 0.85 <= ratio <= 1.15


def _node(action_type: str, weight: float = 1.0) -> ProcessNode:
    return ProcessNode(
        node_id=action_type,
        kind=ProcessNodeKind.action,
        action_type=action_type,
        duration_weight=weight,
    )


def test_gestures_keep_their_own_length_and_elastic_steps_absorb_the_rest() -> None:
    """A gesture must not stretch with the activity that contains it.

    The whole budget used to be shared out by `durationWeight`, and the authoring model emits 1.0
    on every node, so an eight-hour sleep of `move_to`/`change_posture`/`wait` became two hours
    and forty minutes of walking to bed, the same again of lying down, and one third of sleeping.
    """
    phases = [[_node("move_to")], [_node("change_posture")], [_node("wait")]]
    durations = _phase_durations(phases, 8 * 3600 * 1_000_000)
    assert durations[1] == 4 * 1_000_000
    assert durations[2] > 7.9 * 3600 * 1_000_000
    # The activity's total is untouched, which is what keeps the habit ground truth valid across
    # this change. Rounding leaves a microsecond or two anywhere the shares do not divide evenly.
    assert abs(sum(durations) - 8 * 3600 * 1_000_000) <= len(durations)


def test_elastic_phases_still_split_the_remainder_by_weight() -> None:
    phases = [[_node("change_posture")], [_node("wait", 3.0)], [_node("perform_work", 1.0)]]
    durations = _phase_durations(phases, 4 * 3600 * 1_000_000)
    assert durations[1] == pytest.approx(3 * durations[2], rel=1e-3)


def test_a_phase_is_elastic_when_any_parallel_branch_is() -> None:
    phases = [[_node("change_posture"), _node("wait")]]
    assert _phase_durations(phases, 600 * 1_000_000) == [600 * 1_000_000]


def test_a_process_of_pure_gestures_still_shares_the_budget_by_weight() -> None:
    """Nothing can absorb the budget here, so stretching the gestures is the only answer."""
    phases = [[_node("open")], [_node("close")], [_node("activate")]]
    assert _phase_durations(phases, 90 * 1_000_000) == [30 * 1_000_000] * 3


def test_executed_gestures_stay_short_across_a_whole_week(result, bundle) -> None:
    """The end-to-end guard: whenever an activity has something to absorb its budget, it does.

    `change_posture` is one of the action types the PIR model treats as manual work, emitting a
    pulse every eighteen seconds, so a long one floods the log with motion from a resident who is
    holding still. A gesture may still run long for two honest reasons — it is preceded by a walk,
    and the walk takes as long as it takes; and if the resident was lying or sitting, the walk is
    preceded by her standing up. So the bound is the gesture's own length or its movement,
    whichever is greater, plus the one posture transition a move may carry. Activities made of
    nothing but gestures, `wake_up` among them, have no elastic step to hand the time to and are
    exempt: stretching them is the only answer.
    """
    assert result.trace is not None
    stand_up = max(
        item.posture_transition_seconds.get("standing", 0.0) for item in bundle.resident_kinematics
    )
    elastic_activities = {
        item.activity_execution_id
        for item in result.trace.action_executions
        if item.action_type not in PUNCTUAL_ACTION_SECONDS
    }
    walked = {
        item.action_execution_id: item.duration_microseconds / 1_000_000
        for item in result.trace.movements
    }
    gestures = [
        item
        for item in result.trace.action_executions
        if item.action_type in PUNCTUAL_ACTION_SECONDS
        and item.activity_execution_id in elastic_activities
    ]
    assert len(gestures) > 20
    overruns = [
        (item.node_id, item.action_type, seconds)
        for item in gestures
        if (seconds := (item.ended_at - item.started_at).total_seconds())
        > max(PUNCTUAL_ACTION_SECONDS[item.action_type], walked.get(item.action_execution_id, 0.0))
        + stand_up
        + 1.0
    ]
    assert not overruns


def test_lying_down_takes_longer_than_sitting_down(result) -> None:
    """`change_posture` must last what the bundle says it lasts, per posture.

    `residentKinematics.postureTransitionSeconds` states 1.5 s to stand, 2.0 to sit and 3.0 to lie,
    is validated by the home model contract and travels in every bundle — and was read by nothing.
    A single constant for every posture would throw that away.
    """
    assert result.trace is not None
    elastic_activities = {
        item.activity_execution_id
        for item in result.trace.action_executions
        if item.action_type not in PUNCTUAL_ACTION_SECONDS
    }
    walked = {item.action_execution_id for item in result.trace.movements}
    by_posture: dict[str, set[float]] = defaultdict(set)
    for item in result.trace.action_executions:
        if item.action_type != "change_posture" or item.action_execution_id in walked:
            continue
        # `wake_up` is nothing but gestures, so there the budget still stretches them and the
        # kinematics have nothing to say.
        if item.activity_execution_id not in elastic_activities:
            continue
        posture = item.resolved_arguments["posture"]
        by_posture[str(posture)].add(round((item.ended_at - item.started_at).total_seconds(), 3))
    assert by_posture["sitting"] == {2.0}
    assert by_posture["standing"] == {1.5}
    assert PUNCTUAL_ACTION_SECONDS["change_posture"] not in {2.0, 1.5}


def _furnished_living_room(bundle: SimulationBundle) -> SimulationBundle:
    """The golden home with two seats in the living room and a desk pulled up to one of them."""
    home = bundle.home_model
    approach = [
        EntityCapability(
            capability="interaction_point", roles=[], supported_operations=["move_to_capability"]
        )
    ]
    points = [
        *home.interaction_points,
        InteractionPoint(
            interaction_point_id="ip_near_chair",
            region_id="living_room",
            position=Point2D(x=11.8, y=8.0),
            approach_radius_meters=0.35,
        ),
        InteractionPoint(
            interaction_point_id="ip_far_armchair",
            region_id="living_room",
            position=Point2D(x=18.5, y=11.0),
            approach_radius_meters=0.35,
        ),
        InteractionPoint(
            interaction_point_id="ip_desk",
            region_id="living_room",
            position=Point2D(x=14.7, y=8.0),
            approach_radius_meters=0.35,
        ),
    ]
    entities = [
        *home.entities,
        HomeEntity(
            entity_id="near_chair",
            entity_type="chair",
            region_id="living_room",
            interaction_point_id="ip_near_chair",
            capabilities=approach,
        ),
        HomeEntity(
            entity_id="far_armchair",
            entity_type="armchair",
            region_id="living_room",
            interaction_point_id="ip_far_armchair",
            capabilities=approach,
        ),
        HomeEntity(
            entity_id="desk",
            entity_type="desk",
            region_id="living_room",
            interaction_point_id="ip_desk",
            capabilities=approach,
        ),
    ]
    obstacles = [
        *home.obstacles,
        HomeObstacle(
            obstacle_id="obstacle_near_chair",
            region_id="living_room",
            boundary=Polygon2D(
                vertices=[
                    Point2D(x=12.2, y=7.8),
                    Point2D(x=12.6, y=7.8),
                    Point2D(x=12.6, y=8.2),
                    Point2D(x=12.2, y=8.2),
                ]
            ),
        ),
        HomeObstacle(
            obstacle_id="obstacle_desk",
            region_id="living_room",
            boundary=Polygon2D(
                vertices=[
                    Point2D(x=13.0, y=7.6),
                    Point2D(x=14.3, y=7.6),
                    Point2D(x=14.3, y=8.4),
                    Point2D(x=13.0, y=8.4),
                ]
            ),
        ),
    ]
    return bundle.model_copy(
        update={
            "home_model": home.model_copy(
                update={
                    "interaction_points": points,
                    "entities": entities,
                    "obstacles": obstacles,
                }
            )
        }
    )


def test_she_sits_on_the_seat_she_is_standing_next_to(bundle) -> None:
    """By id it was whichever seat sorted first, which is a fact about its name.

    A study holding a desk chair and a reading armchair sat her in the armchair to work and then
    walked her back to the desk, still recorded as sitting: the sensor log put her in the armchair
    for the whole block and the replay drew her at the desk, and neither was wrong about the trace
    it was reading. `far_armchair` sorts before `near_chair`, so this is that ordering exactly.
    """
    engine = SimulationEngine(_furnished_living_room(bundle))
    actor = ResidentRuntime(
        resident_id="resident_mario_rossi",
        region_id="living_room",
        position=Point2D(x=14.7, y=8.0),
    )

    assert engine._resting_entity(actor, _SEATING_FURNITURE).entity_id == "near_chair"

    # And from the other end of the room, the armchair. Nearest, not favourite.
    actor.position = Point2D(x=19.0, y=11.5)
    assert engine._resting_entity(actor, _SEATING_FURNITURE).entity_id == "far_armchair"


def test_a_seated_body_reaches_the_desk_rather_than_getting_up_to_walk_round_it(bundle) -> None:
    """An interaction point is where a body *stands*, so a chair and the desk it is at have two.

    Walking between them is what turned eighty minutes of work into a body standing at a keyboard
    with the posture reading `sitting`. Measured from the berth to the *footprint*, because the
    question is whether what she wants is within arm's length of where she is sitting.
    """
    engine = SimulationEngine(_furnished_living_room(bundle))
    seated = ResidentRuntime(
        resident_id="resident_mario_rossi",
        region_id="living_room",
        position=Point2D(x=11.8, y=8.0),
        posture="sitting",
        resting_at=Point2D(x=12.4, y=8.0),
    )

    assert engine._within_reach(seated, "ip_desk")
    # Nothing across the room, and nothing at all while she is on her feet.
    assert not engine._within_reach(seated, "ip_far_armchair")
    seated.resting_at = None
    assert not engine._within_reach(seated, "ip_desk")


def test_she_sits_back_down_after_reaching_something_across_the_room(bundle) -> None:
    """Getting up to press a button is not the end of sitting down.

    The berth survives a walk that does not leave the room — which is right, a posture is what lets
    a berth go — so the trace went on saying she was on the sofa while the body stood at the
    television for the thirty-one minutes she watched it. The sensor projection read the berth and
    the replay read the movement, and the two described different evenings. She goes back.
    """
    engine = SimulationEngine(_furnished_living_room(bundle))
    actor = ResidentRuntime(
        resident_id="resident_mario_rossi",
        region_id="living_room",
        position=Point2D(x=14.7, y=8.0),
        posture="sitting",
        resting_at=Point2D(x=12.4, y=8.0),
    )

    walk = list(engine._sit_back_down(actor, "action_1"))
    assert walk, "the body was across the room from the seat it is recorded as being on"

    # Nothing to do when she never left: the berth is where she already is.
    settled = ResidentRuntime(
        resident_id="resident_mario_rossi",
        region_id="living_room",
        position=Point2D(x=11.8, y=8.0),
        posture="sitting",
        resting_at=Point2D(x=12.4, y=8.0),
    )
    assert list(engine._sit_back_down(settled, "action_2")) == []


def test_a_lying_body_stands_up_even_for_a_walk_that_stays_in_the_room(bundle) -> None:
    """Reaching across the table is a person; crossing the room from the bed is two channels lying.

    The stand-up used to be owed only to a walk that changed room, and that handed the exemption to
    a lying body as well as a seated one: over five months 380 of 8,131 movements were walked with
    the posture still reading `lying`, every one of them inside a single room, the longest 2.58 m.
    Nothing is within reach of a body lying down — `_within_reach` has already turned every genuine
    reach into no path at all — so a walk that gets this far while lying is a walk.
    """
    engine = SimulationEngine(_furnished_living_room(bundle))
    across_the_room = NavigationPath(
        waypoints=(
            NavigationWaypoint(
                region_id="living_room", x=11.8, y=8.0, traversal_mode=TraversalMode.walking
            ),
            NavigationWaypoint(
                region_id="living_room", x=14.7, y=8.0, traversal_mode=TraversalMode.walking
            ),
        ),
        distance_meters=2.9,
        duration_seconds=3.0,
    )

    lying = ResidentRuntime(
        resident_id="resident_mario_rossi",
        region_id="living_room",
        position=Point2D(x=11.8, y=8.0),
        posture="lying",
        resting_at=Point2D(x=11.8, y=8.0),
    )
    list(engine._travel(lying, across_the_room, 3_000_000, "action_lying"))
    assert lying.posture in _AMBULATORY_POSTURES
    assert lying.resting_at is None, "she is not still on the thing she was lying on"

    # And the reason the gate was narrow in the first place survives: a seated body stays seated,
    # which is what stopped a twenty-eight minute breakfast being eaten standing up.
    seated = ResidentRuntime(
        resident_id="resident_mario_rossi",
        region_id="living_room",
        position=Point2D(x=11.8, y=8.0),
        posture="sitting",
        resting_at=Point2D(x=11.8, y=8.0),
    )
    list(engine._travel(seated, across_the_room, 3_000_000, "action_seated"))
    assert seated.posture == "sitting"


def test_the_return_walk_says_which_room_it_walked_into(result) -> None:
    """A walk the catalog never routed still owes the fact the catalog says it writes.

    `move_to` declares `resident.location := {destination}` and the engine's own walk out of a
    service room wrote the action without ever applying it, so the fact went on naming the bathroom
    for every minute after a shower: over five months 1,466 of 12,080 stationary stretches — 18,585
    minutes — had the resident recorded in a room her own waypoints had already left.
    """
    trace = result.trace
    returns = [item for item in trace.action_executions if item.node_id == RETURN_NODE_ID]
    assert returns

    moves = defaultdict(list)
    for transition in trace.state_transitions:
        if transition.fact == "location":
            moves[transition.causality.cause_id].append(transition)

    for action in returns:
        written = moves[action.action_execution_id]
        assert len(written) == 1, "one walk, one statement about where it ended"
        assert written[0].value == action.resolved_arguments["destination"]


def _dinner_the_plan_gives_up_on(bundle: SimulationBundle) -> SimulationBundle:
    """The golden week with `d1_a22` optional and impossible.

    It is the activity that follows a shower by 7.7 minutes, which is inside
    `IDLE_RETURN_AFTER_SECONDS`: the walk out of the bathroom is deferred for it, and then it never
    happens.
    """
    plan = bundle.canonical_plan.model_copy(deep=True)
    target = next(
        activity
        for day in plan.days
        for activity in day.activities
        if activity.source_activity_id == "d1_a22"
    )
    target.mandatory = False
    target.preconditions = [
        Condition(fact="resident.a_fact_no_day_ever_sets", operator=ConditionOperator.exists)
    ]
    return bundle.model_copy(update={"canonical_plan": plan})


def test_giving_up_on_an_activity_walks_her_out_of_the_room_it_left_her_waiting_in(
    bundle: SimulationBundle,
) -> None:
    """The bathroom stay that is a person, and the one that is the engine forgetting.

    `_return_from_service_room` decides once, when an activity ends, and defers when the next
    commitment is inside `IDLE_RETURN_AFTER_SECONDS` — she is between two steps of the same morning
    and the walk is not worth taking. That commitment can then be dropped for failing its live
    preconditions, and nothing revisited the decision: over five months every one of the 43 idle
    bathroom stays past twenty minutes had a dropped activity inside that window, sixteen of them
    past the hour and the longest 111.8 minutes, against a median stay of 4.2. Sitting there a
    while is a person. The tail was this.

    The walk is filed under the activity that was dropped, which is the only one that can own it
    and is also the honest reading: the plan giving up is what sent her out.
    """
    trace = simulate_bundle(_dinner_the_plan_gives_up_on(bundle)).trace
    assert not validate_execution_trace(trace, _dinner_the_plan_gives_up_on(bundle))

    dropped = next(
        item for item in trace.activity_executions if item.source_activity_id == "d1_a22"
    )
    assert dropped.status == "dropped"
    # Giving up stays a zero-length statement that nothing happened.
    assert dropped.actual_start == dropped.actual_end

    walk = next(
        item
        for item in trace.action_executions
        if item.action_execution_id in dropped.action_execution_ids
    )
    assert walk.node_id == RETURN_NODE_ID
    movement = next(
        item for item in trace.movements if item.action_execution_id == walk.action_execution_id
    )
    assert movement.origin_region_id in _TRANSIENT_REGIONS
    assert movement.destination_region_id not in _TRANSIENT_REGIONS

    # And she is not left standing in the room the walk delivered her to.
    postures = [
        item
        for item in trace.state_transitions
        if item.fact == "posture" and item.at >= walk.ended_at
    ]
    assert postures and postures[0].value != "standing"
