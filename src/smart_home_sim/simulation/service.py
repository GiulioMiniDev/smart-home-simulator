from __future__ import annotations

import bisect
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Generator, Iterable
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
from smart_home_sim.domain.environment import (
    ConnectionKind,
    Point2D,
    ResolvedActionBinding,
    SimulationBundle,
)
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
from smart_home_sim.environment.occupancy import berth_for
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
# A plan states twenty-five minutes; the person takes twenty-three and a half, or twenty-seven.
# Without this the realised duration equals the planned one exactly, so every activity in the log
# lasts a whole number of minutes and `(actualEnd - actualStart) % 60 == 0` has no exceptions —
# a synthetic fingerprint one modulo finds. Lognormal keeps the plan as the central tendency and
# scales the deviation with the activity's length.
EXECUTION_PACE_SIGMA = 0.10
# The bound is a tanh squash rather than a clamp. A hard clamp maps every extreme draw onto the
# same two factors, and an exact factor times a whole-minute plan lands back on a whole minute —
# reintroducing, for the ~1% of activities that hit the bound, the very fingerprint this removes.
EXECUTION_PACE_LOG_LIMIT = 0.262
EXECUTION_PACE_MIN_FACTOR = math.exp(-EXECUTION_PACE_LOG_LIMIT)
EXECUTION_PACE_MAX_FACTOR = math.exp(EXECUTION_PACE_LOG_LIMIT)
# The postures a resident can cross a room in. Anything else has to be left first, and
# `_execute_action` makes her leave it — see the note there.
_STANDING_POSTURE = "standing"
_SITTING_POSTURE = "sitting"
_RECLINING_POSTURE = "lying"
_AMBULATORY_POSTURES = frozenset({_STANDING_POSTURE, "walking"})
# Actions a body cannot perform lying down. Walking was the first one found and the rule turned
# out to be wider: an activity that changes no room inherits whatever posture the last one left,
# so a resident who had been reading on the sofa tidied the living room without getting up. These
# are the ones that need hands, a cupboard or a floor.
# Deliberately not here: `activate`, `deactivate`, `manage_medication`, `personal_care`. Those are
# done wherever the body already is — a television is turned on from the sofa, and putting a
# switch in the set stood the resident up one second after she had sat down to watch, which is the
# same defect as the breakfast taken standing and was found the same way, in the replay frames.
_UPRIGHT_ACTIONS = frozenset(
    {
        "clean",
        "close",
        "exercise",
        "laundry_step",
        "open",
        "organize",
        "prepare_food",
        "put_item",
        "take_item",
    }
)

# What the resident does with the time the plan did not ask for.
#
# Until now: nothing at all. The plan's last action left her wherever it finished and no process
# owned the minutes that followed, so she held that spot — standing in the bathroom for two hours
# and sixteen minutes after a shower, 402 minutes a day across a generated year, 65 of them in the
# bathroom. The sensor model renders this faithfully and that is the problem: its presence pulses
# are right ("still, but never perfectly still"), so a statue in a bathroom emits a person's worth
# of bathroom motion, 162 events a day that no activity explains.
#
# Two corrections, both of which stay inside the trace contract. A body leaves the room it has
# finished with, which needs a movement and therefore an action, so the walk is charged to the
# activity that just ended — going back to the sitting room is part of finishing the shower, not a
# new thing the resident decided to do, and nothing new appears in the ground truth. And a body
# waiting sits down, which is a posture and needs no action at all; the presence-pulse rate follows
# the posture, so the log stops reporting a standing person for hours on end.
#
# What deliberately is *not* here: filler activities. Giving the gaps a name changes what the
# dataset is asking a recogniser to do, and that is a decision to take with a measurement beside
# it, not a side effect of a bug fix.

# Rooms a person passes through rather than settles in. The kitchen and the balcony are absent on
# purpose: standing in a kitchen for twenty minutes is something people do, and the posture
# settling below covers it. Standing in a shower for two hours is not.
_TRANSIENT_REGIONS = frozenset(
    {"bathroom", "hallway", "corridor", "entrance", "entryway", "utility", "laundry"}
)
# Where she goes instead, most-preferred first; the first one the dwelling actually has wins.
_SETTLING_PREFERENCE = ("living_room", "lounge", "sitting_room", "kitchen", "bedroom")
# What a room offers to a body with nothing to do, best first.
_RESTING_FURNITURE = frozenset({"sofa", "armchair", "bed", "recliner", "daybed"})
# What can be sat on. `move_to` goes to a room, and a room's anchor is its middle, so a process
# that says "go to the kitchen, sit down, eat" seated the resident on the floor in the centre of
# it — and every meal of a generated year was then taken next to the refrigerator, because the
# only action that named a fixture was the one holding the food. Sitting down is sitting down
# *on* something, and this is the list of what.
_SEATING_FURNITURE = frozenset(
    {"chair", "sofa", "armchair", "stool", "bench", "bed", "recliner", "daybed"}
)
# The capability role of a provider that is merely holding something. Handing over an item does
# not move the body that is already seated within reach.
_ITEM_ROLE = "item"
# How far a seated body will reach rather than stand up, measured from where she is sitting to the
# edge of the thing she wants. Generous for an arm — a desk chair sits 0.27m from its desk — and
# far short of anything across the room.
SEATED_REACH_METRES = 0.9
# And what may be lain on. Reclining is not a property of the room but of what she is on: lying
# down in a sitting room is a sofa, and lying down in the middle of one is a floor.
_RECLINING_FURNITURE = frozenset({"sofa", "bed", "recliner", "daybed"})
# How upright each posture is. Waiting only ever moves *down* this ladder: someone who finished
# reading on the sofa lying down does not sit up in order to wait. Without the order, the settle
# read the schedule literally and sat a lying resident up 1,162 times over one generated year.
_UPRIGHTNESS = {_STANDING_POSTURE: 2, _SITTING_POSTURE: 1, _RECLINING_POSTURE: 0}
# Below this the walk is not worth taking: she is between two steps of the same morning.
IDLE_RETURN_AFTER_SECONDS = 10 * 60
# How long she stays on her feet before sitting, and before settling back on a long wait.
IDLE_SIT_AFTER_SECONDS = 120.0
IDLE_RECLINE_AFTER_SECONDS = 25 * 60.0
# The spread on both, so a year of waits does not share one stopwatch.
IDLE_SETTLE_LOG_SIGMA = 0.35
# The node id the return walk is filed under. Synthetic: it names no node of any process model,
# because no author wrote it. Nothing downstream resolves node ids against the model.
RETURN_NODE_ID = "engine_return_from_service_room"

