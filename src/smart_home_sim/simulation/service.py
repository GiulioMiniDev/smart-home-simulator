from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import simpy
from pydantic import JsonValue, ValidationError
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon

from smart_home_sim.behavior.service import (
    _condition_matches,
    default_action_catalog_path,
    default_variable_catalog_path,
)
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    EffectOperation,
    ProcessEdge,
    ProcessModel,
    ProcessNode,
    ProcessNodeKind,
    VariableCatalog,
    VariableCondition,
)
from smart_home_sim.domain.environment import Point2D, ResolvedActionBinding, SimulationBundle
from smart_home_sim.domain.execution import (
    ActionExecution,
    ActivityExecution,
    DailyExecutionSummary,
    ExecutionTrace,
    FinalWorldState,
    MovementExecution,
    PlanDeviation,
    ReplayReport,
    ResidentFinalState,
    ResourceEvent,
    RuntimeEventExecution,
    SimulationIssue,
    SimulationReport,
    SimulationResult,
    SimulationSummary,
    StateTransition,
    TraceCausality,
    TrajectoryWaypoint,
)
from smart_home_sim.domain.models import (
    Condition,
    ConditionOperator,
    RuntimeEventOperation,
    StateEffect,
)
from smart_home_sim.domain.plan import CanonicalActivity
from smart_home_sim.environment.navigation import NavigationPath, plan_path
from smart_home_sim.validation.service import (
    MAX_SCENARIO_BYTES,
    DuplicateJsonKeyError,
    InvalidJsonConstantError,
    _exceeds_json_nesting_limit,
    _json_path,
    _reject_duplicate_keys,
    _reject_non_finite_constant,
)

SUPPORTED_BUNDLE_VERSION = "1.0.0"
MINUTE_US = 60_000_000


class SimulationFailure(RuntimeError):
    def __init__(self, code: str, message: str, path: str = "$") -> None:
        super().__init__(code, message, path)
        self.code = code
        self.message = message
        self.path = path

    def __str__(self) -> str:
        return self.message


