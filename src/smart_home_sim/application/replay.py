from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any

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
class _ReplayIndex:
    trace_start: datetime
    trace_end: datetime
    events: tuple[ReplayEventView, ...]
    event_times: tuple[datetime, ...]
    trace: ExecutionTrace
    observations: ObservableSensorLog
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


def _events(
    trace: ExecutionTrace,
    observations: ObservableSensorLog,
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


@lru_cache(maxsize=8)
def _replay_index(
    trace_path: str,
    trace_digest: str,
    observations_path: str,
    observations_digest: str,
    oracle_path: str | None,
    oracle_digest: str | None,
    bundle_path: str | None,
    bundle_digest: str | None,
) -> _ReplayIndex:
    trace = _trace(trace_path, trace_digest)
    observations = _observations(observations_path, observations_digest)
    oracle = _oracle(oracle_path, oracle_digest or "") if oracle_path else None
    bundle = _bundle(bundle_path, bundle_digest or "") if bundle_path else None
    events = _events(trace, observations)
    return _ReplayIndex(
        trace_start=trace.started_at,
        trace_end=trace.ended_at,
        events=events,
        event_times=tuple(item.at for item in events),
        trace=trace,
        observations=observations,
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


def _with_oracle(
    item: ReplayEventView, oracle_links: Mapping[str, Any] | None
) -> ReplayEventView:
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
                transition.fact in {"posture", "execution_state"}
                and transition.fact not in seeded
            ):
                state[transition.fact] = transition.previous_value or "idle"
                seeded.add(transition.fact)
            else:
                state["facts"].setdefault(transition.fact, transition.previous_value)
        return residents
    points = {
        item.interaction_point_id: item for item in bundle.home_model.interaction_points
    }
    bindings = {
        item.scenario_location_id: item for item in bundle.home_model.location_bindings
    }
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
    trace: ExecutionTrace, bundle: SimulationBundle | None, at: datetime
) -> tuple[list[ReplayResidentFrame], list[str]]:
    residents = _initial_residents(trace, bundle)
    resident_ids = {item.actor_id for item in trace.activity_executions}
    resident_ids.update(item.actor_id for item in trace.action_executions)
    resident_ids.update(item.actor_id for item in trace.movements)
    resident_ids.update(
        item.subject_id
        for item in trace.state_transitions
        if item.subject_type == "resident"
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
    for transition in sorted(
        (
            item
            for item in trace.state_transitions
            if item.subject_type == "resident" and item.at <= at
        ),
        key=lambda item: (item.at, item.transition_id),
    ):
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
    active_activities = [
        item for item in trace.activity_executions if item.actual_start <= at < item.actual_end
    ]
    active_actions = [
        item for item in trace.action_executions if item.started_at <= at < item.ended_at
    ]
    active_ids = {
        item.activity_execution_id for item in active_activities
    } | {item.action_execution_id for item in active_actions}
    spatial_updates: list[tuple[datetime, int, str, str, Any]] = [
        (item.at, 1, item.transition_id, "transition", item)
        for item in trace.state_transitions
        if item.subject_type == "resident"
        and item.fact in {"location", "position"}
        and item.at <= at
    ]
    for movement in sorted(trace.movements, key=lambda item: (item.ended_at, item.movement_id)):
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
    for event in sorted(
        (item for item in trace.resource_events if item.at <= at),
        key=lambda item: (item.at, item.resource_event_id),
    ):
        if event.actor_id not in held:
            held[event.actor_id] = set()
        if event.operation == "acquired":
            held[event.actor_id].add(event.resource_id)
        elif event.operation in {"released", "preempted"}:
            held[event.actor_id].discard(event.resource_id)
    activity_by_actor = {item.actor_id: item.activity_execution_id for item in active_activities}
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
            activity_execution_id=activity_by_actor.get(resident_id),
            action_execution_id=action_by_actor.get(resident_id),
            held_resource_ids=sorted(held.get(resident_id, set())),
            facts=deepcopy(state["facts"]),
        )
        for resident_id, state in sorted(residents.items())
    ]
    return frames, sorted(active_ids)


def _world_state_at(
    trace: ExecutionTrace, bundle: SimulationBundle | None, at: datetime
) -> tuple[dict[str, dict[str, JsonValue]], dict[str, JsonValue]]:
    entity_states = (
        {item.entity_id: dict(item.initial_state) for item in bundle.home_model.entities}
        if bundle
        else {}
    )
    environment_facts = dict(bundle.scenario.initial_state.environment_facts) if bundle else {}
    if bundle is None:
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
    for transition in sorted(
        (item for item in trace.state_transitions if item.at <= at),
        key=lambda item: (item.at, item.transition_id),
    ):
        if transition.subject_type == "entity":
            if transition.fact.startswith(f"{transition.subject_id}."):
                continue
            _apply_transition(entity_states.setdefault(transition.subject_id, {}), transition)
        elif transition.subject_type == "environment":
            _apply_transition(environment_facts, transition)
    return entity_states, environment_facts


def _resource_state_at(
    trace: ExecutionTrace, bundle: SimulationBundle | None, at: datetime
) -> dict[str, int]:
    resources = (
        {item.resource_id: item.capacity for item in bundle.scenario.resources} if bundle else {}
    )
    if bundle is None:
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
    for item in sorted(
        (item for item in trace.resource_events if item.at <= at),
        key=lambda item: (item.at, item.resource_event_id),
    ):
        resources[item.resource_id] = item.available_units_after
    return resources


def _sensor_state_at(
    observations: ObservableSensorLog,
    oracle: OracleMapping | None,
    at: datetime,
    include_oracle: bool,
) -> list[ReplaySensorFrame]:
    latest: dict[str, Any] = {}
    for item in observations.records:
        if item.observed_at > at:
            break
        latest[item.sensor_id] = item
    causes = {item.observation_id: item for item in oracle.links} if oracle else {}
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
        trace_path, trace_digest = self._artifact(run_id, "execution_trace")
        observations_path, observations_digest = self._artifact(run_id, "observable_sensor_log")
        artifacts = self.workspace.run_artifacts(run_id)
        oracle_artifact = artifacts.get("oracle_mapping")
        bundle_artifact = artifacts.get("simulation_bundle")
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
        return _replay_index(
            str(trace_path),
            trace_digest,
            str(observations_path),
            observations_digest,
            oracle_path,
            oracle_artifact.sha256 if oracle_artifact is not None else None,
            bundle_path,
            bundle_artifact.sha256 if bundle_artifact is not None else None,
        )

    def events(
        self,
        run_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        kinds: set[ReplayEventKind] | None = None,
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
        residents, active_ids = _resident_frames(index.trace, index.bundle, instant)
        entity_states, environment_facts = _world_state_at(index.trace, index.bundle, instant)
        resources = _resource_state_at(index.trace, index.bundle, instant)
        sensors = _sensor_state_at(index.observations, index.oracle, instant, include_oracle)
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
