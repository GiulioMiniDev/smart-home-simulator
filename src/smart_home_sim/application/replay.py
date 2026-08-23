from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import JsonValue

from smart_home_sim.application.horizon_run import verify_horizon
from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import (
    DiaryAction,
    DiaryEntry,
    ObservableReplayEventView,
    ObservationCause,
    ObservationView,
    ReplayEventKind,
    ReplayEventView,
    ReplayEventWindow,
    ReplayFrame,
    ReplayResidentFrame,
    ReplaySensorFrame,
    ReplayVerification,
    ReplayWaypoint,
    utc_now,
)
from smart_home_sim.domain.environment import Point2D, SimulationBundle
from smart_home_sim.domain.execution import (
    ExecutionTrace,
    MovementExecution,
    StateTransition,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.profile import ResidentProfile
from smart_home_sim.domain.sensors import ObservableSensorLog, OracleMapping
from smart_home_sim.profiling import DEFAULT_SLOT_MINUTES, profile_from_trace
from smart_home_sim.simulation import replay_files


@lru_cache(maxsize=8)
def _trace(path: str, digest: str) -> ExecutionTrace:
    del digest
    return ExecutionTrace.model_validate_json(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _profile(path: str, digest: str, run_id: str, slot_minutes: int) -> ResidentProfile:
    """Aggregating a horizon costs real time, and the answer cannot change while the digest holds.

    Kept separate from the trace cache because the profile survives the trace being evicted, and
    because the same trace can be asked for at more than one slot width.
    """
    return profile_from_trace(_trace(path, digest), run_id=run_id, slot_minutes=slot_minutes)


@lru_cache(maxsize=8)
def _observations(path: str, digest: str) -> ObservableSensorLog:
    del digest
    return ObservableSensorLog.model_validate_json(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _oracle(path: str, digest: str) -> OracleMapping:
    del digest
    return OracleMapping.model_validate_json(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _bundle(path: str, digest: str) -> SimulationBundle:
    del digest
    return SimulationBundle.model_validate_json(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class _FrameSources:
    residents: dict[str, dict[str, Any]]
    resident_ids: tuple[str, ...]
    entity_states: dict[str, dict[str, JsonValue]]
    environment_facts: dict[str, JsonValue]
    resources: dict[str, int]
    activities: tuple[Any, ...]
    activity_times: tuple[datetime, ...]
    active_activity_times: tuple[datetime, ...]
    active_activity_snapshots: tuple[tuple[Any, ...], ...]
    actions: tuple[Any, ...]
    action_times: tuple[datetime, ...]
    active_action_times: tuple[datetime, ...]
    active_action_snapshots: tuple[tuple[Any, ...], ...]
    movements: tuple[Any, ...]
    movement_times: tuple[datetime, ...]
    transitions: tuple[Any, ...]
    transition_times: tuple[datetime, ...]
    resource_events: tuple[Any, ...]
    resource_times: tuple[datetime, ...]
    transition_timelines: tuple[
        tuple[tuple[str, str, str], tuple[datetime, ...], tuple[StateTransition, ...]], ...
    ]
    completed_movement_timelines: tuple[
        tuple[str, tuple[datetime, ...], tuple[MovementExecution, ...]], ...
    ]
    active_movement_times: tuple[datetime, ...]
    active_movement_snapshots: tuple[tuple[MovementExecution, ...], ...]
    resource_timelines: tuple[tuple[tuple[str, str], tuple[datetime, ...], tuple[Any, ...]], ...]
    resource_availability_timelines: tuple[
        tuple[str, tuple[datetime, ...], tuple[Any, ...]], ...
    ]


@dataclass(frozen=True)
class _ReplayIndex:
    trace_start: datetime
    trace_end: datetime
    events: tuple[ReplayEventView, ...]
    event_times: tuple[datetime, ...]
    trace: ExecutionTrace
    observations: ObservableSensorLog
    sensor_timelines: tuple[tuple[str, tuple[datetime, ...], tuple[Any, ...]], ...]
    frame_sources: _FrameSources
    oracle: OracleMapping | None
    bundle: SimulationBundle | None


def _cause(link: Any) -> ObservationCause:
    return ObservationCause(
        origin=link.origin,
        cause_type=link.cause_type,
        cause_ids=link.cause_ids,
        resident_ids=link.resident_ids,
        activity_execution_ids=link.activity_execution_ids,
        action_execution_ids=link.action_execution_ids,
    )


def _point_at(movement: MovementExecution, at: datetime) -> Point2D:
    waypoints = movement.waypoints
    times = [item.at for item in waypoints]
    right = bisect_right(times, at)
    if right == 0 or right == len(waypoints):
        return _waypoint_at(movement, at).position
    left_item, right_item = waypoints[right - 1], waypoints[right]
    span = (right_item.at - left_item.at).total_seconds()
    ratio = 0.0 if span == 0 else (at - left_item.at).total_seconds() / span
    return Point2D(
        x=left_item.position.x + (right_item.position.x - left_item.position.x) * ratio,
        y=left_item.position.y + (right_item.position.y - left_item.position.y) * ratio,
    )


def _waypoint_at(movement: MovementExecution, at: datetime) -> Any:
    right = bisect_right([item.at for item in movement.waypoints], at)
    return movement.waypoints[max(right - 1, 0)]


def _apply_transition(target: dict[str, JsonValue], transition: StateTransition) -> None:
    if transition.operation in {"set", "increment", "decrement", "append"}:
        target[transition.fact] = transition.value
    elif transition.operation == "remove":
        target.pop(transition.fact, None)
    else:
        target[transition.fact] = None


def _fold_transition_value(
    current: JsonValue | None, transition: StateTransition
) -> JsonValue | None:
    target: dict[str, JsonValue] = {transition.fact: current}
    _apply_transition(target, transition)
    return target.get(transition.fact)


def _active_interval_snapshots(
    items: tuple[Any, ...], *, start: str, end: str, identifier: str
) -> tuple[tuple[datetime, ...], tuple[tuple[Any, ...], ...]]:
    """Precompute interval membership at every start/end boundary for seek-stable frames."""
    boundaries: dict[datetime, list[tuple[bool, Any]]] = {}
    for item in items:
        if getattr(item, end) <= getattr(item, start):
            continue
        boundaries.setdefault(getattr(item, start), []).append((True, item))
        boundaries.setdefault(getattr(item, end), []).append((False, item))
    active: dict[str, Any] = {}
    times: list[datetime] = []
    snapshots: list[tuple[Any, ...]] = []
    for at in sorted(boundaries):
        # Intervals are [start, end): remove endings before accepting same-time starts.
        for begins, item in sorted(boundaries[at], key=lambda entry: entry[0]):
            if begins:
                active[getattr(item, identifier)] = item
            else:
                active.pop(getattr(item, identifier), None)
        times.append(at)
        snapshots.append(
            tuple(
                sorted(
                    active.values(),
                    key=lambda item: (getattr(item, start), getattr(item, identifier)),
                )
            )
        )
    return tuple(times), tuple(snapshots)


def _active_items_at(
    times: tuple[datetime, ...], snapshots: tuple[tuple[Any, ...], ...], at: datetime
) -> tuple[Any, ...]:
    position = bisect_right(times, at)
    return snapshots[position - 1] if position else ()


def _last_timeline_item(
    times: tuple[datetime, ...], items: tuple[Any, ...], at: datetime
) -> Any | None:
    position = bisect_right(times, at)
    return items[position - 1] if position else None


def _daily_summary_available_at(
    summary_date: date, trace_end: datetime, *, timezone: tzinfo | None = None
) -> datetime:
    """Publish a daily aggregate only once its local day has ended.

    ``DailyExecutionSummary.date`` is a local calendar date, rather than an event instant.  Its
    replay timestamp is therefore the following local midnight in the bundle's timezone (or the
    trace's aware offset only when its bundle is unavailable). A trace may end before that
    boundary, so its final summary becomes available at ``trace_end``;
    this keeps the event query honest without inventing time after the authoritative trace.
    """
    local_midnight = datetime.combine(
        summary_date + timedelta(days=1), time.min, tzinfo=timezone or trace_end.tzinfo
    )
    return min(local_midnight, trace_end)


def _events(
    trace: ExecutionTrace,
    observations: ObservableSensorLog,
    timezone: tzinfo | None = None,
) -> tuple[ReplayEventView, ...]:
    events: list[ReplayEventView] = []
    activity_starts = {
        item.activity_execution_id: item.actual_start for item in trace.activity_executions
    }
    for item in trace.activity_executions:
        events.append(
            ReplayEventView(
                at=item.actual_start,
                end=item.actual_end,
                kind="activity",
                event_id=item.activity_execution_id,
                label=item.intent,
                status=item.status,
                actor_id=item.actor_id,
            )
        )
    for item in trace.action_executions:
        events.append(
            ReplayEventView(
                at=item.started_at,
                end=item.ended_at,
                kind="action",
                event_id=item.action_execution_id,
                label=item.action_type,
                status=item.status,
                actor_id=item.actor_id,
                details={"nodeId": item.node_id},
            )
        )
    for item in trace.movements:
        events.append(
            ReplayEventView(
                at=item.started_at,
                end=item.ended_at,
                kind="movement",
                event_id=item.movement_id,
                label=f"{item.origin_region_id} → {item.destination_region_id}",
                status="completed",
                actor_id=item.actor_id,
                waypoints=[
                    ReplayWaypoint(
                        at=waypoint.at,
                        region_id=waypoint.region_id,
                        position=waypoint.position,
                        traversal_mode=waypoint.traversal_mode,
                    )
                    for waypoint in item.waypoints
                ],
            )
        )
    for item in trace.state_transitions:
        events.append(
            ReplayEventView(
                at=item.at,
                kind="state_transition",
                event_id=item.transition_id,
                label=f"{item.subject_type}.{item.fact}",
                details={"operation": item.operation, "value": item.value},
            )
        )
    for item in trace.resource_events:
        events.append(
            ReplayEventView(
                at=item.at,
                kind="resource",
                event_id=item.resource_event_id,
                label=f"{item.resource_id}: {item.operation}",
                actor_id=item.actor_id,
                details={
                    "operation": item.operation,
                    "units": item.units,
                    "availableUnitsAfter": item.available_units_after,
                },
            )
        )
    for item in trace.runtime_events:
        events.append(
            ReplayEventView(
                at=item.evaluated_at,
                kind="runtime_event",
                event_id=item.event_execution_id,
                label=item.event_id,
                status=item.outcome,
                details={"sampled": item.sampled, "occurred": item.occurred},
            )
        )
    for item in trace.plan_deviations:
        events.append(
            ReplayEventView(
                at=activity_starts[item.activity_execution_id],
                kind="plan_deviation",
                event_id=item.deviation_id,
                label=item.kind,
                details={
                    "activityExecutionId": item.activity_execution_id,
                    "amountMicroseconds": item.amount_microseconds,
                },
            )
        )
    for item in trace.daily_summaries:
        events.append(
            ReplayEventView(
                at=_daily_summary_available_at(
                    item.date,
                    trace.ended_at,
                    timezone=timezone,
                ),
                kind="daily_summary",
                event_id=f"daily_summary:{item.date.isoformat()}",
                label=f"Daily summary {item.date.isoformat()}",
                status="completed",
                details={
                    "completedActivityCount": item.completed_activity_count,
                    "deviatedActivityCount": item.deviated_activity_count,
                    "failedActivityCount": item.failed_activity_count,
                    "droppedActivityCount": item.dropped_activity_count,
                },
            )
        )
    for item in observations.records:
        details: dict[str, JsonValue] = {
            "measurement": item.measurement,
            "value": item.value,
            "unit": item.unit,
            "quality": item.quality,
        }
        events.append(
            ReplayEventView(
                at=item.observed_at,
                kind="observation",
                event_id=item.observation_id,
                label=item.measurement,
                sensor_id=item.sensor_id,
                details=details,
            )
        )
    return tuple(sorted(events, key=lambda item: (item.at, item.kind, item.event_id)))


def _replay_index(
    trace_path: str,
    trace_digest: str,
    observations_path: str,
    observations_digest: str,
    oracle_path: str | None,
    oracle_digest: str | None,
    bundle_path: str | None,
    bundle_digest: str | None,
    scenario_path: str | None,
    scenario_digest: str | None,
) -> _ReplayIndex:
    # An index is owned by one ReplayService instance.  Do not reuse it across reopened
    # workspaces: artifact paths can be regenerated in place and a module-level index would
    # retain an unrelated workspace's parsed run for the process lifetime.
    del trace_digest, observations_digest, oracle_digest, bundle_digest, scenario_digest
    trace = ExecutionTrace.model_validate_json(Path(trace_path).read_text(encoding="utf-8"))
    observations = ObservableSensorLog.model_validate_json(
        Path(observations_path).read_text(encoding="utf-8")
    )
    oracle = (
        OracleMapping.model_validate_json(Path(oracle_path).read_text(encoding="utf-8"))
        if oracle_path
        else None
    )
    bundle = (
        SimulationBundle.model_validate_json(Path(bundle_path).read_text(encoding="utf-8"))
        if bundle_path
        else None
    )
    scenario = (
        Scenario.model_validate_json(Path(scenario_path).read_text(encoding="utf-8"))
        if scenario_path
        else None
    )
    events = _events(
        trace,
        observations,
        ZoneInfo(bundle.scenario.time_zone)
        if bundle is not None
        else ZoneInfo(scenario.time_zone) if scenario is not None else None,
    )
    sensor_records: dict[str, list[Any]] = {}
    for record in observations.records:
        sensor_records.setdefault(record.sensor_id, []).append(record)
    sensor_timelines = tuple(
        (sensor_id, tuple(item.observed_at for item in records), tuple(records))
        for sensor_id, records in sorted(sensor_records.items())
    )
    frame_sources = _frame_sources(trace, bundle)
    return _ReplayIndex(
        trace_start=trace.started_at,
        trace_end=trace.ended_at,
        events=events,
        event_times=tuple(item.at for item in events),
        trace=trace,
        observations=observations,
        sensor_timelines=sensor_timelines,
        frame_sources=frame_sources,
        oracle=oracle,
        bundle=bundle,
    )


def _opaque_replay_id(kind: ReplayEventKind, event_id: str) -> str:
    digest = sha256(f"observable-replay-v1:{kind}:{event_id}".encode()).hexdigest()
    return f"replay_{kind}_{digest}"


def _opaque_event_id(item: ReplayEventView) -> str:
    return _opaque_replay_id(item.kind, item.event_id)


def _without_oracle(item: ReplayEventView) -> ReplayEventView:
    observable = ObservableReplayEventView.from_event(deepcopy(item))
    projected = ReplayEventView.model_validate(observable.model_dump(mode="python", by_alias=True))
    if item.kind in {"activity", "action", "movement", "plan_deviation"}:
        projected.event_id = _opaque_event_id(item)
    return projected.model_copy(deep=True)


def _with_oracle(item: ReplayEventView, oracle_links: Mapping[str, Any] | None) -> ReplayEventView:
    result = item.model_copy(deep=True)
    if result.kind != "observation" or oracle_links is None:
        return result
    link = oracle_links.get(result.event_id)
    if link is not None:
        result.details["oracleCause"] = _cause(link).model_dump(mode="json", by_alias=True)
    return result


def _initial_residents(
    trace: ExecutionTrace, bundle: SimulationBundle | None
) -> dict[str, dict[str, Any]]:
    residents: dict[str, dict[str, Any]] = {}
    if bundle is None:
        for transition in sorted(
            (item for item in trace.state_transitions if item.subject_type == "resident"),
            key=lambda item: (item.at, item.transition_id),
        ):
            state = residents.setdefault(
                transition.subject_id,
                {
                    "region_id": None,
                    "position": None,
                    "posture": None,
                    "execution_state": "idle",
                    "facts": {},
                    "seeded": set(),
                },
            )
            seeded: set[str] = state["seeded"]
            if transition.fact == "location" and "location" not in seeded:
                state["region_id"] = transition.previous_value
                state["facts"].setdefault(transition.fact, transition.previous_value)
                seeded.add("location")
            elif transition.fact == "position" and "position" not in seeded:
                if isinstance(transition.previous_value, dict):
                    state["position"] = Point2D.model_validate(transition.previous_value)
                seeded.add("position")
            elif (
                transition.fact in {"posture", "execution_state"} and transition.fact not in seeded
            ):
                state[transition.fact] = transition.previous_value or "idle"
                seeded.add(transition.fact)
            else:
                state["facts"].setdefault(transition.fact, transition.previous_value)
        return residents
    points = {item.interaction_point_id: item for item in bundle.home_model.interaction_points}
    bindings = {item.scenario_location_id: item for item in bundle.home_model.location_bindings}
    for initial in bundle.scenario.initial_state.residents:
        binding = bindings.get(initial.location_id)
        point = points.get(binding.anchor_interaction_point_id) if binding else None
        facts = dict(initial.facts)
        facts.setdefault("at_home", not initial.location_id.startswith("outside"))
        residents[initial.resident_id] = {
            "region_id": point.region_id if point else None,
            "position": point.position if point else None,
            "posture": "lying" if not bool(facts.get("awake", True)) else "standing",
            "execution_state": "idle",
            "facts": facts,
        }
    return residents


def _resident_frames(
    trace: ExecutionTrace,
    bundle: SimulationBundle | None,
    at: datetime,
    sources: _FrameSources | None = None,
) -> tuple[list[ReplayResidentFrame], list[str]]:
    if sources is not None:
        return _indexed_resident_frames(at, sources)
    residents = deepcopy(sources.residents) if sources else _initial_residents(trace, bundle)
    resident_ids = (
        set(sources.resident_ids)
        if sources
        else {item.actor_id for item in trace.activity_executions}
    )
    if sources is None:
        resident_ids.update(item.actor_id for item in trace.action_executions)
        resident_ids.update(item.actor_id for item in trace.movements)
        resident_ids.update(
            item.subject_id for item in trace.state_transitions if item.subject_type == "resident"
        )
    for resident_id in resident_ids:
        residents.setdefault(
            resident_id,
            {
                "region_id": None,
                "position": None,
                "posture": None,
                "execution_state": "idle",
                "facts": {},
            },
        )
    transitions = (
        sources.transitions[: bisect_right(sources.transition_times, at)]
        if sources
        else sorted(
            (item for item in trace.state_transitions if item.at <= at),
            key=lambda item: (item.at, item.transition_id),
        )
    )
    for transition in transitions:
        if transition.subject_type != "resident":
            continue
        state = residents[transition.subject_id]
        if transition.fact in {"location", "position"}:
            continue
        if transition.fact not in {"position", "execution_state"}:
            _apply_transition(state["facts"], transition)
        if transition.fact == "posture":
            value = _fold_transition_value(state["posture"], transition)
            state["posture"] = value if isinstance(value, str) else None
        elif transition.fact == "execution_state":
            value = _fold_transition_value(state["execution_state"], transition)
            state["execution_state"] = value if isinstance(value, str) and value else "unknown"
    active_activities = (
        _active_items_at(
            sources.active_activity_times, sources.active_activity_snapshots, at
        )
        if sources
        else tuple(
            item for item in trace.activity_executions if item.actual_start <= at < item.actual_end
        )
    )
    active_actions = (
        _active_items_at(sources.active_action_times, sources.active_action_snapshots, at)
        if sources
        else tuple(
            item for item in trace.action_executions if item.started_at <= at < item.ended_at
        )
    )
    active_ids = {item.activity_execution_id for item in active_activities} | {
        item.action_execution_id for item in active_actions
    }
    spatial_updates: list[tuple[datetime, int, str, str, Any]] = [
        (item.at, 1, item.transition_id, "transition", item)
        for item in transitions
        if item.subject_type == "resident"
        and item.fact in {"location", "position"}
        and item.at <= at
    ]
    movements = (
        sources.movements[: bisect_right(sources.movement_times, at)]
        if sources
        else sorted(trace.movements, key=lambda item: (item.started_at, item.movement_id))
    )
    for movement in movements:
        state = residents[movement.actor_id]
        if movement.started_at <= at < movement.ended_at:
            spatial_updates.append((at, 0, movement.movement_id, "movement", movement))
            state["execution_state"] = "moving"
            active_ids.add(movement.movement_id)
        elif movement.ended_at <= at:
            spatial_updates.append(
                (movement.ended_at, 0, movement.movement_id, "movement", movement)
            )
    for timestamp, _, _, update_kind, item in sorted(spatial_updates, key=lambda item: item[:3]):
        if update_kind == "movement":
            movement = item
            state = residents[movement.actor_id]
            state["region_id"] = _waypoint_at(movement, timestamp).region_id
            state["position"] = _point_at(movement, timestamp)
            continue
        transition = item
        state = residents[transition.subject_id]
        _apply_transition(state["facts"], transition)
        if transition.fact == "location":
            value = _fold_transition_value(state["region_id"], transition)
            state["region_id"] = value if isinstance(value, str) else None
        else:
            current = state["position"]
            raw_current = current.model_dump(mode="python") if current is not None else None
            value = _fold_transition_value(raw_current, transition)
            state["position"] = Point2D.model_validate(value) if isinstance(value, dict) else None
    held = {resident_id: set() for resident_id in residents}
    resource_events = (
        sources.resource_events[: bisect_right(sources.resource_times, at)]
        if sources
        else sorted(
            (item for item in trace.resource_events if item.at <= at),
            key=lambda item: (item.at, item.resource_event_id),
        )
    )
    for event in resource_events:
        if event.actor_id not in held:
            held[event.actor_id] = set()
        if event.operation == "acquired":
            held[event.actor_id].add(event.resource_id)
        elif event.operation in {"released", "preempted"}:
            held[event.actor_id].discard(event.resource_id)
    activity_by_actor = {item.actor_id: item.activity_execution_id for item in active_activities}
    activity_label_by_actor = {item.actor_id: item.intent for item in active_activities}
    action_by_actor = {item.actor_id: item.action_execution_id for item in active_actions}
    active_actors = set(activity_by_actor) | set(action_by_actor)
    for resident_id, state in residents.items():
        if resident_id not in active_actors and state["execution_state"] in {
            "moving",
            "performing_activity",
        }:
            state["execution_state"] = "idle"
    frames = [
        ReplayResidentFrame(
            resident_id=resident_id,
            region_id=state["region_id"],
            position=state["position"],
            posture=state["posture"],
            execution_state=state["execution_state"],
            activity_active=resident_id in activity_by_actor,
            activity_label=activity_label_by_actor.get(resident_id),
            activity_execution_id=activity_by_actor.get(resident_id),
            action_execution_id=action_by_actor.get(resident_id),
            held_resource_ids=sorted(held.get(resident_id, set())),
            facts=deepcopy(state["facts"]),
        )
        for resident_id, state in sorted(residents.items())
    ]
    return frames, sorted(active_ids)


def _indexed_resident_frames(
    at: datetime, sources: _FrameSources
) -> tuple[list[ReplayResidentFrame], list[str]]:
    """Reconstruct residents from their latest field deltas instead of a trace-prefix fold."""
    residents = deepcopy(sources.residents)
    for resident_id in sources.resident_ids:
        residents.setdefault(
            resident_id,
            {
                "region_id": None,
                "position": None,
                "posture": None,
                "execution_state": "idle",
                "facts": {},
            },
        )

    latest_transitions: dict[tuple[str, str, str], StateTransition] = {}
    for key, times, transitions in sources.transition_timelines:
        transition = _last_timeline_item(times, transitions, at)
        if transition is not None:
            latest_transitions[key] = transition

    active_activities = _active_items_at(
        sources.active_activity_times, sources.active_activity_snapshots, at
    )
    active_actions = _active_items_at(
        sources.active_action_times, sources.active_action_snapshots, at
    )
    active_ids = {item.activity_execution_id for item in active_activities} | {
        item.action_execution_id for item in active_actions
    }

    completed_movements = {
        resident_id: _last_timeline_item(times, movements, at)
        for resident_id, times, movements in sources.completed_movement_timelines
    }
    active_movements: dict[str, MovementExecution] = {}
    for movement in _active_items_at(
        sources.active_movement_times, sources.active_movement_snapshots, at
    ):
        current = active_movements.get(movement.actor_id)
        if current is None or movement.movement_id > current.movement_id:
            active_movements[movement.actor_id] = movement
    for movement in active_movements.values():
        active_ids.add(movement.movement_id)

    held: dict[str, set[str]] = {resident_id: set() for resident_id in residents}
    for (actor_id, resource_id), times, events in sources.resource_timelines:
        event = _last_timeline_item(times, events, at)
        if event is None:
            continue
        held.setdefault(actor_id, set())
        if event.operation == "acquired":
            held[actor_id].add(resource_id)

    activity_by_actor = {item.actor_id: item.activity_execution_id for item in active_activities}
    activity_label_by_actor = {item.actor_id: item.intent for item in active_activities}
    action_by_actor = {item.actor_id: item.action_execution_id for item in active_actions}
    active_actors = set(activity_by_actor) | set(action_by_actor)

    for resident_id, state in residents.items():
        for fact in ("posture", "execution_state"):
            transition = latest_transitions.get(("resident", resident_id, fact))
            if transition is not None:
                value = _fold_transition_value(state[fact], transition)
                state[fact] = value if isinstance(value, str) and value else (
                    "unknown" if fact == "execution_state" else None
                )
        for key, transition in latest_transitions.items():
            if key[:2] != ("resident", resident_id) or key[2] == "execution_state":
                continue
            _apply_transition(state["facts"], transition)

        movement = active_movements.get(resident_id)
        transition_region = latest_transitions.get(("resident", resident_id, "location"))
        transition_position = latest_transitions.get(("resident", resident_id, "position"))
        completed = completed_movements.get(resident_id)
        for field, transition in (
            ("region_id", transition_region),
            ("position", transition_position),
        ):
            if movement is not None:
                # A transition at this exact instant follows the synthetic active-movement update.
                if transition is not None and transition.at == at:
                    candidate = _fold_transition_value(
                        state[field].model_dump(mode="python")
                        if field == "position" and state[field] is not None
                        else state[field],
                        transition,
                    )
                    state[field] = (
                        Point2D.model_validate(candidate)
                        if field == "position" and isinstance(candidate, dict)
                        else (
                            candidate
                            if field == "region_id" and isinstance(candidate, str)
                            else None
                        )
                    )
                else:
                    state[field] = (
                        _point_at(movement, at)
                        if field == "position"
                        else _waypoint_at(movement, at).region_id
                    )
                continue
            latest_key = (
                (completed.ended_at, 0, completed.movement_id) if completed is not None else None
            )
            transition_key = (
                (transition.at, 1, transition.transition_id) if transition is not None else None
            )
            if latest_key is not None and (transition_key is None or latest_key > transition_key):
                state[field] = (
                    _point_at(completed, completed.ended_at)
                    if field == "position"
                    else _waypoint_at(completed, completed.ended_at).region_id
                )
            elif transition is not None:
                candidate = _fold_transition_value(
                    state[field].model_dump(mode="python")
                    if field == "position" and state[field] is not None
                    else state[field],
                    transition,
                )
                state[field] = (
                    Point2D.model_validate(candidate)
                    if field == "position" and isinstance(candidate, dict)
                    else candidate if field == "region_id" and isinstance(candidate, str) else None
                )
        if movement is not None:
            state["execution_state"] = "moving"
        elif resident_id not in active_actors and state["execution_state"] in {
            "moving",
            "performing_activity",
        }:
            state["execution_state"] = "idle"

    frames = [
        ReplayResidentFrame(
            resident_id=resident_id,
            region_id=state["region_id"],
            position=state["position"],
            posture=state["posture"],
            execution_state=state["execution_state"],
            activity_active=resident_id in activity_by_actor,
            activity_label=activity_label_by_actor.get(resident_id),
            activity_execution_id=activity_by_actor.get(resident_id),
            action_execution_id=action_by_actor.get(resident_id),
            held_resource_ids=sorted(held.get(resident_id, set())),
            facts=deepcopy(state["facts"]),
        )
        for resident_id, state in sorted(residents.items())
    ]
    return frames, sorted(active_ids)


def _world_state_at(
    trace: ExecutionTrace,
    bundle: SimulationBundle | None,
    at: datetime,
    sources: _FrameSources | None = None,
) -> tuple[dict[str, dict[str, JsonValue]], dict[str, JsonValue]]:
    if sources is not None:
        entity_states = deepcopy(sources.entity_states)
        environment_facts = deepcopy(sources.environment_facts)
        for (subject_type, subject_id, fact), times, transitions in sources.transition_timelines:
            transition = _last_timeline_item(times, transitions, at)
            if transition is None:
                continue
            if subject_type == "entity":
                if fact.startswith(f"{subject_id}."):
                    continue
                _apply_transition(entity_states.setdefault(subject_id, {}), transition)
            elif subject_type == "environment":
                _apply_transition(environment_facts, transition)
        return entity_states, environment_facts
    entity_states = (
        deepcopy(sources.entity_states)
        if sources
        else (
            {item.entity_id: dict(item.initial_state) for item in bundle.home_model.entities}
            if bundle
            else {}
        )
    )
    environment_facts = (
        deepcopy(sources.environment_facts)
        if sources
        else (dict(bundle.scenario.initial_state.environment_facts) if bundle else {})
    )
    if bundle is None and sources is None:
        for transition in sorted(
            trace.state_transitions, key=lambda item: (item.at, item.transition_id)
        ):
            if transition.subject_type == "entity":
                if transition.fact.startswith(f"{transition.subject_id}."):
                    continue
                entity_states.setdefault(transition.subject_id, {}).setdefault(
                    transition.fact, transition.previous_value
                )
            elif transition.subject_type == "environment":
                environment_facts.setdefault(transition.fact, transition.previous_value)
    transitions = (
        sources.transitions[: bisect_right(sources.transition_times, at)]
        if sources
        else sorted(
            (item for item in trace.state_transitions if item.at <= at),
            key=lambda item: (item.at, item.transition_id),
        )
    )
    for transition in transitions:
        if transition.subject_type == "entity":
            if transition.fact.startswith(f"{transition.subject_id}."):
                continue
            _apply_transition(entity_states.setdefault(transition.subject_id, {}), transition)
        elif transition.subject_type == "environment":
            _apply_transition(environment_facts, transition)
    return entity_states, environment_facts


def _resource_state_at(
    trace: ExecutionTrace,
    bundle: SimulationBundle | None,
    at: datetime,
    sources: _FrameSources | None = None,
) -> dict[str, int]:
    if sources is not None:
        resources = deepcopy(sources.resources)
        for resource_id, times, events in sources.resource_availability_timelines:
            event = _last_timeline_item(times, events, at)
            if event is not None:
                resources[resource_id] = event.available_units_after
        return resources
    resources = (
        deepcopy(sources.resources)
        if sources
        else (
            {item.resource_id: item.capacity for item in bundle.scenario.resources}
            if bundle
            else {}
        )
    )
    if bundle is None and sources is None:
        for item in sorted(
            trace.resource_events, key=lambda item: (item.at, item.resource_event_id)
        ):
            if item.resource_id in resources:
                continue
            if item.operation == "acquired":
                resources[item.resource_id] = item.available_units_after + item.units
            elif item.operation == "released":
                resources[item.resource_id] = max(item.available_units_after - item.units, 0)
            else:
                resources[item.resource_id] = item.available_units_after
    events = (
        sources.resource_events[: bisect_right(sources.resource_times, at)]
        if sources
        else sorted(
            (item for item in trace.resource_events if item.at <= at),
            key=lambda item: (item.at, item.resource_event_id),
        )
    )
    for item in events:
        resources[item.resource_id] = item.available_units_after
    return resources


def _sensor_state_at(
    observations: ObservableSensorLog,
    oracle: OracleMapping | None,
    at: datetime,
    include_oracle: bool,
    sensor_timelines: tuple[tuple[str, tuple[datetime, ...], tuple[Any, ...]], ...] | None = None,
) -> list[ReplaySensorFrame]:
    if sensor_timelines is None:
        latest: dict[str, Any] = {}
        for item in observations.records:
            if item.observed_at > at:
                break
            latest[item.sensor_id] = item
    else:
        latest = {}
        for sensor_id, times, records in sensor_timelines:
            position = bisect_right(times, at)
            if position:
                latest[sensor_id] = records[position - 1]
    causes = (
        {item.observation_id: item for item in oracle.links}
        if include_oracle and oracle is not None
        else {}
    )
    changed_after = at - timedelta(milliseconds=500)
    return [
        ReplaySensorFrame(
            observation_id=item.observation_id,
            sensor_id=item.sensor_id,
            sensor_type=item.sensor_type,
            observed_at=item.observed_at,
            measurement=item.measurement,
            value=deepcopy(item.value),
            unit=item.unit,
            quality=item.quality,
            changed=changed_after < item.observed_at <= at,
            oracle_cause=_cause(causes[item.observation_id])
            if include_oracle and item.observation_id in causes
            else None,
        )
        for item in sorted(latest.values(), key=lambda item: item.sensor_id)
    ]


def _frame_sources(trace: ExecutionTrace, bundle: SimulationBundle | None) -> _FrameSources:
    transitions = tuple(
        sorted(trace.state_transitions, key=lambda item: (item.at, item.transition_id))
    )
    activities = tuple(sorted(trace.activity_executions, key=lambda item: item.actual_start))
    actions = tuple(sorted(trace.action_executions, key=lambda item: item.started_at))
    active_activity_times, active_activity_snapshots = _active_interval_snapshots(
        activities,
        start="actual_start",
        end="actual_end",
        identifier="activity_execution_id",
    )
    active_action_times, active_action_snapshots = _active_interval_snapshots(
        actions,
        start="started_at",
        end="ended_at",
        identifier="action_execution_id",
    )
    movements = tuple(sorted(trace.movements, key=lambda item: item.started_at))
    resources = tuple(
        sorted(trace.resource_events, key=lambda item: (item.at, item.resource_event_id))
    )
    residents = _initial_residents(trace, bundle)
    resident_ids = {item.actor_id for item in trace.activity_executions}
    resident_ids.update(item.actor_id for item in trace.action_executions)
    resident_ids.update(item.actor_id for item in trace.movements)
    resident_ids.update(
        item.subject_id for item in trace.state_transitions if item.subject_type == "resident"
    )
    if bundle is None:
        entity_states: dict[str, dict[str, JsonValue]] = {}
        environment_facts: dict[str, JsonValue] = {}
        for transition in transitions:
            if transition.subject_type == "entity" and not transition.fact.startswith(
                f"{transition.subject_id}."
            ):
                entity_states.setdefault(transition.subject_id, {}).setdefault(
                    transition.fact, transition.previous_value
                )
            elif transition.subject_type == "environment":
                environment_facts.setdefault(transition.fact, transition.previous_value)
        capacities: dict[str, int] = {}
        for event in resources:
            if event.resource_id not in capacities:
                if event.operation == "acquired":
                    capacities[event.resource_id] = event.available_units_after + event.units
                elif event.operation == "released":
                    capacities[event.resource_id] = max(
                        event.available_units_after - event.units, 0
                    )
                else:
                    capacities[event.resource_id] = event.available_units_after
    else:
        entity_states = {
            item.entity_id: dict(item.initial_state) for item in bundle.home_model.entities
        }
        environment_facts = dict(bundle.scenario.initial_state.environment_facts)
        capacities = {item.resource_id: item.capacity for item in bundle.scenario.resources}
    transition_groups: dict[tuple[str, str, str], list[StateTransition]] = {}
    for transition in transitions:
        transition_groups.setdefault(
            (transition.subject_type, transition.subject_id, transition.fact), []
        ).append(transition)
    transition_timelines = tuple(
        (
            key,
            tuple(item.at for item in items),
            tuple(items),
        )
        for key, items in sorted(transition_groups.items())
    )
    completed_movement_groups: dict[str, list[MovementExecution]] = {}
    for movement in sorted(trace.movements, key=lambda item: (item.ended_at, item.movement_id)):
        completed_movement_groups.setdefault(movement.actor_id, []).append(movement)
    completed_movement_timelines = tuple(
        (resident_id, tuple(item.ended_at for item in items), tuple(items))
        for resident_id, items in sorted(completed_movement_groups.items())
    )
    active_movement_times, active_movement_snapshots = _active_interval_snapshots(
        movements,
        start="started_at",
        end="ended_at",
        identifier="movement_id",
    )
    resource_groups: dict[tuple[str, str], list[Any]] = {}
    resource_availability_groups: dict[str, list[Any]] = {}
    for event in resources:
        if event.operation in {"acquired", "released", "preempted"}:
            resource_groups.setdefault((event.actor_id, event.resource_id), []).append(event)
        resource_availability_groups.setdefault(event.resource_id, []).append(event)
    resource_timelines = tuple(
        (key, tuple(item.at for item in items), tuple(items))
        for key, items in sorted(resource_groups.items())
    )
    resource_availability_timelines = tuple(
        (resource_id, tuple(item.at for item in items), tuple(items))
        for resource_id, items in sorted(resource_availability_groups.items())
    )
    return _FrameSources(
        residents=residents,
        resident_ids=tuple(sorted(resident_ids)),
        entity_states=entity_states,
        environment_facts=environment_facts,
        resources=capacities,
        activities=activities,
        activity_times=tuple(item.actual_start for item in activities),
        active_activity_times=active_activity_times,
        active_activity_snapshots=active_activity_snapshots,
        actions=actions,
        action_times=tuple(item.started_at for item in actions),
        active_action_times=active_action_times,
        active_action_snapshots=active_action_snapshots,
        movements=movements,
        movement_times=tuple(item.started_at for item in movements),
        transitions=transitions,
        transition_times=tuple(item.at for item in transitions),
        resource_events=resources,
        resource_times=tuple(item.at for item in resources),
        transition_timelines=transition_timelines,
        completed_movement_timelines=completed_movement_timelines,
        active_movement_times=active_movement_times,
        active_movement_snapshots=active_movement_snapshots,
        resource_timelines=resource_timelines,
        resource_availability_timelines=resource_availability_timelines,
    )


def _matches_final_state(frame: ReplayFrame, trace: ExecutionTrace) -> bool:
    expected_residents = {item.resident_id: item for item in trace.final_state.residents}
    actual_residents = {item.resident_id: item for item in frame.residents}
    if expected_residents.keys() != actual_residents.keys():
        return False
    for resident_id, expected in expected_residents.items():
        actual = actual_residents[resident_id]
        if (
            actual.region_id != expected.region_id
            or actual.position != expected.position
            or actual.posture != expected.posture
            or actual.execution_state != expected.execution_state
            or actual.facts != expected.facts
            or actual.held_resource_ids != expected.held_resource_ids
        ):
            return False
    return (
        frame.entity_states == trace.final_state.entity_states
        and frame.environment_facts == trace.final_state.environment_facts
        and frame.resource_available_units == trace.final_state.resource_available_units
    )


class ReplayService:
    def __init__(self, workspace: WorkspaceService) -> None:
        self.workspace = workspace
        # Completed run artifacts are immutable. Cached indexes avoid rehashing large traces
        # for every scrubber seek while preserving a fresh index per service instance.
        self._indices: dict[str, _ReplayIndex] = {}

    def _artifact(self, run_id: str, role: str) -> tuple[Path, str]:
        artifacts = self.workspace.run_artifacts(run_id)
        artifact = artifacts.get(role)
        if artifact is None:
            if not artifacts:
                try:
                    self.workspace.get_job(run_id)
                except WorkspaceError as error:
                    raise WorkspaceError(f"unknown run '{run_id}'") from error
            raise WorkspaceError(f"run '{run_id}' has no '{role}' artifact")
        return self.workspace.artifact_path(artifact.artifact_id), artifact.sha256

    def _index(self, run_id: str) -> _ReplayIndex:
        cached = self._indices.get(run_id)
        if cached is not None:
            return cached
        trace_path, trace_digest = self._artifact(run_id, "execution_trace")
        observations_path, observations_digest = self._artifact(run_id, "observable_sensor_log")
        artifacts = self.workspace.run_artifacts(run_id)
        oracle_artifact = artifacts.get("oracle_mapping")
        bundle_artifact = artifacts.get("simulation_bundle")
        scenario_artifact = artifacts.get("scenario")
        oracle_path = (
            str(self.workspace.artifact_path(oracle_artifact.artifact_id))
            if oracle_artifact is not None
            else None
        )
        bundle_path = (
            str(self.workspace.artifact_path(bundle_artifact.artifact_id))
            if bundle_artifact is not None
            else None
        )
        scenario_path = (
            str(self.workspace.artifact_path(scenario_artifact.artifact_id))
            if scenario_artifact is not None
            else None
        )
        index = _replay_index(
            str(trace_path),
            trace_digest,
            str(observations_path),
            observations_digest,
            oracle_path,
            oracle_artifact.sha256 if oracle_artifact is not None else None,
            bundle_path,
            bundle_artifact.sha256 if bundle_artifact is not None else None,
            scenario_path,
            scenario_artifact.sha256 if scenario_artifact is not None else None,
        )
        self._indices[run_id] = index
        return index

    def events(
        self,
        run_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        kinds: set[ReplayEventKind] | None = None,
        statuses: set[str] | None = None,
        actor_id: str | None = None,
        sensor_id: str | None = None,
        include_oracle: bool = False,
        limit: int = 2_000,
    ) -> ReplayEventWindow:
        if actor_id is not None and not include_oracle:
            raise ValueError("replay actor filter requires include_oracle=True")
        index = self._index(run_id)
        window_start = max(start or index.trace_start, index.trace_start)
        window_end = min(end or index.trace_end, index.trace_end)
        left = bisect_left(index.event_times, window_start)
        right = bisect_right(index.event_times, window_end)
        selected = [
            item
            for item in index.events[left:right]
            if (kinds is None or item.kind in kinds)
            and (statuses is None or item.status in statuses)
            and (actor_id is None or item.actor_id == actor_id)
            and (sensor_id is None or item.sensor_id == sensor_id)
        ]
        bounded = max(1, min(limit, 5_000))
        visible = selected[:bounded]
        if include_oracle:
            oracle_links = (
                {item.observation_id: item for item in index.oracle.links}
                if index.oracle is not None
                else None
            )
            visible = [_with_oracle(item, oracle_links) for item in visible]
        else:
            visible = [_without_oracle(item) for item in visible]
        return ReplayEventWindow(
            items=deepcopy(visible),
            total=len(selected),
            trace_start=index.trace_start,
            trace_end=index.trace_end,
            window_start=window_start,
            window_end=window_end,
        )

    def frame(
        self,
        run_id: str,
        *,
        at: datetime,
        include_oracle: bool = False,
    ) -> ReplayFrame:
        index = self._index(run_id)
        instant = min(max(at, index.trace_start), index.trace_end)
        residents, active_ids = _resident_frames(
            index.trace, index.bundle, instant, index.frame_sources
        )
        entity_states, environment_facts = _world_state_at(
            index.trace, index.bundle, instant, index.frame_sources
        )
        resources = _resource_state_at(index.trace, index.bundle, instant, index.frame_sources)
        sensors = _sensor_state_at(
            index.observations,
            index.oracle,
            instant,
            include_oracle,
            index.sensor_timelines,
        )
        frame = ReplayFrame(
            run_id=run_id,
            at=instant,
            trace_start=index.trace_start,
            trace_end=index.trace_end,
            residents=residents,
            sensor_states=sensors,
            entity_states=entity_states,
            environment_facts=environment_facts,
            resource_available_units=resources,
            active_event_ids=active_ids,
        )
        if instant == index.trace_end and not _matches_final_state(frame, index.trace):
            raise WorkspaceError("reconstructed replay frame does not match the trace final state")
        return frame.model_copy(deep=True)

    def verify(self, run_id: str) -> ReplayVerification:
        trace_path, _ = self._artifact(run_id, "execution_trace")
        artifacts = self.workspace.run_artifacts(run_id)
        if "simulation_bundle" in artifacts:
            report = replay_files(self._artifact(run_id, "simulation_bundle")[0], trace_path)
            matches = report.matches
            expected = report.expected_semantic_digest
            actual = report.actual_semantic_digest
        else:
            # A merged horizon run cannot be re-executed from one bundle; its published content is
            # verified against its own authoritative digest and its per-day source digests.
            matches, expected, actual = verify_horizon(
                trace_path, self._artifact(run_id, "horizon_manifest")[0]
            )
        verification = ReplayVerification(
            run_id=run_id,
            verified_at=utc_now(),
            matches=matches,
            expected_semantic_digest=expected,
            actual_semantic_digest=actual,
        )
        if verification.matches and not self.workspace.diagnostic_mode:
            self.workspace.save_replay_session(
                run_id,
                verified_digest=verification.actual_semantic_digest,
            )
        return verification

    def diary(
        self,
        run_id: str,
        *,
        actor_id: str | None = None,
        status: str | None = None,
        query: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[DiaryEntry], int]:
        trace_path, trace_sha = self._artifact(run_id, "execution_trace")
        trace = _trace(str(trace_path), trace_sha)
        actions = {item.action_execution_id: item for item in trace.action_executions}
        movement_by_action: dict[str, list[str]] = {}
        for movement in trace.movements:
            movement_by_action.setdefault(movement.action_execution_id, []).append(
                movement.movement_id
            )
        entries: list[DiaryEntry] = []
        normalized_query = query.casefold().strip()
        for activity in trace.activity_executions:
            if actor_id and activity.actor_id != actor_id:
                continue
            if status and activity.status != status:
                continue
            if normalized_query and normalized_query not in (
                f"{activity.intent} {activity.actor_id} {activity.source_activity_id}".casefold()
            ):
                continue
            activity_actions = [actions[item] for item in activity.action_execution_ids]
            entries.append(
                DiaryEntry(
                    activity_execution_id=activity.activity_execution_id,
                    source_activity_id=activity.source_activity_id,
                    actor_id=activity.actor_id,
                    intent=activity.intent,
                    process_model_id=activity.process_model_id,
                    planned_start=activity.planned_start,
                    planned_end=activity.planned_end,
                    actual_start=activity.actual_start,
                    actual_end=activity.actual_end,
                    status=activity.status,
                    actions=[
                        DiaryAction(
                            action_execution_id=action.action_execution_id,
                            node_id=action.node_id,
                            action_type=action.action_type,
                            started_at=action.started_at,
                            ended_at=action.ended_at,
                            status=action.status,
                            provider_ids=action.provider_ids,
                        )
                        for action in activity_actions
                    ],
                    movement_ids=[
                        movement_id
                        for action in activity_actions
                        for movement_id in movement_by_action.get(action.action_execution_id, [])
                    ],
                    deviation_ids=activity.deviation_ids,
                    trace_id=trace.trace_id,
                    trace_semantic_digest=trace.semantic_digest,
                )
            )
        entries.sort(key=lambda item: (item.actual_start, item.activity_execution_id))
        total = len(entries)
        offset = max(offset, 0)
        limit = max(1, min(limit, 500))
        return entries[offset : offset + limit], total

    def profile(self, run_id: str, *, slot_minutes: int = DEFAULT_SLOT_MINUTES) -> ResidentProfile:
        """What this run's residents are like, aggregated from its execution trace."""
        trace_path, trace_sha = self._artifact(run_id, "execution_trace")
        return _profile(str(trace_path), trace_sha, run_id, slot_minutes)

    def observations(
        self,
        run_id: str,
        *,
        include_oracle: bool = False,
        sensor_id: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[ObservationView], int]:
        log_path, log_sha = self._artifact(run_id, "observable_sensor_log")
        log = _observations(str(log_path), log_sha)
        links = {}
        if include_oracle:
            oracle_path, oracle_sha = self._artifact(run_id, "oracle_mapping")
            mapping = _oracle(str(oracle_path), oracle_sha)
            links = {item.observation_id: item for item in mapping.links}
        records = [item for item in log.records if sensor_id is None or item.sensor_id == sensor_id]
        total = len(records)
        offset = max(offset, 0)
        limit = max(1, min(limit, 1000))
        result = []
        for record in records[offset : offset + limit]:
            link = links.get(record.observation_id)
            cause = None
            if link is not None:
                cause = ObservationCause(
                    origin=link.origin,
                    cause_type=link.cause_type,
                    cause_ids=link.cause_ids,
                    resident_ids=link.resident_ids,
                    activity_execution_ids=link.activity_execution_ids,
                    action_execution_ids=link.action_execution_ids,
                )
            result.append(
                ObservationView(
                    observation_id=record.observation_id,
                    sensor_id=record.sensor_id,
                    sensor_type=record.sensor_type,
                    observed_at=record.observed_at,
                    measurement=record.measurement,
                    value=record.value,
                    unit=record.unit,
                    quality=record.quality,
                    oracle_cause=cause,
                )
            )
        return result, total

    def _trace_timeline(
        self,
        run_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        include_oracle: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        trace_path, trace_sha = self._artifact(run_id, "execution_trace")
        trace = _trace(str(trace_path), trace_sha)
        events: list[dict[str, Any]] = []

        def accepted(at: datetime) -> bool:
            return (start is None or at >= start) and (end is None or at <= end)

        def add(
            *,
            at: datetime,
            kind: ReplayEventKind,
            event_id: str,
            actor_id: str,
            label: str,
            status: str,
            end_at: datetime,
            waypoints: list[dict[str, Any]] | None = None,
        ) -> None:
            if not accepted(at):
                return
            item: dict[str, Any] = {
                "at": at.isoformat(),
                "kind": kind,
                "id": event_id if include_oracle else _opaque_replay_id(kind, event_id),
                "label": label,
                "status": status,
                "end": end_at.isoformat(),
            }
            if include_oracle:
                item["actorId"] = actor_id
            if waypoints is not None:
                item["waypoints"] = waypoints
            events.append(item)

        for activity in trace.activity_executions:
            add(
                at=activity.actual_start,
                kind="activity",
                event_id=activity.activity_execution_id,
                actor_id=activity.actor_id,
                label=activity.intent,
                status=activity.status,
                end_at=activity.actual_end,
            )
        for action in trace.action_executions:
            add(
                at=action.started_at,
                kind="action",
                event_id=action.action_execution_id,
                actor_id=action.actor_id,
                label=action.action_type,
                status=action.status,
                end_at=action.ended_at,
            )
        for movement in trace.movements:
            add(
                at=movement.started_at,
                kind="movement",
                event_id=movement.movement_id,
                actor_id=movement.actor_id,
                label=f"{movement.origin_region_id} → {movement.destination_region_id}",
                status="completed",
                end_at=movement.ended_at,
                waypoints=[
                    item.model_dump(mode="json", by_alias=True) for item in movement.waypoints
                ],
            )
        events.sort(key=lambda item: (item["at"], item["kind"], item["id"]))
        return events[: max(1, min(limit, 5_000))]

    def timeline(
        self,
        run_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        include_oracle: bool = False,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        if "observable_sensor_log" not in self.workspace.run_artifacts(run_id):
            return self._trace_timeline(
                run_id,
                start=start,
                end=end,
                include_oracle=include_oracle,
                limit=limit,
            )
        window = self.events(
            run_id,
            start=start,
            end=end,
            kinds={"activity", "action", "movement"},
            include_oracle=include_oracle,
            limit=limit,
        )
        events: list[dict[str, Any]] = []
        for event in window.items:
            item: dict[str, Any] = {
                "at": event.at.isoformat(),
                "kind": event.kind,
                "id": event.event_id,
                "label": event.label,
                "status": event.status,
                "end": event.end.isoformat() if event.end else None,
            }
            if include_oracle:
                item["actorId"] = event.actor_id
            if event.kind == "movement":
                item["waypoints"] = [
                    waypoint.model_dump(mode="json", by_alias=True) for waypoint in event.waypoints
                ]
            events.append(item)
        events.sort(key=lambda item: (item["at"], item["kind"], item["id"]))
        return events