class NamedRandomStreams:
    """Independent deterministic random streams derived from a bundle seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._streams: dict[str, random.Random] = {}

    def stream(self, name: str) -> random.Random:
        if name not in self._streams:
            material = f"{self.seed}:sha256-named-streams-1.0.0:{name}".encode()
            derived = int.from_bytes(hashlib.sha256(material).digest()[:16], "big")
            self._streams[name] = random.Random(derived)
        return self._streams[name]


@dataclass
class ResidentRuntime:
    resident_id: str
    region_id: str
    position: Point2D
    posture: str = "standing"
    execution_state: str = "idle"
    facts: dict[str, JsonValue] = field(default_factory=dict)
    held_resources: set[str] = field(default_factory=set)


@dataclass
class RuntimeState:
    residents: dict[str, ResidentRuntime]
    entity_states: dict[str, dict[str, JsonValue]]
    environment_facts: dict[str, JsonValue]
    capability_facts: dict[str, JsonValue]
    invalidated_facts: set[str] = field(default_factory=set)
    completed_activities: set[str] = field(default_factory=set)


@dataclass
class PreparedEvent:
    event_id: str
    occurred: bool
    at_us: int
    amounts: list[float]


@dataclass
class ResourceAllocation:
    allocation_id: str
    activity_id: str
    actor_id: str
    priority: int
    requirements: dict[str, int]
    process: simpy.events.Process
    active: bool = False


class ResourceCoordinator:
    """Atomic multi-resource capacity manager with priority pre-emption."""

    def __init__(self, env: simpy.Environment, capacities: dict[str, int]) -> None:
        self.env = env
        self.capacities = capacities
        self.allocations: dict[str, ResourceAllocation] = {}
        self.waiters: list[tuple[int, int, ResourceAllocation, simpy.Event]] = []
        self._sequence = 0

    def available(self, resource_id: str) -> int:
        used = sum(
            allocation.requirements.get(resource_id, 0)
            for allocation in self.allocations.values()
            if allocation.active
        )
        return self.capacities[resource_id] - used

    def _fits(self, requirements: dict[str, int]) -> bool:
        return all(self.available(key) >= units for key, units in requirements.items())

    def _grant(self, allocation: ResourceAllocation, event: simpy.Event) -> None:
        allocation.active = True
        self.allocations[allocation.allocation_id] = allocation
        event.succeed(allocation)

    def request(
        self,
        *,
        allocation_id: str,
        activity_id: str,
        actor_id: str,
        priority: int,
        requirements: dict[str, int],
    ) -> simpy.Event:
        process = self.env.active_process
        if process is None:
            raise RuntimeError("resource requests require an active simulation process")
        event = self.env.event()
        allocation = ResourceAllocation(
            allocation_id=allocation_id,
            activity_id=activity_id,
            actor_id=actor_id,
            priority=priority,
            requirements=requirements,
            process=process,
        )
        if self._fits(requirements):
            self._grant(allocation, event)
            return event
        candidates = sorted(
            (
                item
                for item in self.allocations.values()
                if item.active
                and item.priority < priority
                and any(key in item.requirements for key in requirements)
            ),
            key=lambda item: (item.priority, item.allocation_id),
        )
        recoverable = {
            key: self.available(key) + sum(item.requirements.get(key, 0) for item in candidates)
            for key in requirements
        }
        if all(recoverable[key] >= units for key, units in requirements.items()):
            for victim in candidates:
                victim.active = False
                victim.process.interrupt(
                    {
                        "kind": "resource_preemption",
                        "allocation_id": victim.allocation_id,
                        "resource_ids": sorted(victim.requirements),
                    }
                )
                if self._fits(requirements):
                    break
            self._grant(allocation, event)
            return event
        self._sequence += 1
        self.waiters.append((-priority, self._sequence, allocation, event))
        self.waiters.sort(key=lambda item: (item[0], item[1]))
        return event

    def release(self, allocation: ResourceAllocation) -> None:
        allocation.active = False
        self.allocations.pop(allocation.allocation_id, None)
        remaining: list[tuple[int, int, ResourceAllocation, simpy.Event]] = []
        for priority, sequence, waiter, event in self.waiters:
            if not event.triggered and self._fits(waiter.requirements):
                self._grant(waiter, event)
            else:
                remaining.append((priority, sequence, waiter, event))
        self.waiters = remaining


class TraceCollector:
    def __init__(self) -> None:
        self.activities: list[ActivityExecution] = []
        self.actions: list[ActionExecution] = []
        self.movements: list[MovementExecution] = []
        self.transitions: list[StateTransition] = []
        self.resources: list[ResourceEvent] = []
        self.runtime_events: list[RuntimeEventExecution] = []
        self.deviations: list[PlanDeviation] = []

    def identifier(self, kind: str, values: Iterable[Any]) -> str:
        payload = ":".join(str(value) for value in values)
        return f"{kind}_{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def _at(origin: datetime, microseconds: int | float) -> datetime:
    return origin + timedelta(microseconds=int(round(microseconds)))


def _offset(origin: datetime, value: datetime) -> int:
    return int(round((value - origin).total_seconds() * 1_000_000))


def _point_for_location(bundle: SimulationBundle, location_id: str) -> tuple[str, Point2D]:
    binding = next(
        item
        for item in bundle.home_model.location_bindings
        if item.scenario_location_id == location_id
    )
    point = next(
        item
        for item in bundle.home_model.interaction_points
        if item.interaction_point_id == binding.anchor_interaction_point_id
    )
    return point.region_id, point.position


def _initial_runtime(bundle: SimulationBundle) -> RuntimeState:
    residents: dict[str, ResidentRuntime] = {}
    for initial in bundle.scenario.initial_state.residents:
        region_id, position = _point_for_location(bundle, initial.location_id)
        facts = dict(initial.facts)
        facts.setdefault("at_home", not initial.location_id.startswith("outside"))
        residents[initial.resident_id] = ResidentRuntime(
            resident_id=initial.resident_id,
            region_id=region_id,
            position=position,
            posture="lying" if not bool(facts.get("awake", True)) else "standing",
            facts=facts,
        )
    entity_states = {
        entity.entity_id: dict(entity.initial_state) for entity in bundle.home_model.entities
    }
    capabilities: dict[str, JsonValue] = {}
    for entity in bundle.home_model.entities:
        for capability in entity.capabilities:
            for role in capability.roles:
                capabilities[f"{entity.entity_id}.{role}.available"] = True
                capabilities[f"{entity.entity_id}.{role}.consumed"] = 0
    return RuntimeState(
        residents=residents,
        entity_states=entity_states,
        environment_facts=dict(bundle.scenario.initial_state.environment_facts),
        capability_facts=capabilities,
    )


def _nested(source: Any, path: str) -> tuple[bool, Any]:
    current = source
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _known_scenario_fact(
    state: RuntimeState,
    actor_id: str,
    fact: str,
    *,
    day_facts: dict[str, JsonValue] | None = None,
) -> tuple[bool, Any]:
    if fact in state.invalidated_facts:
        return True, False
    resident = state.residents[actor_id]
    aliases = {
        "resident_awake": "awake",
        "resident_at_home": "at_home",
        "medication_available": "medicationAvailableDoses",
    }
    if fact in aliases:
        present, value = _nested(resident.facts, aliases[fact])
        if fact == "medication_available" and present:
            return True, bool(isinstance(value, (int, float)) and value > 0)
        return present, value
    if fact == "leftover_dinner_portion_available":
        present, value = _nested(resident.facts, "foodInventory.leftoverDinnerPortions")
        return (True, bool(value and isinstance(value, (int, float)))) if present else (False, None)
    if fact.startswith("pending_task_"):
        present, tasks = _nested(resident.facts, "pendingTasks")
        return (True, fact.removeprefix("pending_task_") in tasks) if present else (False, None)
    if fact.endswith("_executed"):
        return True, fact.removesuffix("_executed") in state.completed_activities
    if fact == "weather_is_dry" and day_facts is not None:
        weather = day_facts.get("weather")
        return (
            True,
            isinstance(weather, str) and ("dry" in weather or "sunny" in weather),
        )
    if fact == "heavy_rain_has_stopped" and day_facts is not None:
        weather = day_facts.get("weather")
        return True, isinstance(weather, str) and "then_dry" in weather
    if fact == "resident_away_from_home_with_purchases":
        carrying = resident.facts.get("carrying.purchases") is True
        return True, resident.facts.get("at_home") is False and carrying
    if day_facts is not None and fact in day_facts:
        return True, day_facts[fact]
    if fact in state.environment_facts:
        return True, state.environment_facts[fact]
    return False, None


def _operator_matches(operator: ConditionOperator, present: bool, actual: Any, value: Any) -> bool:
    if operator is ConditionOperator.exists:
        return present
    if operator is ConditionOperator.not_exists:
        return not present
    if not present:
        return False
    if operator is ConditionOperator.truthy:
        return bool(actual)
    if operator is ConditionOperator.falsy:
        return not bool(actual)
    if operator is ConditionOperator.eq:
        return actual == value
    if operator is ConditionOperator.ne:
        return actual != value
    if operator is ConditionOperator.gt:
        return actual > value
    if operator is ConditionOperator.gte:
        return actual >= value
    if operator is ConditionOperator.lt:
        return actual < value
    if operator is ConditionOperator.lte:
        return actual <= value
    if operator is ConditionOperator.in_:
        return actual in value
    return actual not in value


def _scenario_condition(
    condition: Condition,
    state: RuntimeState,
    actor_id: str,
    day_facts: dict[str, JsonValue],
    *,
    unknown_is_true: bool = False,
) -> bool:
    present, actual = _known_scenario_fact(state, actor_id, condition.fact, day_facts=day_facts)
    if not present and unknown_is_true:
        return True
    return _operator_matches(condition.operator, present, actual, condition.value)


def _variable_value(
    condition: VariableCondition,
    state: RuntimeState,
    actor_id: str,
    day: Any,
    bundle: SimulationBundle,
    variable_catalog: VariableCatalog,
) -> tuple[bool, Any]:
    definition = next(
        (item for item in variable_catalog.variables if item.variable_id == condition.variable_id),
        None,
    )
    if definition is None:
        return False, None
    if condition.variable_id.startswith("resident."):
        path = condition.variable_id.removeprefix("resident.")
        return _nested(state.residents[actor_id].facts, path)
    if condition.variable_id == "calendar.weekday":
        return True, day.date.weekday()
    if condition.variable_id == "calendar.season":
        month = day.date.month
        return True, (
            "winter"
            if month in {12, 1, 2}
            else "spring"
            if month in {3, 4, 5}
            else "summer"
            if month in {6, 7, 8}
            else "autumn"
        )
    if definition.source_path:
        resident = next(item for item in bundle.scenario.residents if item.resident_id == actor_id)
        if definition.scope.value == "resident":
            return _nested(resident.profile, definition.source_path)
        if definition.scope.value == "day":
            return _nested(
                day.context.model_dump(mode="python", by_alias=True), definition.source_path
            )
        return _nested(state.residents[actor_id].facts, definition.source_path)
    return False, None


def _variable_condition(
    condition: VariableCondition,
    state: RuntimeState,
    actor_id: str,
    day: Any,
    bundle: SimulationBundle,
    variable_catalog: VariableCatalog,
) -> bool:
    present, actual = _variable_value(condition, state, actor_id, day, bundle, variable_catalog)
    return _condition_matches(condition, present, actual)


def _reachable(start: str, outgoing: dict[str, list[ProcessEdge]]) -> set[str]:
    result: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        pending.extend(edge.target_node_id for edge in outgoing[current])
    return result


def _expand_process(
    model: ProcessModel,
    state: RuntimeState,
    actor_id: str,
    day: Any,
    bundle: SimulationBundle,
    variable_catalog: VariableCatalog,
) -> list[list[ProcessNode]]:
    nodes = {item.node_id: item for item in model.nodes}
    outgoing: dict[str, list[ProcessEdge]] = defaultdict(list)
    for edge in model.edges:
        outgoing[edge.source_node_id].append(edge)
    starts = [node for node in model.nodes if node.kind is ProcessNodeKind.start]
    loop_counts: Counter[str] = Counter()

    def select_edge(node: ProcessNode) -> ProcessEdge:
        edges = outgoing[node.node_id]
        if node.kind in {ProcessNodeKind.choice, ProcessNodeKind.loop}:
            if node.kind is ProcessNodeKind.loop and loop_counts[node.node_id] >= (
                node.max_iterations or 0
            ):
                return next(edge for edge in edges if edge.is_default)
            selected = next(
                (
                    edge
                    for edge in edges
                    if edge.condition is not None
                    and _variable_condition(
                        edge.condition, state, actor_id, day, bundle, variable_catalog
                    )
                ),
                None,
            )
            if selected is not None:
                if node.kind is ProcessNodeKind.loop:
                    loop_counts[node.node_id] += 1
                return selected
            return next(edge for edge in edges if edge.is_default)
        if len(edges) != 1:
            raise SimulationFailure(
                "PROCESS_EXECUTION_FAILED",
                f"Node '{node.node_id}' does not have one deterministic successor.",
            )
        return edges[0]

    def walk(node_id: str, stop: str | None = None) -> list[list[ProcessNode]]:
        phases: list[list[ProcessNode]] = []
        steps = 0
        while node_id != stop:
            steps += 1
            if steps > len(nodes) * 20:
                raise SimulationFailure(
                    "PROCESS_EXECUTION_FAILED", "Process traversal did not terminate."
                )
            node = nodes[node_id]
            if node.kind is ProcessNodeKind.end:
                break
            if node.kind is ProcessNodeKind.action:
                phases.append([node])
                node_id = select_edge(node).target_node_id
                continue
            if node.kind is ProcessNodeKind.parallel_split:
                branch_starts = [edge.target_node_id for edge in outgoing[node.node_id]]
                common = set.intersection(*(_reachable(item, outgoing) for item in branch_starts))
                joins = sorted(
                    item for item in common if nodes[item].kind is ProcessNodeKind.parallel_join
                )
                if not joins:
                    raise SimulationFailure(
                        "PROCESS_EXECUTION_FAILED", f"Parallel split '{node.node_id}' has no join."
                    )
                join = joins[0]
                branches = [walk(item, join) for item in branch_starts]
                for index in range(max(len(branch) for branch in branches)):
                    phase = [branch[index][0] for branch in branches if index < len(branch)]
                    phases.append(phase)
                node_id = select_edge(nodes[join]).target_node_id
                continue
            node_id = select_edge(node).target_node_id
        return phases

    return walk(select_edge(starts[0]).target_node_id)


def _semantic_digest(payload: dict[str, Any]) -> str:
    semantic = {
        key: payload[key]
        for key in (
            "sourceBundleId",
            "seed",
            "activityExecutions",
            "actionExecutions",
            "movements",
            "stateTransitions",
            "resourceEvents",
            "runtimeEvents",
            "planDeviations",
            "finalState",
        )
    }
    encoded = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class SimulationEngine:
    def __init__(self, bundle: SimulationBundle) -> None:
        self.bundle = bundle
        self.origin = bundle.scenario.simulation_window.start
        self.env = simpy.Environment(initial_time=0)
        self.streams = NamedRandomStreams(bundle.seed)
        self.state = _initial_runtime(bundle)
        self.trace = TraceCollector()
        self.action_catalog = ActionCatalog.model_validate_json(
            default_action_catalog_path(
                bundle.behavior_package.catalogs.action_catalog.version
            ).read_text(encoding="utf-8")
        )
        self.variable_catalog = VariableCatalog.model_validate_json(
            default_variable_catalog_path().read_text(encoding="utf-8")
        )
        self.action_definitions = {item.action_type: item for item in self.action_catalog.actions}
        self.models = {
            item.process_model_id: item for item in bundle.behavior_package.process_models
        }
        self.bindings = {
            (item.source_activity_id, item.node_id): item for item in bundle.action_bindings
        }
        self.kinematics = {item.resident_id: item for item in bundle.resident_kinematics}
        self.actor_locks = {
            item.resident_id: simpy.Resource(self.env, capacity=1)
            for item in bundle.scenario.residents
        }
        self.resource_capacities = {
            item.resource_id: item.capacity for item in bundle.scenario.resources
        }
        self.resource_coordinator = ResourceCoordinator(self.env, self.resource_capacities)
        self.active_processes: dict[str, simpy.events.Process] = {}
        self.activity_start_events = {
            candidate.trigger_activity_id: self.env.event()
            for candidate in bundle.scenario.runtime_event_candidates
            if candidate.trigger_activity_id is not None
        }
        self.delay_us: defaultdict[str, int] = defaultdict(int)
        self.extension_us: defaultdict[str, int] = defaultdict(int)
        self.prepared_events: dict[str, PreparedEvent] = {}
        self.replacement_deviations: dict[str, tuple[str, str]] = {}
        self._prepare_events()

    def _prepare_events(self) -> None:
        for candidate in self.bundle.scenario.runtime_event_candidates:
            occurrence_rng = self.streams.stream(f"runtime-event-occurrence:{candidate.event_id}")
            occurred = occurrence_rng.random() < candidate.occurrence_probability
            time_rng = self.streams.stream(f"runtime-event-time:{candidate.event_id}")
            low = _offset(self.origin, candidate.eligible_window.earliest)
            high = _offset(self.origin, candidate.eligible_window.latest)
            at_us = time_rng.randint(low, high)
            amounts: list[float] = []
            for index, effect in enumerate(candidate.effects):
                if effect.minimum_amount is None:
                    continue
                rng = self.streams.stream(f"runtime-event-amount:{candidate.event_id}:{index}")
                amounts.append(rng.uniform(effect.minimum_amount, effect.maximum_amount or 0))
            prepared = PreparedEvent(candidate.event_id, occurred, at_us, amounts)
            self.prepared_events[candidate.event_id] = prepared
            if occurred and not candidate.preconditions:
                amount_index = 0
                for effect in candidate.effects:
                    amount = amounts[amount_index] if effect.minimum_amount is not None else None
                    amount_index += effect.minimum_amount is not None
                    if effect.operation is RuntimeEventOperation.delay_activity_start:
                        self.delay_us[effect.target_id] += int(round((amount or 0) * MINUTE_US))
                    elif effect.operation is RuntimeEventOperation.extend_activity_duration:
                        self.extension_us[effect.target_id] += int(round((amount or 0) * MINUTE_US))

    def _day_for(self, day_date: date) -> Any:
        return next(item for item in self.bundle.scenario.days if item.date == day_date)

    def _selected_activities(self) -> list[CanonicalActivity]:
        selected: list[CanonicalActivity] = []
        for canonical_day in self.bundle.canonical_plan.days:
            day = self._day_for(canonical_day.date)
            replacements: dict[str, Any] = {}
            remove_ids: set[str] = set()
            for activity in canonical_day.activities:
                materialization_conditions = [
                    condition
                    for condition in activity.preconditions
                    if condition.fact in {"leftover_dinner_portion_available", "weather_is_dry"}
                ]
                definitely_false = any(
                    not _scenario_condition(
                        condition,
                        self.state,
                        activity.actor_id,
                        day.context.facts,
                        unknown_is_true=True,
                    )
                    for condition in materialization_conditions
                )
                if not definitely_false:
                    continue
                contingency = next(
                    (
                        item
                        for item in canonical_day.contingencies
                        if item.replaces_activity_id == activity.source_activity_id
                        and item.activation.fallback_trigger
                        and item.activation.fallback_trigger.value == "precondition_failed"
                    ),
                    None,
                )
                if contingency is not None:
                    replacements[activity.source_activity_id] = contingency
                    remove_ids.add(activity.source_activity_id)
                    remove_ids.update(
                        item.source_activity_id for item in contingency.omitted_activities
                    )
                    remove_ids.update(
                        item.source_activity_id for item in contingency.rescheduled_activities
                    )
                    self.replacement_deviations[activity.source_activity_id] = (
                        "fallback_applied",
                        contingency.contingency_id,
                    )
                elif not activity.mandatory:
                    remove_ids.add(activity.source_activity_id)
                    self.replacement_deviations[activity.source_activity_id] = (
                        "optional_dropped",
                        "precondition_failed",
                    )
            day_selected = [
                item
                for item in canonical_day.activities
                if item.source_activity_id not in remove_ids
            ]
            for target_id, contingency in replacements.items():
                day_selected.extend(contingency.activities)
                day_selected.extend(contingency.rescheduled_activities)
                self._record_dropped(target_id, contingency.contingency_id)
            for removed in sorted(remove_ids - set(replacements)):
                if removed not in {item.source_activity_id for item in day_selected}:
                    self._record_dropped(removed, "precondition_failed")
            selected.extend(day_selected)
        return sorted(selected, key=lambda item: (item.scheduled_start, item.sequence_index))

    def _record_dropped(self, activity_id: str, cause_id: str) -> None:
        original = next(
            (
                activity
                for day in self.bundle.canonical_plan.days
                for activity in day.activities
                if activity.source_activity_id == activity_id
            ),
            None,
        )
        if original is None:
            return
        execution_id = self.trace.identifier("activity", [activity_id])
        deviation_id = self.trace.identifier("deviation", [activity_id, cause_id])
        self.trace.deviations.append(
            PlanDeviation(
                deviation_id=deviation_id,
                activity_execution_id=execution_id,
                kind=self.replacement_deviations.get(activity_id, ("optional_dropped", ""))[0],
                cause_id=cause_id,
            )
        )
        self.trace.activities.append(
            ActivityExecution(
                activity_execution_id=execution_id,
                source_activity_id=activity_id,
                actor_id=original.actor_id,
                intent=original.intent,
                process_model_id=self._process_model_id(activity_id),
                planned_start=original.scheduled_start,
                planned_end=original.scheduled_end,
                actual_start=original.scheduled_start,
                actual_end=original.scheduled_start,
                status="dropped",
                deviation_ids=[deviation_id],
            )
        )

    def _process_model_id(self, activity_id: str) -> str:
        binding = next(
            (
                item
                for item in self.bundle.action_bindings
                if item.source_activity_id == activity_id
            ),
            None,
        )
        if binding is None:
            raise SimulationFailure(
                "PROCESS_EXECUTION_FAILED", f"Activity '{activity_id}' has no process binding."
            )
        return binding.process_model_id

    def _runtime_event_process(self, candidate: Any) -> Generator[Any, Any, None]:
        prepared = self.prepared_events[candidate.event_id]
        if candidate.trigger_activity_id is None:
            yield self.env.timeout(max(0, prepared.at_us - self.env.now))
        else:
            yield self.activity_start_events[candidate.trigger_activity_id]
        outcome = "not_sampled"
        if prepared.occurred:
            actor_id = next(iter(self.state.residents))
            day = self._day_for(_at(self.origin, self.env.now).date())
            conditions_ok = all(
                _scenario_condition(item, self.state, actor_id, day.context.facts)
                for item in candidate.preconditions
            )
            outcome = "applied" if conditions_ok else "precondition_failed"
            if conditions_ok:
                amount_index = 0
                for effect in candidate.effects:
                    amount = (
                        prepared.amounts[amount_index]
                        if effect.minimum_amount is not None
                        else None
                    )
                    amount_index += effect.minimum_amount is not None
                    if effect.operation is RuntimeEventOperation.interrupt_actor:
                        process = self.active_processes.get(effect.target_id)
                        if process is not None and process.is_alive:
                            process.interrupt(
                                {
                                    "event_id": candidate.event_id,
                                    "duration_us": int(round((amount or 0) * MINUTE_US)),
                                }
                            )
                    elif effect.operation is RuntimeEventOperation.invalidate_fact:
                        self.state.invalidated_facts.add(effect.target_id)
                        self._state_transition(
                            "environment",
                            "world",
                            effect.target_id,
                            None,
                            None,
                            "invalidate",
                            "runtime_event",
                            candidate.event_id,
                        )
                    elif effect.operation is RuntimeEventOperation.set_fact:
                        previous = self.state.environment_facts.get(effect.target_id)
                        self.state.environment_facts[effect.target_id] = effect.value
                        self._state_transition(
                            "environment",
                            "world",
                            effect.target_id,
                            previous,
                            effect.value,
                            "set",
                            "runtime_event",
                            candidate.event_id,
                        )
        self.trace.runtime_events.append(
            RuntimeEventExecution(
                event_execution_id=self.trace.identifier("runtime", [candidate.event_id]),
                event_id=candidate.event_id,
                sampled=True,
                occurred=prepared.occurred and outcome == "applied",
                evaluated_at=_at(self.origin, self.env.now),
                trigger_activity_id=candidate.trigger_activity_id,
                sampled_amounts=prepared.amounts,
                outcome=outcome,
            )
        )

    def _state_transition(
        self,
        subject_type: str,
        subject_id: str,
        fact: str,
        previous: JsonValue | None,
        value: JsonValue | None,
        operation: str,
        cause_type: str,
        cause_id: str,
    ) -> None:
        self.trace.transitions.append(
            StateTransition(
                transition_id=self.trace.identifier(
                    "state", [len(self.trace.transitions), self.env.now, subject_id, fact]
                ),
                at=_at(self.origin, self.env.now),
                subject_type=subject_type,
                subject_id=subject_id,
                fact=fact,
                previous_value=previous,
                value=value,
                operation=operation,
                causality=TraceCausality(cause_type=cause_type, cause_id=cause_id),
            )
        )

    def _resource_event(
        self, resource_id: str, activity_id: str, actor_id: str, operation: str, units: int
    ) -> None:
        self.trace.resources.append(
            ResourceEvent(
                resource_event_id=self.trace.identifier(
                    "resource", [len(self.trace.resources), resource_id, activity_id, operation]
                ),
                at=_at(self.origin, self.env.now),
                resource_id=resource_id,
                activity_execution_id=self.trace.identifier("activity", [activity_id]),
                actor_id=actor_id,
                operation=operation,
                units=units,
                available_units_after=self.resource_coordinator.available(resource_id),
            )
        )

    def _apply_effect(
        self,
        effect: StateEffect,
        actor_id: str,
        cause_id: str,
        binding: ResolvedActionBinding | None = None,
    ) -> None:
        fact = effect.fact
        provider = next(
            (
                item.provider_id
                for item in (binding.capability_bindings if binding else [])
                if item.provider_type == "entity"
            ),
            None,
        )
        if fact.startswith("resident."):
            path = fact.removeprefix("resident.")
            target = self.state.residents[actor_id].facts
            subject_type, subject_id = "resident", actor_id
        elif fact.startswith("entity."):
            parts = fact.split(".")
            entity_id = provider or (parts[1] if len(parts) > 2 else "world")
            path = parts[-1]
            target = self.state.entity_states.setdefault(entity_id, {})
            subject_type, subject_id = "entity", entity_id
        elif fact.startswith("capability."):
            parts = fact.split(".")
            path = f"{provider or 'world'}.{parts[-2]}.{parts[-1]}"
            target = self.state.capability_facts
            subject_type, subject_id = "entity", provider or "world"
        else:
            path = fact
            target = self.state.environment_facts
            subject_type, subject_id = "environment", "world"
        previous = target.get(path)
        value: Any = effect.value
        if effect.operation is EffectOperation.increment:
            value = (previous or 0) + effect.value
        elif effect.operation is EffectOperation.decrement:
            value = (previous or 0) - effect.value
        elif effect.operation is EffectOperation.append:
            value = [*(previous or []), effect.value]
        elif effect.operation is EffectOperation.remove:
            value = [item for item in (previous or []) if item != effect.value]
        target[path] = value
        self._state_transition(
            subject_type,
            subject_id,
            path,
            previous,
            value,
            effect.operation.value,
            "action_effect",
            cause_id,
        )

    def _action_fact(
        self,
        fact: str,
        actor_id: str,
        binding: ResolvedActionBinding,
    ) -> tuple[bool, Any]:
        provider = next(
            (
                item.provider_id
                for item in binding.capability_bindings
                if item.provider_type == "entity"
            ),
            None,
        )
        if fact.startswith("resident."):
            path = fact.removeprefix("resident.")
            facts = self.state.residents[actor_id].facts
            if path in facts:
                return True, facts[path]
            return _nested(facts, path)
        if fact.startswith("entity."):
            key = fact.split(".")[-1]
            target = self.state.entity_states.get(provider or "", {})
            return (key in target), target.get(key)
        if fact.startswith("capability."):
            parts = fact.split(".")
            key = f"{provider or 'world'}.{parts[-2]}.{parts[-1]}"
            return (key in self.state.capability_facts), self.state.capability_facts.get(key)
        return (fact in self.state.environment_facts), self.state.environment_facts.get(fact)

    def _check_action_preconditions(
        self,
        activity: CanonicalActivity,
        node: ProcessNode,
        binding: ResolvedActionBinding,
    ) -> None:
        definition = self.action_definitions[node.action_type or ""]
        arguments = {key: str(value) for key, value in binding.resolved_arguments.items()}
        for precondition in definition.preconditions:
            fact = precondition.fact_template.format(**arguments)
            present, actual = self._action_fact(fact, activity.actor_id, binding)
            operator = ConditionOperator(precondition.operator)
            if not _operator_matches(operator, present, actual, precondition.value):
                raise SimulationFailure(
                    "PRECONDITION_FAILED",
                    f"Action '{node.action_type}' failed precondition '{fact}'.",
                    f"$.actionBindings[{activity.source_activity_id}:{node.node_id}]",
                )
        day = self._day_for(activity.scheduled_start.date())
        for precondition in node.preconditions:
            if not _variable_condition(
                precondition,
                self.state,
                activity.actor_id,
                day,
                self.bundle,
                self.variable_catalog,
            ):
                raise SimulationFailure(
                    "PRECONDITION_FAILED",
                    f"Action node '{node.node_id}' failed its variable precondition.",
                )

    def _movement(
        self,
        binding: ResolvedActionBinding,
        action_execution_id: str,
        actor: ResidentRuntime,
    ) -> NavigationPath | None:
        if not binding.destination_interaction_point_id:
            return None
        destination = next(
            item
            for item in self.bundle.home_model.interaction_points
            if item.interaction_point_id == binding.destination_interaction_point_id
        )
        kinetics = self.kinematics[actor.resident_id]
        return plan_path(
            self.bundle.home_model,
            start_region_id=actor.region_id,
            start=actor.position,
            end_region_id=destination.region_id,
            end=destination.position,
            walking_speed_meters_per_second=kinetics.walking_speed_meters_per_second,
            body_radius_meters=kinetics.body_radius_meters,
            mobility_profile=kinetics.mobility_profile,
        )

    def _execute_action(
        self,
        activity: CanonicalActivity,
        activity_execution_id: str,
        node: ProcessNode,
        occurrence: int,
        duration_us: int,
    ) -> Generator[Any, Any, str]:
        binding = self.bindings[(activity.source_activity_id, node.node_id)]
        self._check_action_preconditions(activity, node, binding)
        action_id = self.trace.identifier(
            "action", [activity.source_activity_id, node.node_id, occurrence]
        )
        actor = self.state.residents[activity.actor_id]
        started = self.env.now
        path = self._movement(binding, action_id, actor)
        movement_us = int(round((path.duration_seconds if path else 0) * 1_000_000))
        actual_duration = max(duration_us, movement_us)
        if path and path.distance_meters > 1e-9:
            previous_state = actor.execution_state
            actor.execution_state = "moving"
            self._state_transition(
                "resident",
                actor.resident_id,
                "execution_state",
                previous_state,
                "moving",
                "set",
                "process_edge",
                action_id,
            )
            segment_lengths = [
                ((right.x - left.x) ** 2 + (right.y - left.y) ** 2) ** 0.5
                for left, right in zip(path.waypoints, path.waypoints[1:], strict=False)
            ]
            accumulated = 0.0
            waypoints = [
                TrajectoryWaypoint(
                    at=_at(self.origin, started),
                    region_id=path.waypoints[0].region_id,
                    position=Point2D(x=path.waypoints[0].x, y=path.waypoints[0].y),
                    traversal_mode=path.waypoints[0].traversal_mode,
                )
            ]
            for waypoint, length in zip(path.waypoints[1:], segment_lengths, strict=True):
                accumulated += length
                fraction = accumulated / path.distance_meters if path.distance_meters else 1
                waypoints.append(
                    TrajectoryWaypoint(
                        at=_at(self.origin, started + movement_us * fraction),
                        region_id=waypoint.region_id,
                        position=Point2D(x=waypoint.x, y=waypoint.y),
                        traversal_mode=waypoint.traversal_mode,
                    )
                )
            yield self.env.timeout(movement_us)
            destination = path.waypoints[-1]
            origin_region = actor.region_id
            actor.region_id = destination.region_id
            actor.position = Point2D(x=destination.x, y=destination.y)
            self.trace.movements.append(
                MovementExecution(
                    movement_id=self.trace.identifier("movement", [action_id]),
                    action_execution_id=action_id,
                    actor_id=actor.resident_id,
                    started_at=_at(self.origin, started),
                    ended_at=_at(self.origin, self.env.now),
                    origin_region_id=origin_region,
                    destination_region_id=actor.region_id,
                    distance_meters=path.distance_meters,
                    duration_microseconds=movement_us,
                    waypoints=waypoints,
                )
            )
            previous_state = actor.execution_state
            actor.execution_state = "performing_activity"
            self._state_transition(
                "resident",
                actor.resident_id,
                "execution_state",
                previous_state,
                actor.execution_state,
                "set",
                "process_edge",
                action_id,
            )
        remaining = max(0, actual_duration - int(self.env.now - started))
        while remaining:
            before = self.env.now
            try:
                yield self.env.timeout(remaining)
                remaining = 0
            except simpy.Interrupt as interruption:
                elapsed = int(self.env.now - before)
                remaining = max(0, remaining - elapsed)
                payload = interruption.cause
                if payload.get("kind") == "resource_preemption":
                    yield payload["resume_event"]
                    continue
                deviation_id = self.trace.identifier(
                    "deviation", [activity.source_activity_id, payload["event_id"]]
                )
                if not any(item.deviation_id == deviation_id for item in self.trace.deviations):
                    self.trace.deviations.append(
                        PlanDeviation(
                            deviation_id=deviation_id,
                            activity_execution_id=activity_execution_id,
                            kind="interrupted",
                            amount_microseconds=payload["duration_us"],
                            cause_id=payload["event_id"],
                        )
                    )
                actor.execution_state = "interrupted"
                yield self.env.timeout(payload["duration_us"])
                actor.execution_state = "performing_activity"
        if node.action_type == "change_posture":
            posture = binding.resolved_arguments["posture"]
            previous = actor.posture
            actor.posture = str(posture)
            self._state_transition(
                "resident",
                actor.resident_id,
                "posture",
                previous,
                actor.posture,
                "set",
                "action_effect",
                action_id,
            )
        definition = self.action_definitions[node.action_type or ""]
        arguments = {key: str(value) for key, value in binding.resolved_arguments.items()}
        for template in definition.effects:
            fact = template.fact_template.format(**arguments)
            value = (
                template.value.format(**arguments)
                if isinstance(template.value, str)
                else template.value
            )
            self._apply_effect(
                StateEffect(fact=fact, operation=template.operation, value=value),
                actor.resident_id,
                action_id,
                binding,
            )
        for effect in node.effects:
            self._apply_effect(effect, actor.resident_id, action_id, binding)
        self.trace.actions.append(
            ActionExecution(
                action_execution_id=action_id,
                activity_execution_id=activity_execution_id,
                node_id=node.node_id,
                occurrence_index=occurrence,
                action_type=node.action_type or "",
                actor_id=actor.resident_id,
                started_at=_at(self.origin, started),
                ended_at=_at(self.origin, self.env.now),
                status="completed",
                resolved_arguments=binding.resolved_arguments,
                provider_ids=[item.provider_id for item in binding.capability_bindings],
            )
        )
        return action_id

    def _activity_process(self, activity: CanonicalActivity) -> Generator[Any, Any, None]:
        planned_us = _offset(self.origin, activity.scheduled_start)
        requested_us = planned_us + self.delay_us[activity.source_activity_id]
        yield self.env.timeout(max(0, requested_us - self.env.now))
        execution_id = self.trace.identifier("activity", [activity.source_activity_id])
        actor_id = activity.actor_id
        day = self._day_for(activity.scheduled_start.date())
        lock = self.actor_locks[actor_id]
        with lock.request() as actor_request:
            yield actor_request
            actual_start_us = int(self.env.now)
            start_event = self.activity_start_events.get(activity.source_activity_id)
            if start_event is not None and not start_event.triggered:
                start_event.succeed(actual_start_us)
            deviations: list[str] = []
            if actual_start_us > planned_us:
                cause = (
                    next(
                        (
                            item.event_id
                            for item in self.bundle.scenario.runtime_event_candidates
                            if any(
                                effect.target_id == activity.source_activity_id
                                and effect.operation is RuntimeEventOperation.delay_activity_start
                                for effect in item.effects
                            )
                            and self.prepared_events[item.event_id].occurred
                        ),
                        None,
                    )
                    or "actor_availability"
                )
                deviation_id = self.trace.identifier(
                    "deviation", [activity.source_activity_id, cause]
                )
                kind = (
                    "delayed_start" if cause != "actor_availability" else "shifted_by_local_repair"
                )
                self.trace.deviations.append(
                    PlanDeviation(
                        deviation_id=deviation_id,
                        activity_execution_id=execution_id,
                        kind=kind,
                        amount_microseconds=actual_start_us - planned_us,
                        cause_id=cause,
                    )
                )
                deviations.append(deviation_id)
            conditions_ok = all(
                _scenario_condition(item, self.state, actor_id, day.context.facts)
                for item in activity.preconditions
            )
            if not conditions_ok:
                if activity.mandatory:
                    raise SimulationFailure(
                        "PRECONDITION_FAILED",
                        f"Mandatory activity '{activity.source_activity_id}' failed "
                        "live preconditions.",
                    )
                deviation_id = self.trace.identifier(
                    "deviation", [activity.source_activity_id, "live-precondition"]
                )
                self.trace.deviations.append(
                    PlanDeviation(
                        deviation_id=deviation_id,
                        activity_execution_id=execution_id,
                        kind="optional_dropped",
                        cause_id="live_precondition_failed",
                    )
                )
                self.trace.activities.append(
                    ActivityExecution(
                        activity_execution_id=execution_id,
                        source_activity_id=activity.source_activity_id,
                        actor_id=actor_id,
                        intent=activity.intent,
                        process_model_id=self._process_model_id(activity.source_activity_id),
                        planned_start=activity.scheduled_start,
                        planned_end=activity.scheduled_end,
                        actual_start=_at(self.origin, self.env.now),
                        actual_end=_at(self.origin, self.env.now),
                        status="dropped",
                        deviation_ids=[deviation_id],
                    )
                )
                return
            actor = self.state.residents[actor_id]
            actor.execution_state = "performing_activity"
            requirements = {item.resource_id: item.units for item in activity.required_resources}
            allocation: ResourceAllocation | None = None
            for resource_id, units in sorted(requirements.items()):
                self._resource_event(
                    resource_id,
                    activity.source_activity_id,
                    actor_id,
                    "requested",
                    units,
                )
            if requirements:
                preemption_started: int | None = None
                preempted_resources: set[str] = set()
                while allocation is None:
                    try:
                        allocation = yield self.resource_coordinator.request(
                            allocation_id=execution_id,
                            activity_id=activity.source_activity_id,
                            actor_id=actor_id,
                            priority=activity.priority,
                            requirements=requirements,
                        )
                    except simpy.Interrupt as interruption:
                        payload = interruption.cause
                        if payload.get("kind") != "resource_preemption":
                            raise
                        if preemption_started is None:
                            preemption_started = int(self.env.now)
                        preempted_resources.update(payload["resource_ids"])
                        for resource_id, units in sorted(requirements.items()):
                            self._resource_event(
                                resource_id,
                                activity.source_activity_id,
                                actor_id,
                                "preempted",
                                units,
                            )
                            self._resource_event(
                                resource_id,
                                activity.source_activity_id,
                                actor_id,
                                "requested",
                                units,
                            )
                if preemption_started is not None:
                    cause = "resource:" + ",".join(sorted(preempted_resources))
                    deviation_id = self.trace.identifier(
                        "deviation", [activity.source_activity_id, cause]
                    )
                    self.trace.deviations.append(
                        PlanDeviation(
                            deviation_id=deviation_id,
                            activity_execution_id=execution_id,
                            kind="interrupted",
                            amount_microseconds=int(self.env.now) - preemption_started,
                            cause_id=cause,
                        )
                    )
                    deviations.append(deviation_id)
            for resource_id, units in sorted(requirements.items()):
                actor.held_resources.add(resource_id)
                self._resource_event(
                    resource_id,
                    activity.source_activity_id,
                    actor_id,
                    "acquired",
                    units,
                )
            process_model_id = self._process_model_id(activity.source_activity_id)
            model = self.models[process_model_id]
            phases = _expand_process(
                model, self.state, actor_id, day, self.bundle, self.variable_catalog
            )
            phase_weights = [max(node.duration_weight or 1 for node in phase) for phase in phases]
            intended = (
                activity.duration_microseconds + self.extension_us[activity.source_activity_id]
            )
            total_weight = sum(phase_weights)
            occurrences: Counter[str] = Counter()
            action_ids: list[str] = []
            self.active_processes[actor_id] = self.env.active_process
            for phase, weight in zip(phases, phase_weights, strict=True):
                duration_us = max(1, int(round(intended * weight / total_weight)))
                processes = []
                for node in phase:
                    occurrence = occurrences[node.node_id]
                    occurrences[node.node_id] += 1
                    processes.append(
                        self.env.process(
                            self._execute_action(
                                activity, execution_id, node, occurrence, duration_us
                            )
                        )
                    )
                while True:
                    try:
                        results = yield simpy.events.AllOf(self.env, processes)
                        break
                    except simpy.Interrupt as interruption:
                        payload = interruption.cause
                        if payload.get("kind") == "resource_preemption":
                            preempted_at = int(self.env.now)
                            preempted_resources = set(payload["resource_ids"])
                            actor.execution_state = "interrupted"
                            resume_event = self.env.event()
                            for process in processes:
                                if process.is_alive:
                                    process.interrupt(
                                        {
                                            "kind": "resource_preemption",
                                            "resume_event": resume_event,
                                        }
                                    )
                            for resource_id, units in sorted(requirements.items()):
                                actor.held_resources.discard(resource_id)
                                self._resource_event(
                                    resource_id,
                                    activity.source_activity_id,
                                    actor_id,
                                    "preempted",
                                    units,
                                )
                                self._resource_event(
                                    resource_id,
                                    activity.source_activity_id,
                                    actor_id,
                                    "requested",
                                    units,
                                )
                            allocation = None
                            while allocation is None:
                                try:
                                    allocation = yield self.resource_coordinator.request(
                                        allocation_id=execution_id,
                                        activity_id=activity.source_activity_id,
                                        actor_id=actor_id,
                                        priority=activity.priority,
                                        requirements=requirements,
                                    )
                                except simpy.Interrupt as repeated_interruption:
                                    repeated_payload = repeated_interruption.cause
                                    if repeated_payload.get("kind") != "resource_preemption":
                                        raise
                                    preempted_resources.update(repeated_payload["resource_ids"])
                                    for resource_id, units in sorted(requirements.items()):
                                        self._resource_event(
                                            resource_id,
                                            activity.source_activity_id,
                                            actor_id,
                                            "preempted",
                                            units,
                                        )
                                        self._resource_event(
                                            resource_id,
                                            activity.source_activity_id,
                                            actor_id,
                                            "requested",
                                            units,
                                        )
                            for resource_id, units in sorted(requirements.items()):
                                actor.held_resources.add(resource_id)
                                self._resource_event(
                                    resource_id,
                                    activity.source_activity_id,
                                    actor_id,
                                    "acquired",
                                    units,
                                )
                            resume_event.succeed()
                            actor.execution_state = "performing_activity"
                            cause = "resource:" + ",".join(sorted(preempted_resources))
                            deviation_id = self.trace.identifier(
                                "deviation", [activity.source_activity_id, cause]
                            )
                            if deviation_id not in deviations:
                                self.trace.deviations.append(
                                    PlanDeviation(
                                        deviation_id=deviation_id,
                                        activity_execution_id=execution_id,
                                        kind="interrupted",
                                        amount_microseconds=int(self.env.now) - preempted_at,
                                        cause_id=cause,
                                    )
                                )
                                deviations.append(deviation_id)
                            continue
                        deviation_id = self.trace.identifier(
                            "deviation",
                            [activity.source_activity_id, payload["event_id"]],
                        )
                        if deviation_id not in deviations:
                            self.trace.deviations.append(
                                PlanDeviation(
                                    deviation_id=deviation_id,
                                    activity_execution_id=execution_id,
                                    kind="interrupted",
                                    amount_microseconds=payload["duration_us"],
                                    cause_id=payload["event_id"],
                                )
                            )
                            deviations.append(deviation_id)
                        actor.execution_state = "interrupted"
                        yield self.env.timeout(payload["duration_us"])
                        actor.execution_state = "performing_activity"
                action_ids.extend(result for result in results.values() if isinstance(result, str))
            self.active_processes.pop(actor_id, None)
            if allocation is not None:
                self.resource_coordinator.release(allocation)
            for resource_id, units in sorted(requirements.items(), reverse=True):
                actor.held_resources.discard(resource_id)
                self._resource_event(
                    resource_id, activity.source_activity_id, actor_id, "released", units
                )
            for effect in activity.effects:
                self._apply_effect(effect, actor_id, execution_id)
            self.state.completed_activities.add(activity.source_activity_id)
            actor.execution_state = "idle"
            if self.extension_us[activity.source_activity_id]:
                event_id = next(
                    item.event_id
                    for item in self.bundle.scenario.runtime_event_candidates
                    if any(
                        effect.target_id == activity.source_activity_id
                        and effect.operation is RuntimeEventOperation.extend_activity_duration
                        for effect in item.effects
                    )
                    and self.prepared_events[item.event_id].occurred
                )
                deviation_id = self.trace.identifier(
                    "deviation", [activity.source_activity_id, event_id]
                )
                self.trace.deviations.append(
                    PlanDeviation(
                        deviation_id=deviation_id,
                        activity_execution_id=execution_id,
                        kind="extended_duration",
                        amount_microseconds=self.extension_us[activity.source_activity_id],
                        cause_id=event_id,
                    )
                )
                deviations.append(deviation_id)
            status = "deviated" if deviations else "completed"
            self.trace.activities.append(
                ActivityExecution(
                    activity_execution_id=execution_id,
                    source_activity_id=activity.source_activity_id,
                    actor_id=actor_id,
                    intent=activity.intent,
                    process_model_id=process_model_id,
                    planned_start=activity.scheduled_start,
                    planned_end=activity.scheduled_end,
                    actual_start=_at(self.origin, actual_start_us),
                    actual_end=_at(self.origin, self.env.now),
                    status=status,
                    action_execution_ids=action_ids,
                    deviation_ids=deviations,
                )
            )

    def run(self) -> ExecutionTrace:
        for candidate in self.bundle.scenario.runtime_event_candidates:
            self.env.process(self._runtime_event_process(candidate))
        activities = self._selected_activities()
        processes = [self.env.process(self._activity_process(item)) for item in activities]
        try:
            self.env.run(until=simpy.events.AllOf(self.env, processes))
        except SimulationFailure:
            raise
        except Exception as error:
            raise SimulationFailure("SIMULATION_FAILED", str(error)) from error
        trace_end_us = max(
            _offset(self.origin, self.bundle.scenario.simulation_window.end), int(self.env.now)
        )
        self.env.run(until=trace_end_us + 1)
        self.trace.activities.sort(key=lambda item: (item.actual_start, item.source_activity_id))
        self.trace.actions.sort(key=lambda item: (item.started_at, item.action_execution_id))
        self.trace.movements.sort(key=lambda item: (item.started_at, item.movement_id))
        self.trace.transitions.sort(key=lambda item: (item.at, item.transition_id))
        self.trace.resources.sort(key=lambda item: (item.at, item.resource_event_id))
        self.trace.runtime_events.sort(key=lambda item: (item.evaluated_at, item.event_id))
        self.trace.deviations.sort(key=lambda item: item.deviation_id)
        final_state = FinalWorldState(
            at=_at(self.origin, trace_end_us),
            residents=[
                ResidentFinalState(
                    resident_id=item.resident_id,
                    region_id=item.region_id,
                    position=item.position,
                    posture=item.posture,
                    execution_state="idle",
                    facts=item.facts,
                    held_resource_ids=sorted(item.held_resources),
                )
                for item in sorted(self.state.residents.values(), key=lambda item: item.resident_id)
            ],
            entity_states=self.state.entity_states,
            environment_facts=self.state.environment_facts,
            resource_available_units={
                key: self.resource_coordinator.available(key)
                for key in sorted(self.resource_capacities)
            },
        )
        daily = []
        for plan_day in self.bundle.canonical_plan.days:
            items = [
                item for item in self.trace.activities if item.planned_start.date() == plan_day.date
            ]
            daily.append(
                DailyExecutionSummary(
                    date=plan_day.date,
                    completed_activity_count=sum(item.status == "completed" for item in items),
                    deviated_activity_count=sum(item.status == "deviated" for item in items),
                    failed_activity_count=sum(item.status == "failed" for item in items),
                    dropped_activity_count=sum(item.status == "dropped" for item in items),
                )
            )
        base = {
            "sourceBundleId": self.bundle.bundle_id,
            "seed": self.bundle.seed,
            "activityExecutions": [
                item.model_dump(mode="json", by_alias=True) for item in self.trace.activities
            ],
            "actionExecutions": [
                item.model_dump(mode="json", by_alias=True) for item in self.trace.actions
            ],
            "movements": [
                item.model_dump(mode="json", by_alias=True) for item in self.trace.movements
            ],
            "stateTransitions": [
                item.model_dump(mode="json", by_alias=True) for item in self.trace.transitions
            ],
            "resourceEvents": [
                item.model_dump(mode="json", by_alias=True) for item in self.trace.resources
            ],
            "runtimeEvents": [
                item.model_dump(mode="json", by_alias=True) for item in self.trace.runtime_events
            ],
            "planDeviations": [
                item.model_dump(mode="json", by_alias=True) for item in self.trace.deviations
            ],
            "finalState": final_state.model_dump(mode="json", by_alias=True),
        }
        return ExecutionTrace(
            trace_id=f"trace_{canonical_sha256(self.bundle)[:16]}",
            source_bundle_id=self.bundle.bundle_id,
            source_bundle_sha256=canonical_sha256(self.bundle),
            seed=self.bundle.seed,
            started_at=self.origin,
            ended_at=_at(self.origin, trace_end_us),
            activity_executions=self.trace.activities,
            action_executions=self.trace.actions,
            movements=self.trace.movements,
            state_transitions=self.trace.transitions,
            resource_events=self.trace.resources,
            runtime_events=self.trace.runtime_events,
            plan_deviations=self.trace.deviations,
            daily_summaries=daily,
            final_state=final_state,
            semantic_digest=_semantic_digest(base),
        )


def _summary(
    trace: ExecutionTrace | None, issues: list[SimulationIssue], planned: int
) -> SimulationSummary:
    activities = trace.activity_executions if trace else []
    return SimulationSummary(
        planned_activity_count=planned,
        completed_activity_count=sum(item.status == "completed" for item in activities),
        deviated_activity_count=sum(item.status == "deviated" for item in activities),
        failed_activity_count=sum(item.status == "failed" for item in activities),
        dropped_activity_count=sum(item.status == "dropped" for item in activities),
        action_execution_count=len(trace.action_executions) if trace else 0,
        movement_count=len(trace.movements) if trace else 0,
        state_transition_count=len(trace.state_transitions) if trace else 0,
        runtime_event_count=sum(item.occurred for item in trace.runtime_events) if trace else 0,
        error_count=sum(item.severity == "error" for item in issues),
        warning_count=sum(item.severity == "warning" for item in issues),
    )


def validate_execution_trace(
    trace: ExecutionTrace, bundle: SimulationBundle
) -> list[SimulationIssue]:
    """Validate causal references, state closure, and spatial trace invariants."""
    messages: list[tuple[str, str]] = []
    identifier_groups = {
        "activity": [item.activity_execution_id for item in trace.activity_executions],
        "action": [item.action_execution_id for item in trace.action_executions],
        "movement": [item.movement_id for item in trace.movements],
        "state transition": [item.transition_id for item in trace.state_transitions],
        "resource event": [item.resource_event_id for item in trace.resource_events],
        "runtime event": [item.event_execution_id for item in trace.runtime_events],
        "deviation": [item.deviation_id for item in trace.plan_deviations],
    }
    for label, identifiers in identifier_groups.items():
        duplicates = sorted(value for value, count in Counter(identifiers).items() if count > 1)
        if duplicates:
            messages.append((f"$.{label}", f"Duplicate {label} identifiers: {duplicates}"))
    activities = {item.activity_execution_id: item for item in trace.activity_executions}
    actions = {item.action_execution_id: item for item in trace.action_executions}
    deviations = {item.deviation_id for item in trace.plan_deviations}
    grouped_actions: defaultdict[str, list[str]] = defaultdict(list)
    for action in trace.action_executions:
        if action.activity_execution_id not in activities:
            messages.append(
                (
                    "$.actionExecutions",
                    f"Action '{action.action_execution_id}' references an unknown activity.",
                )
            )
        grouped_actions[action.activity_execution_id].append(action.action_execution_id)
    for activity in trace.activity_executions:
        if set(activity.action_execution_ids) != set(
            grouped_actions[activity.activity_execution_id]
        ):
            messages.append(
                (
                    "$.activityExecutions",
                    f"Activity '{activity.source_activity_id}' has inconsistent action references.",
                )
            )
        if not set(activity.deviation_ids) <= deviations:
            messages.append(
                (
                    "$.activityExecutions",
                    f"Activity '{activity.source_activity_id}' references an unknown deviation.",
                )
            )
    regions = {
        item.region_id: Polygon([(point.x, point.y) for point in item.boundary.vertices])
        for item in bundle.home_model.regions
    }
    obstacles: defaultdict[str, list[Polygon]] = defaultdict(list)
    for obstacle in bundle.home_model.obstacles:
        obstacles[obstacle.region_id].append(
            Polygon([(point.x, point.y) for point in obstacle.boundary.vertices])
        )
    for movement in trace.movements:
        if movement.action_execution_id not in actions:
            messages.append(
                (
                    "$.movements",
                    f"Movement '{movement.movement_id}' references an unknown action.",
                )
            )
        previous_at = movement.started_at
        for waypoint in movement.waypoints:
            point = ShapelyPoint(waypoint.position.x, waypoint.position.y)
            region = regions.get(waypoint.region_id)
            if region is None or not region.covers(point):
                messages.append(
                    (
                        "$.movements",
                        f"Movement '{movement.movement_id}' leaves region geometry.",
                    )
                )
                break
            if any(obstacle.contains(point) for obstacle in obstacles[waypoint.region_id]):
                messages.append(
                    (
                        "$.movements",
                        f"Movement '{movement.movement_id}' enters an obstacle.",
                    )
                )
                break
            if waypoint.at < previous_at or waypoint.at > movement.ended_at:
                messages.append(
                    (
                        "$.movements",
                        f"Movement '{movement.movement_id}' has non-monotonic waypoint time.",
                    )
                )
                break
            previous_at = waypoint.at
    capacities = {item.resource_id: item.capacity for item in bundle.scenario.resources}
    if trace.final_state.resource_available_units != capacities:
        messages.append(("$.finalState", "Final resource capacity was not fully released."))
    if any(item.held_resource_ids for item in trace.final_state.residents):
        messages.append(("$.finalState", "A resident retains a resource after simulation."))
    payload = trace.model_dump(mode="json", by_alias=True)
    if trace.semantic_digest != _semantic_digest(payload):
        messages.append(("$.semanticDigest", "Semantic digest does not match trace content."))
    return [
        SimulationIssue(
            code="TRACE_INVARIANT_FAILED",
            stage="invariant",
            path=path,
            message=message,
        )
        for path, message in messages
    ]


def simulate_bundle(bundle: SimulationBundle) -> SimulationResult:
    planned = sum(len(day.activities) for day in bundle.canonical_plan.days)
    try:
        trace = SimulationEngine(bundle).run()
    except SimulationFailure as error:
        issues = [
            SimulationIssue(
                code=error.code,
                stage="execution",
                path=error.path,
                message=str(error),
            )
        ]
        return SimulationResult(
            report=SimulationReport(
                success=False,
                source_bundle_id=bundle.bundle_id,
                source_bundle_sha256=canonical_sha256(bundle),
                issues=issues,
                summary=_summary(None, issues, planned),
            )
        )
    except Exception as error:
        issues = [
            SimulationIssue(
                code="SIMULATION_FAILED",
                stage="execution",
                path="$",
                message=str(error),
            )
        ]
        return SimulationResult(
            report=SimulationReport(
                success=False,
                source_bundle_id=bundle.bundle_id,
                source_bundle_sha256=canonical_sha256(bundle),
                issues=issues,
                summary=_summary(None, issues, planned),
            )
        )
    invariant_issues = validate_execution_trace(trace, bundle)
    if invariant_issues:
        return SimulationResult(
            report=SimulationReport(
                success=False,
                source_bundle_id=bundle.bundle_id,
                source_bundle_sha256=canonical_sha256(bundle),
                issues=invariant_issues,
                summary=_summary(None, invariant_issues, planned),
            )
        )
    trace_sha = canonical_sha256(trace)
    return SimulationResult(
        trace=trace,
        report=SimulationReport(
            success=True,
            source_bundle_id=bundle.bundle_id,
            source_bundle_sha256=canonical_sha256(bundle),
            trace_sha256=trace_sha,
            semantic_digest=trace.semantic_digest,
            summary=_summary(trace, [], planned),
        ),
    )


def _input_issue(code: str, message: str, path: str = "$") -> SimulationResult:
    issue = SimulationIssue(code=code, stage="input", path=path, message=message)
    return SimulationResult(
        report=SimulationReport(success=False, issues=[issue], summary=_summary(None, [issue], 0))
    )


def load_simulation_bundle_file(
    path: Path,
) -> tuple[SimulationBundle | None, list[SimulationIssue]]:
    def issue(code: str, message: str, issue_path: str = "$") -> list[SimulationIssue]:
        return [SimulationIssue(code=code, stage="input", path=issue_path, message=message)]

    try:
        encoded = path.read_bytes()
    except FileNotFoundError:
        return None, issue("FILE_NOT_FOUND", f"Simulation bundle not found: {path}")
    except OSError as error:
        return None, issue("FILE_READ_ERROR", f"Cannot read simulation bundle: {error}")
    if len(encoded) > MAX_SCENARIO_BYTES * 20:
        return None, issue("FILE_TOO_LARGE", "Simulation bundle exceeds the input size limit.")
    try:
        raw = encoded.decode("utf-8")
    except UnicodeDecodeError:
        return None, issue("FILE_ENCODING_ERROR", "Simulation bundle must be UTF-8.")
    if _exceeds_json_nesting_limit(raw):
        return None, issue("JSON_NESTING_TOO_DEEP", "Simulation bundle is nested too deeply.")
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except (DuplicateJsonKeyError, InvalidJsonConstantError, json.JSONDecodeError) as error:
        return None, issue("JSON_SYNTAX", f"Invalid simulation bundle JSON: {error}")
    if not isinstance(payload, dict):
        return None, issue("STRUCTURE_INVALID", "Simulation bundle must be a JSON object.")
    if payload.get("schemaVersion") != SUPPORTED_BUNDLE_VERSION:
        return None, issue(
            "UNSUPPORTED_SCHEMA_VERSION",
            f"Expected simulation bundle schemaVersion '{SUPPORTED_BUNDLE_VERSION}'.",
            "$.schemaVersion",
        )
    try:
        bundle = SimulationBundle.model_validate_json(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
    except ValidationError as error:
        return None, [
            SimulationIssue(
                code="BUNDLE_INVALID",
                stage="input",
                path=_json_path(item["loc"]),
                message=item["msg"],
            )
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        ]
    return bundle, []


def simulate_file(path: Path) -> SimulationResult:
    bundle, issues = load_simulation_bundle_file(path)
    if bundle is None:
        if len(issues) == 1:
            item = issues[0]
            return _input_issue(item.code, item.message, item.path)
        return SimulationResult(
            report=SimulationReport(success=False, issues=issues, summary=_summary(None, issues, 0))
        )
    return simulate_bundle(bundle)


def replay_files(bundle_path: Path, trace_path: Path) -> ReplayReport:
    result = simulate_file(bundle_path)
    try:
        expected = ExecutionTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        issue = SimulationIssue(
            code="STRUCTURE_INVALID",
            stage="input",
            path="$",
            message=f"Cannot parse expected execution trace: {error}",
        )
        report = SimulationReport(
            success=False,
            issues=[issue],
            summary=_summary(None, [issue], 0),
        )
        return ReplayReport(
            matches=False,
            source_bundle_id=result.report.source_bundle_id or "unknown",
            expected_semantic_digest="0" * 64,
            simulation_report=report,
        )
    actual = result.trace.semantic_digest if result.trace else None
    return ReplayReport(
        matches=actual == expected.semantic_digest,
        source_bundle_id=expected.source_bundle_id,
        expected_semantic_digest=expected.semantic_digest,
        actual_semantic_digest=actual,
        simulation_report=result.report,
    )