# How long a gesture takes on its own, in seconds, regardless of how much time the plan has
# budgeted for the activity around it. Sitting down takes a moment whether the meal that follows
# runs twenty minutes or two hours.
#
# Without this the whole budget was shared out by `durationWeight` alone, so every step stretched
# with the activity. An eight-hour sleep whose three steps all weigh 1.0 — which is what the
# authoring model emits, on all 110 action nodes of the twelve-month package — became two hours
# and forty minutes of `move_to`, the same again of `change_posture`, and only the last third of
# actual sleeping. Over that export it put 1.671 hours a year into changing posture; and since
# `change_posture` is one of the action types the PIR model treats as manual work, three quarters
# of the night's motion pulses came from a resident lying still in bed.
#
# Only gestures with a length of their own are listed. Everything absent is elastic: it is what
# the activity is made of, and it absorbs whatever the budget leaves. Travel actions are entered
# at zero because their real length is the walk, which `_execute_action` floors them at once the
# path is planned.
#
# `change_posture` is the one entry that is only a fallback. Lying down takes longer than standing
# up, and by how much is already stated per resident in the bundle, in
# `residentKinematics.postureTransitionSeconds` — so the engine reads it from there and this number
# is used only where the target posture is not one the kinematics name.
# The bladder, and the first drive the engine carries rather than the planner.
#
# `drives.py` threads sleep debt, hunger, social need and fatigue from one day to the next and
# turns them into the shape of a day — bedtime, night length, a nap, a nocturnal trip. It decides
# all of that *before* the day runs, which is why the resident's toilet visits came out at 1.4 a
# day against the six to eight a person actually makes: the plan can only place what an author
# declared, and no author declares a bladder.
#
# So the planner seeds candidate visits through the waking day and the engine decides which of
# them happen. The mechanism for that already existed and was unused: an activity that is not
# mandatory and whose live preconditions fail is dropped with an `optional_dropped` deviation.
# What was missing is a fact that moves during the day for those preconditions to read.
#
# The level is not stored and ticked; it is derived from when it was last emptied, which is exact,
# costs nothing between checks, and stays deterministic under replay. The interval is drawn once
# per cycle so that a year does not run on one stopwatch.
BLADDER_FILL_MEDIAN_MINUTES = 165.0
BLADDER_FILL_LOG_SIGMA = 0.32
# Everything that leaves the resident relieved, however it is labelled.
_BLADDER_RELIEVING_INTENTS = frozenset(
    {
        "use_toilet",
        "morning_toilet_and_shower",
        "morning_toilet_and_wash",
        "night_toilet_visit",
    }
)

# The moment between one thing and the next.
#
# An activity that has waited for the resident begins the instant she is free, so on a generated
# day eleven of twenty-two activities started in the same second the previous one ended: the run
# came home from a jog and was in the bathroom, then at the breakfast table, then at the medicine
# cabinet, with nothing in between. Read as a replay it is a person being teleported through her
# own morning.
#
# The pause is what a body spends between two things and no plan writes down — putting something
# away, straightening up, deciding. It applies only to an activity that had to queue: one that
# begins at its own scheduled minute was not waiting for anything and gets none.
# It was worth checking that it pays for itself, since seventy seconds twenty times a day is
# twenty minutes and the queue could compound it. Measured with the pause switched off on the same
# two days: every activity kept the minute it already had, so it does not push the day along — the
# time comes out of a gap that was empty anyway. Without it, thirteen of a weekend's activities
# began in the same second the previous one ended.
TRANSITION_PAUSE_MEDIAN_SECONDS = 70.0
TRANSITION_PAUSE_LOG_SIGMA = 0.55
TRANSITION_PAUSE_MAX_SECONDS = 240.0

# How long the resident has to have been doing nothing before an unclaimed-hours filler may take
# the stretch. The planner cannot decide this: it seeds candidates on a grid, but the gaps it can
# see are the plan's, and the ones that matter are the execution's — a Saturday afternoon reads as
# ninety minutes on the day plan and runs to three hours and forty in the trace. So the engine
# decides, from how long she has actually been sitting there.
UNCLAIMED_AFTER_SECONDS = 25 * 60

PUNCTUAL_ACTION_SECONDS = {
    "activate": 3.0,
    "change_posture": 4.0,
    "close": 3.0,
    "deactivate": 3.0,
    "enter_home": 6.0,
    "leave_home": 6.0,
    "move_to": 0.0,
    "move_to_capability": 0.0,
    "open": 3.0,
    "put_item": 6.0,
    "take_item": 6.0,
}


def _gesture_table() -> dict[str, float]:
    """The gesture lengths in force, from the active vocabulary pack.

    `PUNCTUAL_ACTION_SECONDS` above stays as the built-in values the default pack is derived from;
    an author who adds an action states its length there instead of here.
    """
    from smart_home_sim.vocabulary import views
    from smart_home_sim.vocabulary.active import active_pack

    return views.gesture_seconds_table(active_pack())


class SimulationFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        path: str = "$",
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        normalized_details = details or {}
        super().__init__(code, message, path, normalized_details)
        self.code = code
        self.message = message
        self.path = path
        self.details = normalized_details

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
    # Where the body is resting when it is not on the floor: a berth inside the furniture it is on.
    # `position` stays the free-floor anchor it walked to, because that is what routes are planned
    # from and what the router is allowed to hand back.
    resting_at: Point2D | None = None
    execution_state: str = "idle"
    facts: dict[str, JsonValue] = field(default_factory=dict)
    held_resources: set[str] = field(default_factory=set)
    # When the bladder was last emptied, and how many times: the cycle counter is what keeps each
    # interval its own draw. See `BLADDER_FILL_MEDIAN_MINUTES`.
    bladder_emptied_us: int = 0
    bladder_cycles: int = 0
    bladder_full: bool = False
    # When the plan last stopped having anything for her, or None while it does.
    idle_since_us: int | None = None


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
        posture = "lying" if not bool(facts.get("awake", True)) else "standing"
        # The fact store is told the opening posture too, not only the runtime field. Without it
        # the day's first `change_posture` reported its `previousValue` as null — a resident who
        # was asleep in bed read as having come from nowhere.
        facts.setdefault("posture", posture)
        residents[initial.resident_id] = ResidentRuntime(
            resident_id=initial.resident_id,
            region_id=region_id,
            position=position,
            posture=posture,
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
    if fact == "bladder_is_full":
        return _nested(resident.facts, "bladder_full")
    if fact == "the_hours_are_unclaimed":
        return _nested(resident.facts, "hours_unclaimed")
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


def _gesture_seconds(node: ProcessNode) -> float | None:
    """How long this node's gesture takes, or None when the node is elastic."""
    return _gesture_table().get(node.action_type or "")


def _phase_durations(
    phases: list[list[ProcessNode]],
    intended: int,
    gesture_seconds: Callable[[ProcessNode], float | None] = _gesture_seconds,
) -> list[int]:
    """Share an activity's budget over its phases, holding gestures to their own length.

    A phase is elastic when at least one of its nodes is something the activity is *made* of —
    working, eating, sleeping. Those absorb the budget, and `durationWeight` decides how they
    split it between themselves. A phase of pure gestures gets the gesture's length and nothing
    more, so the time it used to swallow goes back to the elastic phases instead of stretching a
    two-second act of sitting down into an hour of it.

    The activity's total is unchanged, which is what keeps the habit ground truth valid across
    this change: only the shape inside the activity moves.

    A process made of nothing but gestures has nothing to absorb anything, so there the budget is
    shared by weight exactly as before — a short process of taps and item handling is the one case
    where stretching the gestures is the only available answer.

    `gesture_seconds` decides how long each gesture is. It defaults to the table, and the engine
    passes one that first asks the resident's own kinematics.
    """
    weights = [max(node.duration_weight or 1 for node in phase) for phase in phases]
    fixed: list[int | None] = []
    for phase in phases:
        seconds = [gesture_seconds(node) for node in phase]
        # A parallel phase is only punctual if every branch in it is: one elastic branch means the
        # phase lasts as long as that branch does.
        fixed.append(
            int(round(max(item for item in seconds if item is not None) * 1_000_000))
            if seconds and all(item is not None for item in seconds)
            else None
        )
    elastic = [index for index, item in enumerate(fixed) if item is None]
    if not elastic:
        total = sum(weights)
        return [max(1, int(round(intended * weight / total))) for weight in weights]
    remaining = max(0, intended - sum(item for item in fixed if item is not None))
    elastic_weight = sum(weights[index] for index in elastic)
    return [
        max(1, item)
        if item is not None
        else max(1, int(round(remaining * weights[index] / elastic_weight)))
        for index, item in enumerate(fixed)
    ]


def trace_semantic_digest(payload: dict[str, Any]) -> str:
    """The authoritative semantic digest of an execution trace payload (by-alias JSON shape)."""
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
        # Flights of stairs, whose length is declared rather than drawn. `_segment_length` reads
        # this so the engine measures a climb the way the router did.
        #
        # Stairways only, deliberately. A transit link also declares a distance — five hundred
        # metres to the supermarket — but it is crossed at eight metres a second rather than
        # walked, so its share of a movement's time is not its share of the distance. Charging it
        # here would change every trace that leaves the house to fix a fault that never involved
        # one, and the invariant it breaks does not care about a walk that ends early.
        self._crossings = {
            frozenset((item.region_a_id, item.region_b_id)): item.distance_meters
            for item in bundle.home_model.connections
            if item.kind is ConnectionKind.stairway and item.distance_meters is not None
        }
        self._points = {
            item.interaction_point_id: item for item in bundle.home_model.interaction_points
        }
        self._entity_at_point = {
            item.interaction_point_id: item
            for item in bundle.home_model.entities
            if item.interaction_point_id
        }
        self._footprints = {
            item.obstacle_id.removeprefix("obstacle_"): Polygon(
                [(vertex.x, vertex.y) for vertex in item.boundary.vertices]
            )
            for item in bundle.home_model.obstacles
        }
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
        # When each resident is next expected somewhere. Filled in `run`, once the day's selection
        # is known: an empty stretch is only empty if nothing is coming, and how long it is decides
        # whether leaving the room is worth the walk.
        self.commitments_by_actor: dict[str, list[int]] = {}
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

    def _paced_duration(self, activity_id: str, intended_us: int) -> int:
        """Scale a planned duration by how fast this execution actually went.

        The plan is the intention, not the stopwatch. Drawing per source activity keeps the run
        deterministic under replay and independent of how many activities precede this one.
        """
        if EXECUTION_PACE_SIGMA <= 0 or intended_us <= 0:
            return intended_us
        stream = self.streams.stream(f"execution-pace:{activity_id}")
        drawn = stream.gauss(0.0, EXECUTION_PACE_SIGMA)
        limit = EXECUTION_PACE_LOG_LIMIT
        factor = math.exp(limit * math.tanh(drawn / limit))
        return max(1, int(round(intended_us * factor)))

    def _gesture_seconds(
        self, activity_id: str, actor_id: str
    ) -> Callable[[ProcessNode], float | None]:
        """How long each gesture takes for *this* resident.

        `change_posture` is the one gesture whose length the bundle already states, per resident and
        per target posture: lying down takes three seconds where standing up takes one and a half.
        The figures travel in `residentKinematics.postureTransitionSeconds`, are validated by the
        home model contract — and were read by nothing until now.
        """
        transitions = self.kinematics[actor_id].posture_transition_seconds

        def resolve(node: ProcessNode) -> float | None:
            fallback = _gesture_table().get(node.action_type or "")
            if node.action_type != "change_posture":
                return fallback
            posture = self.bindings[(activity_id, node.node_id)].resolved_arguments.get("posture")
            return transitions.get(str(posture), fallback)

        return resolve

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

    def _transition_pause(
        self,
        actor: ResidentRuntime,
        requested_us: int,
        cause_id: str,
    ) -> Generator[Any, Any, None]:
        """The breath between two activities, for one that had to wait its turn."""
        if int(self.env.now) <= requested_us:
            return
        stream = self.streams.stream(f"transition-pause:{cause_id}")
        seconds = TRANSITION_PAUSE_MEDIAN_SECONDS * math.exp(
            stream.gauss(0.0, TRANSITION_PAUSE_LOG_SIGMA)
        )
        yield self.env.timeout(int(round(min(seconds, TRANSITION_PAUSE_MAX_SECONDS) * 1_000_000)))

    def _refresh_unclaimed(self, actor: ResidentRuntime, cause_id: str) -> None:
        """Has she been left with nothing for long enough that the stretch wants filling?"""
        idle_for = 0 if actor.idle_since_us is None else int(self.env.now) - actor.idle_since_us
        unclaimed = idle_for >= UNCLAIMED_AFTER_SECONDS * 1_000_000
        if actor.facts.get("hours_unclaimed") == unclaimed:
            return
        previous = actor.facts.get("hours_unclaimed")
        actor.facts["hours_unclaimed"] = unclaimed
        self._state_transition(
            "resident",
            actor.resident_id,
            "hours_unclaimed",
            previous,
            unclaimed,
            "set",
            "plan",
            cause_id,
        )

    def _bladder_fill_us(self, actor: ResidentRuntime) -> int:
        """How long this filling takes, drawn once for this cycle."""
        stream = self.streams.stream(f"bladder:{actor.resident_id}:{actor.bladder_cycles}")
        minutes = BLADDER_FILL_MEDIAN_MINUTES * math.exp(stream.gauss(0.0, BLADDER_FILL_LOG_SIGMA))
        return int(round(minutes * MINUTE_US))

    def _refresh_bladder(self, actor: ResidentRuntime, cause_id: str) -> None:
        """Read the level now, and say so if it has crossed."""
        full = int(self.env.now) - actor.bladder_emptied_us >= self._bladder_fill_us(actor)
        self._set_bladder(actor, full, cause_id)

    def _empty_bladder(self, actor: ResidentRuntime, cause_id: str) -> None:
        actor.bladder_emptied_us = int(self.env.now)
        actor.bladder_cycles += 1
        self._set_bladder(actor, False, cause_id)

    def _set_bladder(self, actor: ResidentRuntime, full: bool, cause_id: str) -> None:
        if actor.bladder_full == full and "bladder_full" in actor.facts:
            return
        previous = actor.facts.get("bladder_full")
        actor.bladder_full = full
        actor.facts["bladder_full"] = full
        self._state_transition(
            "resident",
            actor.resident_id,
            "bladder_full",
            previous,
            full,
            "set",
            "plan",
            cause_id,
        )

    def _set_posture(
        self,
        actor: ResidentRuntime,
        value: str,
        cause_type: str,
        cause_id: str,
    ) -> None:
        """Change the posture in the runtime, in the fact store and in the trace, all three.

        `change_posture` reaches the fact store through the catalog effect and the runtime field
        through `_execute_action`; the engine's own posture changes have no catalog effect to ride
        on and would otherwise update one and not the other.
        """
        if actor.posture == value:
            return
        facts = self.state.residents[actor.resident_id].facts
        previous = facts.get("posture", actor.posture)
        facts["posture"] = value
        actor.posture = value
        self._state_transition(
            "resident",
            actor.resident_id,
            "posture",
            previous,
            value,
            "set",
            cause_type,
            cause_id,
        )
        self._release_berth(actor, cause_id)

    def _set_execution_state(
        self,
        actor: ResidentRuntime,
        value: str,
        cause_type: str,
        cause_id: str,
    ) -> None:
        """Move the resident between idle, moving, performing and interrupted, and say so.

        The field was always maintained; only two of its six assignments were ever written to the
        trace, both inside a movement. So `idle` — which the domain has declared since the first
        contract — appeared nowhere in a year of state transitions, and a resident standing in the
        bathroom for two hours with nothing scheduled was reported as `performing_activity`. A
        reader could not tell an occupied hour from an empty one without reconstructing the
        activity intervals herself, which is the one thing the state stream exists to spare her.
        """
        if actor.execution_state == value:
            return
        previous = actor.execution_state
        actor.execution_state = value
        self._state_transition(
            "resident",
            actor.resident_id,
            "execution_state",
            previous,
            value,
            "set",
            cause_type,
            cause_id,
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
                    details={
                        "activityId": activity.source_activity_id,
                        "residentId": activity.actor_id,
                        "processModelId": binding.process_model_id,
                        "nodeId": node.node_id,
                        "actionType": node.action_type or "",
                        "fact": fact,
                        "operator": operator.value,
                        "expected": precondition.value,
                        "actual": actual if present else "absent",
                    },
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

    def _segment_length(self, left: Any, right: Any) -> float:
        """How far the resident walks between two waypoints, the way the router counted it.

        Measured in plain coordinates this was wrong for exactly one kind of step. A staircase
        joins two storeys that are drawn side by side on one plane, so the gap between its ends is
        a drawing convention: `navigation.plan_path` says so where it charges the flight its
        declared climb instead — "must not be charged to the resident as walking". Recomputing the
        segments here from the coordinates charged it again, eleven metres of page for a climb of
        three, so the accumulated length ran past `path.distance_meters` and every waypoint after
        the flight was stamped beyond the movement's own end.

        The invariant check caught it and refused the whole trace: 276 movements on one authored
        month, every one of them a walk between the two floors, and no run of that home could
        finish. Nothing was wrong with the walk — only with measuring it twice by two rules.
        """
        if left.region_id == right.region_id:
            return math.hypot(right.x - left.x, right.y - left.y)
        crossing = self._crossings.get(frozenset((left.region_id, right.region_id)))
        if crossing is not None:
            return crossing
        return math.hypot(right.x - left.x, right.y - left.y)

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
        if self._within_reach(actor, destination.interaction_point_id):
            return None
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

    def _within_reach(self, actor: ResidentRuntime, interaction_point_id: str) -> bool:
        """Is she sitting at the thing already, so that going to it would mean getting up?

        An interaction point is where a body *stands* to use a piece, so a chair pulled up to a
        desk and the desk itself have points a metre and a half apart — and the resident sat on
        the chair, stood up, walked round to the desk's own point and worked there for eighty
        minutes with the posture still reading `sitting`. The sensor projection put her on the
        chair for the whole block because that is where the berth was, the replay drew her at the
        desk because that is where the movement ended, and the two disagreed about the same hour.

        Measured from the berth to the *footprint*, not between the two standing points, because
        that is the question being asked: not how far apart the two places to stand are, but
        whether what she wants is within arm's length of where she is sitting. Sitting at the desk
        it is 0.27m and at the kitchen table 0.26m; the television across the living room is 5.6m,
        and for that she does get up.
        """
        if actor.resting_at is None:
            return False
        entity = self._entity_at_point.get(interaction_point_id)
        if entity is None:
            return False
        footprint = self._footprints.get(entity.entity_id)
        if footprint is None:
            return False
        return footprint.distance(ShapelyPoint(actor.resting_at.x, actor.resting_at.y)) <= (
            SEATED_REACH_METRES
        )

    def _settling_region(self) -> str | None:
        """The room this dwelling settles in, chosen once from what it actually has."""
        available = {item.region_id for item in self.bundle.home_model.regions}
        return next((item for item in _SETTLING_PREFERENCE if item in available), None)

    def _settling_point(self, region_id: str) -> Any | None:
        """Somewhere to *be* in that room, and a sofa counts for more than a floor.

        The order used to be the other way round — the generated service anchor first — and the
        anchor is the middle of the room. So a resident with nothing to do walked into the centre
        of her sitting room and lay down on the carpet, which is what the replay showed and what a
        room name in a diary cannot. Real furniture first, and among it the things made for
        sitting; the anchor is the backstop it was always meant to be.
        """
        entities = {
            entity.interaction_point_id: entity
            for entity in self.bundle.home_model.entities
            if entity.interaction_point_id
        }
        points = [
            item
            for item in self.bundle.home_model.interaction_points
            if item.region_id == region_id
        ]
        if not points:
            return None

        def rank(item: Any) -> tuple[int, str]:
            entity = entities.get(item.interaction_point_id)
            kind = entity.entity_type if entity is not None else ""
            if kind in _RESTING_FURNITURE:
                return 0, item.interaction_point_id
            if entity is not None and kind != "generated_environment_service":
                return 1, item.interaction_point_id
            return 2, item.interaction_point_id

        points.sort(key=rank)
        return points[0]

    def _is_on_resting_furniture(self, actor: ResidentRuntime, kinds: frozenset[str]) -> bool:
        """Is she actually on something, or just standing in a room that happens to contain one?"""
        for entity in self.bundle.home_model.entities:
            if entity.entity_type not in kinds or entity.region_id != actor.region_id:
                continue
            point = next(
                (
                    item
                    for item in self.bundle.home_model.interaction_points
                    if item.interaction_point_id == entity.interaction_point_id
                ),
                None,
            )
            if point is None:
                continue
            reach = (
                (point.position.x - actor.position.x) ** 2
                + (point.position.y - actor.position.y) ** 2
            ) ** 0.5
            if reach <= point.approach_radius_meters + 0.5:
                return True
        return False

    def _next_commitment(self, actor_id: str, after_us: int) -> int | None:
        """When this resident is next due somewhere, or None if the plan is finished with her."""
        starts = self.commitments_by_actor.get(actor_id, [])
        index = bisect.bisect_right(starts, after_us)
        return starts[index] if index < len(starts) else None

    def _return_from_service_room(
        self,
        actor: ResidentRuntime,
        activity: CanonicalActivity,
        execution_id: str,
        next_us: int | None,
    ) -> Generator[Any, Any, str | None]:
        """Leave the room the activity finished in, when nothing is coming and it is not a room to
        wait in.

        The walk belongs to the activity that just ended, and that is the honest reading as well as
        the one the trace contract allows: finishing a shower includes coming out of the bathroom.
        Nothing new appears in the ground truth, and the resident stops emitting a bathroom's worth
        of presence motion for the two hours that follow.
        """
        if actor.region_id not in _TRANSIENT_REGIONS:
            return None
        if next_us is not None and next_us - self.env.now < IDLE_RETURN_AFTER_SECONDS * 1_000_000:
            return None
        destination = self._settling_region()
        if destination is None or destination == actor.region_id:
            return None
        point = self._settling_point(destination)
        if point is None:
            return None
        kinetics = self.kinematics[actor.resident_id]
        path = plan_path(
            self.bundle.home_model,
            start_region_id=actor.region_id,
            start=actor.position,
            end_region_id=point.region_id,
            end=point.position,
            walking_speed_meters_per_second=kinetics.walking_speed_meters_per_second,
            body_radius_meters=kinetics.body_radius_meters,
            mobility_profile=kinetics.mobility_profile,
        )
        if path is None or path.distance_meters <= 1e-9:
            return None
        action_id = self.trace.identifier(
            "action", [activity.source_activity_id, RETURN_NODE_ID, 0]
        )
        started = self.env.now
        movement_us = int(round(path.duration_seconds * 1_000_000))
        yield from self._travel(actor, path, movement_us, action_id)
        self.trace.actions.append(
            ActionExecution(
                action_execution_id=action_id,
                activity_execution_id=execution_id,
                node_id=RETURN_NODE_ID,
                occurrence_index=0,
                action_type="move_to",
                actor_id=actor.resident_id,
                started_at=_at(self.origin, started),
                ended_at=_at(self.origin, self.env.now),
                status="completed",
                resolved_arguments={"destination": destination},
                provider_ids=[actor.resident_id],
            )
        )
        return action_id

    def _settle(
        self,
        actor: ResidentRuntime,
        cause_id: str,
        until_us: int | None,
    ) -> Generator[Any, Any, None]:
        """Sit down while there is nothing to do, and settle back if the wait is a long one.

        Posture and nothing else, which is what keeps this out of the ground truth: a posture
        change needs no action to hang off, so the gaps stay unlabelled — as they should, since
        nobody planned anything there — while stopping being a log of a person standing still for
        hours. The presence-pulse rate is read from the posture at every pulse, so this is also
        the whole of the correction on the sensor side.
        """
        # A resident who is out is not waiting in a room of ours, and sitting her down in
        # `outdoors` would be a statement about a place the model does not describe.
        if self.state.residents[actor.resident_id].facts.get("at_home") is False:
            return
        horizon_us = _offset(self.origin, self.bundle.scenario.simulation_window.end)
        limit = horizon_us if until_us is None else min(until_us, horizon_us)
        stream = self.streams.stream(f"idle-settle:{cause_id}")
        schedule = [(IDLE_SIT_AFTER_SECONDS, _SITTING_POSTURE)]
        if self._is_on_resting_furniture(actor, _RECLINING_FURNITURE):
            schedule.append((IDLE_RECLINE_AFTER_SECONDS, _RECLINING_POSTURE))
        for seconds, posture in schedule:
            drawn = seconds * math.exp(stream.gauss(0.0, IDLE_SETTLE_LOG_SIGMA))
            delay = int(round(drawn * 1_000_000))
            if self.env.now + delay >= limit:
                return
            yield self.env.timeout(delay)
            # She may have been called away while we waited, and a body the plan is using again is
            # not ours to move.
            if actor.execution_state != "idle":
                return
            if _UPRIGHTNESS[posture] >= _UPRIGHTNESS.get(actor.posture, 2):
                continue
            self._set_posture(actor, posture, "plan", cause_id)

    def _take_a_seat(
        self,
        actor: ResidentRuntime,
        posture: str,
        action_id: str,
    ) -> Generator[Any, Any, None]:
        """Put her on something before she sits or lies down on it.

        A room's anchor is its middle, so without this a night's sleep happened 1.7 metres from
        the bed and an afternoon's reading in the centre of the carpet. The walk is the last two
        metres and is charged to the posture change that needed it.
        """
        kinds = _RECLINING_FURNITURE if posture == _RECLINING_POSTURE else _SEATING_FURNITURE
        lying = posture == _RECLINING_POSTURE
        if self._is_on_resting_furniture(actor, kinds):
            self._settle_onto(actor, kinds, lying=lying, action_id=action_id)
            return
        point = self._furniture_point(actor, kinds)
        if point is None:
            return
        kinetics = self.kinematics[actor.resident_id]
        path = plan_path(
            self.bundle.home_model,
            start_region_id=actor.region_id,
            start=actor.position,
            end_region_id=point.region_id,
            end=point.position,
            walking_speed_meters_per_second=kinetics.walking_speed_meters_per_second,
            body_radius_meters=kinetics.body_radius_meters,
            mobility_profile=kinetics.mobility_profile,
        )
        if path is None or path.distance_meters <= 1e-9:
            return
        yield from self._travel(
            actor, path, int(round(path.duration_seconds * 1_000_000)), action_id
        )
        self._settle_onto(actor, kinds, lying=lying, action_id=action_id)
        self._set_execution_state(actor, "performing_activity", "process_edge", action_id)

    def _sit_back_down(self, actor: ResidentRuntime, action_id: str) -> Generator[Any, Any, None]:
        """Take the body back to the piece it is still recorded as being on.

        Only when it actually left: an action performed within reach of the seat moves nothing, and
        this then has nothing to do. The berth is found from the body rather than remembered,
        because the berth is the only thing that says which piece she is on, and it is what every
        other reader of the trace is already using.
        """
        seat = next(
            (
                entity
                for entity in self.bundle.home_model.entities
                if entity.interaction_point_id
                and entity.region_id == actor.region_id
                and self._footprints.get(entity.entity_id) is not None
                and self._footprints[entity.entity_id].covers(
                    ShapelyPoint(actor.resting_at.x, actor.resting_at.y)
                )
            ),
            None,
        )
        point = self._points.get(seat.interaction_point_id) if seat is not None else None
        if point is None:
            return
        kinetics = self.kinematics[actor.resident_id]
        path = plan_path(
            self.bundle.home_model,
            start_region_id=actor.region_id,
            start=actor.position,
            end_region_id=point.region_id,
            end=point.position,
            walking_speed_meters_per_second=kinetics.walking_speed_meters_per_second,
            body_radius_meters=kinetics.body_radius_meters,
            mobility_profile=kinetics.mobility_profile,
        )
        if path is None or path.distance_meters <= 1e-9:
            return
        yield from self._travel(
            actor, path, int(round(path.duration_seconds * 1_000_000)), action_id, tag="return"
        )
        kinds = _RECLINING_FURNITURE if actor.posture == _RECLINING_POSTURE else _SEATING_FURNITURE
        self._settle_onto(
            actor, kinds, lying=actor.posture == _RECLINING_POSTURE, action_id=action_id
        )

    def _resting_entity(self, actor: ResidentRuntime, kinds: frozenset[str]) -> Any | None:
        """The piece in this room she rests on: the nearest one, then by id to settle a tie.

        By id alone it was whichever piece sorted first, which is a property of its name and not
        of where she is standing. A study holding a desk chair and a reading armchair sat her in
        the armchair to work and then walked her back to the desk, still recorded as sitting; the
        sensor log put her in the armchair for the whole block and the replay drew her at the desk,
        and neither of them was wrong about the trace it was reading. You sit on the seat you are
        next to.
        """
        candidates = [
            entity
            for entity in self.bundle.home_model.entities
            if entity.entity_type in kinds
            and entity.region_id == actor.region_id
            and entity.interaction_point_id
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: (self._reach(actor, item), item.entity_id))

    def _reach(self, actor: ResidentRuntime, entity: Any) -> float:
        """How far the body is from the point it would stand at to use this piece."""
        point = self._points.get(entity.interaction_point_id)
        if point is None:
            return math.inf
        return math.hypot(point.position.x - actor.position.x, point.position.y - actor.position.y)

    def _settle_onto(
        self,
        actor: ResidentRuntime,
        kinds: frozenset[str],
        *,
        lying: bool,
        action_id: str,
    ) -> None:
        """Move the body the last half metre, off the floor and onto the thing itself.

        The walk above ends at the interaction point, which is where a body *stands* to use a
        piece — it has to be, because it is what the router walks to and the router may only put a
        body on free floor. So a night's sleep was still recorded on the carpet beside the bed.

        The berth is inside the footprint on purpose, which is why nothing plans a path to it: this
        is recorded as a movement so that everything reading the trace — the sensor projection's
        dwell, the replay, a reader counting who is where — sees the body where the body is, and it
        takes no time, because lying down is already paid for by the posture change that asked for
        it. `_stand_up` puts her back on the floor before anything tries to route from here.
        """
        entity = self._resting_entity(actor, kinds)
        if entity is None:
            return
        obstacle = next(
            (
                item
                for item in self.bundle.home_model.obstacles
                if item.obstacle_id == f"obstacle_{entity.entity_id}"
            ),
            None,
        )
        if obstacle is None:
            return
        # Which side of the bed is hers. Stable for a resident across a night, and different from
        # the one beside her, which is the whole reason a piece has more than one berth.
        occupant = sorted(self.state.residents).index(actor.resident_id)
        if actor.resting_at is not None:
            return
        target = berth_for(obstacle.boundary, lying=lying, occupant=occupant)
        self._record_berth(actor, target, action_id)

    def _release_berth(self, actor: ResidentRuntime, action_id: str) -> None:
        """Let go of the berth the moment the body stops being on it.

        A berth belongs to a posture, not to a room and not to an activity: she is on the sofa
        because she is sitting, and the instant she is not sitting she is not on it. Stating it
        that way is what closes the hole — `_stand_up` used to be the only thing that cleared one,
        and it does not run on every way a body can end up upright or elsewhere. A plan that ends
        with `change_posture{standing}` set the posture through the catalogue effect and left the
        berth behind, and the body then carried the sofa into the bathroom with it.

        Called wherever either half of the pair can move, so the two cannot disagree.
        """
        if actor.resting_at is None:
            return
        if actor.posture in {_SITTING_POSTURE, _RECLINING_POSTURE}:
            return
        self._record_berth(actor, None, action_id)

    def _rise_from_furniture(self, actor: ResidentRuntime, action_id: str) -> None:
        """Put her back on the floor she is routed from, and say so in the trace.

        Called wherever a body is about to be walked or stood up rather than only where a posture
        changes: `position` is what every route is planned from, and a route that started on a
        berth was refused outright — `route endpoint is outside navigable space in region
        'kitchen'`, which is the invariant doing its job.
        """
        if actor.resting_at is None:
            return
        self._record_berth(actor, None, action_id)

    def _record_berth(
        self,
        actor: ResidentRuntime,
        target: Point2D | None,
        action_id: str,
    ) -> None:
        """Say where the body has come to rest, as a fact about the resident rather than a walk.

        Not a movement, deliberately. A movement's waypoints may not enter an obstacle — the trace
        checks its own work for it, and the rule is right: it is what says a walking body does not
        pass through the furniture. Resting *on* something is a different claim from walking
        *through* it, and it rides on the state stream, which is already how the trace says what a
        body is doing rather than where it is going.
        """
        # The room travels with the berth, so a reader can tell one still in force from one left
        # behind. `_release_berth` is what keeps that from happening at all; this is what lets
        # anything reading the trace check rather than trust.
        previous = (
            None
            if actor.resting_at is None
            else {
                "x": actor.resting_at.x,
                "y": actor.resting_at.y,
                "regionId": actor.region_id,
            }
        )
        value = (
            None if target is None else {"x": target.x, "y": target.y, "regionId": actor.region_id}
        )
        actor.resting_at = target
        # Both stores, as `_set_posture` does for the same reason. A resident fact that reaches the
        # transition stream and not the fact store is a fact the replay can fold and the final state
        # has never heard of, and the frame rebuilt at the end of the trace stops matching the state
        # the run finished in — which is the check that caught this.
        self.state.residents[actor.resident_id].facts["resting_at"] = value
        self._state_transition(
            "resident",
            actor.resident_id,
            "resting_at",
            previous,
            value,
            "set",
            "action_effect",
            action_id,
        )

    def _furniture_point(self, actor: ResidentRuntime, kinds: frozenset[str]) -> Any | None:
        """Where she would stand to get onto the piece `_resting_entity` would put her on."""
        entity = self._resting_entity(actor, kinds)
        if entity is None:
            return None
        return self._points.get(entity.interaction_point_id)

    def _stand_up(
        self,
        actor: ResidentRuntime,
        action_id: str,
    ) -> Generator[Any, Any, None]:
        """Get to her feet, on the budget of the action that needs it."""
        stand_seconds = self.kinematics[actor.resident_id].posture_transition_seconds.get(
            _STANDING_POSTURE, _gesture_table()["change_posture"]
        )
        self._rise_from_furniture(actor, action_id)
        yield self.env.timeout(int(round(stand_seconds * 1_000_000)))
        self._set_posture(actor, _STANDING_POSTURE, "action_effect", action_id)

    def _travel(
        self,
        actor: ResidentRuntime,
        path: NavigationPath,
        movement_us: int,
        action_id: str,
        tag: str | None = None,
    ) -> Generator[Any, Any, None]:
        """Walk the resident along one planned path and record the movement it produced.

        Extracted from `_execute_action` so the engine's own walks — the one that leaves a service
        room when the plan has nothing next — go through the same body, with the same stand-up,
        the same trajectory and the same movement record. The caller owns the execution state
        afterwards, because where the resident is going next is the caller's business.
        """
        # A body that walks is a body that stood up first. Neither `move_to` nor
        # `move_to_capability` carried a posture precondition, so a process model ending in
        # `change_posture{lying}` — which every reading and resting block does — handed the
        # next activity a resident who then crossed the flat without getting off the sofa.
        # Over one generated year that was 2,622 inter-room moves begun `lying`, 37.7% of all
        # of them, and 672 hours spent lying on a kitchen floor. The correction belongs here
        # rather than in the process models because it is a fact about bodies, not about any
        # one routine, and the catalogue is written once per resident.
        #
        # The stand-up is charged to the action that needed it and comes out of that action's
        # own budget: `actual_duration` is unchanged, so the day does not grow by a second and
        # the schedule the compiler solved still holds.
        #
        # Only for a walk that actually goes somewhere. Every action whose provider has an
        # interaction point produces a path, and half of those never leave the room — two metres
        # to the other side of the same table. Standing the resident up for those was wrong twice:
        # a person reaches across a table without getting up, and it stood her up one second after
        # she had sat down to eat, so a twenty-eight minute breakfast was taken on her feet. Read
        # off the replay frames, which is where it shows.
        leaves_the_room = path.waypoints[-1].region_id != actor.region_id
        if leaves_the_room and actor.posture not in _AMBULATORY_POSTURES:
            yield from self._stand_up(actor, action_id)
        self._set_execution_state(actor, "moving", "process_edge", action_id)
        # The walk begins when the walk begins, not when the action did: standing up above
        # already spent part of the action's budget, and back-dating the trajectory to the
        # action's start would put the first waypoint before the posture change that allowed it.
        walk_started = int(self.env.now)
        segment_lengths = [
            self._segment_length(left, right)
            for left, right in zip(path.waypoints, path.waypoints[1:], strict=False)
        ]
        accumulated = 0.0
        waypoints = [
            TrajectoryWaypoint(
                at=_at(self.origin, walk_started),
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
                    at=_at(self.origin, walk_started + movement_us * fraction),
                    region_id=waypoint.region_id,
                    position=Point2D(x=waypoint.x, y=waypoint.y),
                    traversal_mode=waypoint.traversal_mode,
                )
            )
        yield self.env.timeout(movement_us)
        destination = path.waypoints[-1]
        origin_region = actor.region_id
        if actor.resting_at is not None and destination.region_id != origin_region:
            # A body cannot be on the sofa and in the bathroom. Posture is what normally lets a
            # berth go; this is the backstop for anything that walks out of the room without it.
            self._record_berth(actor, None, action_id)
        actor.region_id = destination.region_id
        actor.position = Point2D(x=destination.x, y=destination.y)
        self.trace.movements.append(
            MovementExecution(
                # An action may walk twice — out to something out of reach and back to the seat
                # it left — and a movement id derived from the action alone then collides with
                # itself. The tag names which of the two this is.
                movement_id=self.trace.identifier(
                    "movement", [action_id] if tag is None else [action_id, tag]
                ),
                action_execution_id=action_id,
                actor_id=actor.resident_id,
                started_at=_at(self.origin, walk_started),
                ended_at=_at(self.origin, self.env.now),
                origin_region_id=origin_region,
                destination_region_id=actor.region_id,
                distance_meters=path.distance_meters,
                duration_microseconds=movement_us,
                waypoints=waypoints,
            )
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
        if node.action_type in _UPRIGHT_ACTIONS and actor.posture not in _AMBULATORY_POSTURES:
            yield from self._stand_up(actor, action_id)
        if node.action_type == "change_posture":
            target = str(binding.resolved_arguments.get("posture", ""))
            if target in {_SITTING_POSTURE, _RECLINING_POSTURE}:
                yield from self._take_a_seat(actor, target, action_id)
        path = self._movement(binding, action_id, actor)
        # A seated body does not get up to reach something on the same side of the same room. The
        # binder walks her to whichever provider answers, which for `consume` is whatever holds the
        # food: she sat down at the table and was then taken to the refrigerator to eat.
        if (
            path is not None
            and actor.posture not in _AMBULATORY_POSTURES
            and path.waypoints[-1].region_id == actor.region_id
            and any(item.role == _ITEM_ROLE for item in binding.capability_bindings)
        ):
            path = None
        movement_us = int(round((path.duration_seconds if path else 0) * 1_000_000))
        actual_duration = max(duration_us, movement_us)
        if path and path.distance_meters > 1e-9:
            yield from self._travel(actor, path, movement_us, action_id)
            self._set_execution_state(actor, "performing_activity", "process_edge", action_id)
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
                self._set_execution_state(
                    actor, "interrupted", "runtime_event", payload["event_id"]
                )
                yield self.env.timeout(payload["duration_us"])
                self._set_execution_state(
                    actor, "performing_activity", "runtime_event", payload["event_id"]
                )
        # She got up to reach something out of arm's length, and then stayed standing at it. The
        # berth survives a walk that does not leave the room, so the trace went on saying she was
        # sitting on the sofa while the body stood at the television for the thirty-one minutes she
        # watched it — the sensor log read the berth and the replay read the movement, and the two
        # described different evenings. Pressing a button is not the end of sitting down: what a
        # person does next is sit back down, and this is that walk.
        if (
            path is not None
            and actor.resting_at is not None
            and node.action_type != "change_posture"
        ):
            yield from self._sit_back_down(actor, action_id)
        if node.action_type == "change_posture":
            # Only the runtime field is set here. The transition is left to the catalog effect
            # below — `change_posture` declares `resident.posture := {posture}` — because writing it
            # in both places wrote it to the trace twice: two ids, one moment, one cause, ten of ten
            # posture changes on a generated day. A reader counting how often the resident sat down
            # got double, and the pair disagreed about where she had been, the fact store having
            # never been told her opening posture.
            actor.posture = str(binding.resolved_arguments["posture"])
            self._release_berth(actor, action_id)
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
            yield from self._transition_pause(
                self.state.residents[actor_id], requested_us, activity.source_activity_id
            )
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
            # Read before the preconditions, because two of them are about to ask.
            self._refresh_bladder(self.state.residents[actor_id], execution_id)
            self._refresh_unclaimed(self.state.residents[actor_id], execution_id)
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
            actor.idle_since_us = None
            self._set_execution_state(actor, "performing_activity", "plan", execution_id)
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
            intended = self._paced_duration(
                activity.source_activity_id,
                activity.duration_microseconds + self.extension_us[activity.source_activity_id],
            )
            phase_durations = _phase_durations(
                phases, intended, self._gesture_seconds(activity.source_activity_id, actor_id)
            )
            occurrences: Counter[str] = Counter()
            action_ids: list[str] = []
            self.active_processes[actor_id] = self.env.active_process
            for phase, duration_us in zip(phases, phase_durations, strict=True):
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
                            self._set_execution_state(
                                actor, "interrupted", "resource", execution_id
                            )
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
                            self._set_execution_state(
                                actor, "performing_activity", "resource", execution_id
                            )
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
                        self._set_execution_state(
                            actor, "interrupted", "runtime_event", payload["event_id"]
                        )
                        yield self.env.timeout(payload["duration_us"])
                        self._set_execution_state(
                            actor, "performing_activity", "runtime_event", payload["event_id"]
                        )
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
            if activity.intent in _BLADDER_RELIEVING_INTENTS:
                self._empty_bladder(actor, execution_id)
            next_us = self._next_commitment(actor_id, int(self.env.now))
            returned = yield from self._return_from_service_room(
                actor, activity, execution_id, next_us
            )
            if returned is not None:
                action_ids.append(returned)
            actor.idle_since_us = int(self.env.now)
            self._set_execution_state(actor, "idle", "plan", execution_id)
            # Not held while it runs: the waiting owns no lock, so the next activity takes the
            # resident back the moment it is due and `_settle` simply finds her busy and stops.
            self.env.process(self._settle(actor, execution_id, next_us))
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
        for item in activities:
            planned = _offset(self.origin, item.scheduled_start)
            self.commitments_by_actor.setdefault(item.actor_id, []).append(
                planned + self.delay_us[item.source_activity_id]
            )
        for starts in self.commitments_by_actor.values():
            starts.sort()
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
            semantic_digest=trace_semantic_digest(base),
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
    if trace.semantic_digest != trace_semantic_digest(payload):
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
                details=error.details,
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
