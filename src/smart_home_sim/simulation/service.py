from __future__ import annotations

import bisect
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Generator, Iterable
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import simpy
from pydantic import JsonValue, ValidationError
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon

from smart_home_sim.behavior.service import (
    _condition_matches,
    default_variable_catalog_path,
    load_action_catalog,
)
from smart_home_sim.clock import localised
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.behavior import (
    EffectOperation,
    ProcessEdge,
    ProcessModel,
    ProcessNode,
    ProcessNodeKind,
    ValueSource,
    VariableCatalog,
    VariableCondition,
)
from smart_home_sim.domain.environment import (
    ConnectionKind,
    Point2D,
    RegionKind,
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
    semantic_activity_executions,
)
from smart_home_sim.domain.hands import CARRYING_PREFIX, carried_role, portable_minutes
from smart_home_sim.domain.models import (
    PRIVACY_EXTENSION,
    Condition,
    ConditionOperator,
    RuntimeEventOperation,
    StateEffect,
)
from smart_home_sim.domain.plan import CanonicalActivity
from smart_home_sim.environment.navigation import NavigationPath, plan_path
from smart_home_sim.environment.occupancy import berth_for, berths
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
# How a body gets up to speed, and why a walk is not its distance over a cruising speed.
#
# Every one of the 8,131 movements of the five-month export was walked at exactly 1.20 m/s: p05,
# median and p95 all the same number, because the duration was distance over the one speed the home
# model declares. That is not only inhuman -- nobody crosses a kitchen at the pace they take a
# hallway -- it is *structural*, because it makes the time a body spends inside a detector's cone a
# deterministic function of the geometry of its path. Every crossing of one doorway then produces
# the same signature, which is one of the things holding the log's 3-gram entropy at 6.87 against
# CASAS Aruba's 9.44.
#
# A real walk accelerates to a cruising speed and decelerates out of it, and across a flat most
# walks are too short to spend much time in between: the median is 2.37 m. With a trapezoid profile
# the trip costs `distance / cruise + cruise / acceleration`, and a walk shorter than
# `cruise^2 / acceleration` never reaches cruise at all and costs `2 * sqrt(distance /
# acceleration)`. The effective speed then falls out of the distance rather than being declared:
# 0.44 m/s over three quarters of a metre, 0.75 over the median, 1.09 over the longest walks of the
# flat. 1.0 m/s^2 sits inside the range gait-initiation studies report for healthy adults, who reach
# steady state in two or three steps.
GAIT_ACCELERATION_METRES_PER_SECOND_SQUARED = 1.0
# And one walk differs from the next. Same shape as the execution pace above and for the same
# reason: lognormal so the declared speed stays the central tendency, tanh-squashed rather than
# clamped so extreme draws do not pile onto one factor.
GAIT_SPEED_SIGMA = 0.12
GAIT_SPEED_LOG_LIMIT = 0.30


def _walk_seconds(path: NavigationPath, cruise_speed: float) -> float:
    """How long this path takes a body walking at `cruise_speed`, accelerating into it and out.

    The transport part of a path is not walked -- it is five hundred metres of street crossed at the
    frozen urban speed -- so it keeps the duration the router gave it and only the walked metres go
    through the gait profile.
    """
    acceleration = GAIT_ACCELERATION_METRES_PER_SECOND_SQUARED
    walked = path.walking_distance_meters
    carried = max(0.0, path.duration_seconds - walked / cruise_speed) if cruise_speed > 0 else 0.0
    if walked <= 0:
        return carried
    if acceleration <= 0:
        return carried + walked / cruise_speed
    # Below this the profile is a triangle: the body is still speeding up when it has to start
    # slowing down, and never touches the cruising speed at all.
    without_cruising = cruise_speed**2 / acceleration
    if walked < without_cruising:
        return carried + 2 * math.sqrt(walked / acceleration)
    return carried + walked / cruise_speed + cruise_speed / acceleration


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
#
# The built-in values the default vocabulary pack is derived from; the engine reads the pack
# (`_upright_actions`), so an action an author adds says there whether it needs the resident up.
UPRIGHT_ACTION_TYPES = frozenset(
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
_RECLINING_FURNITURE = frozenset({"sofa", "bed", "single_bed", "recliner", "daybed"})
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
# The engine's own actions for a resident taking part in an activity somebody else performs:
# the walk to where it happens, the posture she holds there, and getting up when it is over.
# The actor's process model is hers alone — it is the cooking and the serving — so a
# participant has no authored node to hang these on, exactly as the walk out of a service room
# has none.
JOIN_NODE_ID = "engine_join_shared_activity"
JOIN_POSTURE_NODE_ID = "engine_join_shared_activity_posture"
LEAVE_POSTURE_NODE_ID = "engine_leave_shared_activity_posture"
JOIN_EGRESS_NODE_ID = "engine_join_shared_activity_leave_home"
LEAVE_INGRESS_NODE_ID = "engine_leave_shared_activity_enter_home"
# How long an actor, once free, holds herself for the others a shared activity names. Unbounded,
# one wait froze a whole household: a television evening planned for 21:58 held Giulia from 00:27
# while Paolo slept, she stood in the kitchen until 10:04, and the day after began eleven hours
# late — her next two shifts started four hours behind. Of the 93 shared activities that month, 19
# waited past a quarter of an hour after the actor was free, 9 past half an hour and 2 past the
# hour, and those two were the frozen ones. Past this an optional one is given up and a mandatory
# one goes ahead with whoever came.
SHARED_WAIT_LIMIT_SECONDS = 60 * 60
# The regions a resident has to go out of the front door to be in.
_OUTSIDE_REGION_KINDS = frozenset({RegionKind.external, RegionKind.transit})
# The capabilities of the front door, which says nothing about where the activity itself happens.
_ENTRANCE_CAPABILITIES = frozenset({"home_egress", "home_ingress"})
# Two away activities of one resident planned this close are one outing, not two. Every away model
# is a round trip — the authoring contract requires it, because a model that leaves without
# returning leaves `at_home` stuck — and the contract also writes a night shift as two commitments
# either side of midnight and a commute as its own commitment before the shift. Executed as
# written, Giulia went to work at 06:35, came back in through the front door at 07:02, left again
# at 07:04 and walked the 500 metres in a minute; on a night shift she came home at 00:10 for two
# minutes. The engine joins such a pair: the first activity keeps everything up to its return, the
# second everything after its departure. The commute ends on the hour the shift starts, the two
# halves of a shift a minute apart, and the compiler moves a commitment by at most a quarter hour.
OUTING_CONTINUATION_GAP_SECONDS = 15 * 60

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


def _upright_actions() -> frozenset[str]:
    """The actions a body must be on its feet for, from the active vocabulary pack."""
    from smart_home_sim.vocabulary import views
    from smart_home_sim.vocabulary.active import active_pack

    return views.upright_action_types(active_pack())


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
    # What is in her hands, by role: the pick-up it came from, so a timer can tell whether the
    # thing it was set for is still the thing she holds; the pick-ups a timer already watches; and
    # what ran past its time while an activity held her. See `smart_home_sim.domain.hands`.
    carry_stamps: dict[str, int] = field(default_factory=dict)
    carry_timers: dict[str, int] = field(default_factory=dict)
    overdue_roles: set[str] = field(default_factory=set)
    # The away activity she is still out for, when the last one ended without bringing her home.
    # See `OUTING_CONTINUATION_GAP_SECONDS`.
    outing_continues_into: str | None = None


@dataclass
class RuntimeState:
    residents: dict[str, ResidentRuntime]
    entity_states: dict[str, dict[str, JsonValue]]
    environment_facts: dict[str, JsonValue]
    capability_facts: dict[str, JsonValue]
    invalidated_facts: set[str] = field(default_factory=set)
    completed_activities: set[str] = field(default_factory=set)


@dataclass
class _RoomUse:
    """A running activity, as far as the privacy of its rooms is concerned."""

    occupying: frozenset[str]
    rooms: frozenset[str]
    excluded: frozenset[str]
    done: simpy.Event


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


def _at(origin: datetime, microseconds: int | float, zone: ZoneInfo) -> datetime:
    return localised(origin + timedelta(microseconds=int(round(microseconds))), zone)


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


def _without_return(phases: list[list[ProcessNode]]) -> list[list[ProcessNode]]:
    """The phases before the last `enter_home`: the outing, without coming back from it."""
    index = max(
        (i for i, phase in enumerate(phases) if any(n.action_type == "enter_home" for n in phase)),
        default=None,
    )
    return phases if index is None or index == 0 else phases[:index]


def _without_departure(phases: list[list[ProcessNode]]) -> list[list[ProcessNode]]:
    """The phases after the first `leave_home`: the outing, for somebody who is already out."""
    index = next(
        (i for i, phase in enumerate(phases) if any(n.action_type == "leave_home" for n in phase)),
        None,
    )
    return phases if index is None or index == len(phases) - 1 else phases[index + 1 :]


# What a body does sitting down, when the process says nothing else — the reference models sit for
# all of them. `perform_work` only when the work is not a shift somewhere else, and `wait` only
# when it is rest.
_SEDENTARY_ACTIONS = frozenset({"consume", "leisure", "communicate"})
# Gestures made from wherever the body already is, looked past to find what it is getting ready for:
# the remote comes before the television.
_FROM_THE_SEAT = frozenset({"activate", "deactivate"})


def _is_sedentary(node: ProcessNode) -> bool:
    def literal(name: str) -> object:
        expression = node.arguments.get(name)
        if expression is None or expression.source is not ValueSource.literal:
            return None
        return expression.value

    if node.action_type in _SEDENTARY_ACTIONS:
        return True
    if node.action_type == "perform_work":
        mode = literal("mode")
        return mode is not None and mode != "shift"
    return node.action_type == "wait" and literal("purpose") == "rest"


def _sits_down_where_written_standing(model: ProcessModel) -> set[str]:
    """The `change_posture(standing)` nodes that are how this model sits down.

    The authoring contract shows a meal as `change_posture(sitting) -> consume ->
    change_posture(standing)`, and every reference model is written that way. The Ferri package
    wrote `standing` in both places, for every meal, every book and every television evening of
    both residents: 1,079 posture changes in a month, not one of them sitting, meals eaten on foot
    in front of the refrigerator and a table and two chairs nobody used. A stand-up immediately
    before something done seated says nothing about standing — the body is up already — and is read
    as the sit-down the contract puts there. Anything after the sedentary action is left alone.
    """
    nodes = {node.node_id: node for node in model.nodes}
    successors: defaultdict[str, list[str]] = defaultdict(list)
    for edge in model.edges:
        successors[edge.source_node_id].append(edge.target_node_id)
    found: set[str] = set()
    for node in model.nodes:
        expression = node.arguments.get("posture")
        if (
            node.action_type != "change_posture"
            or expression is None
            or expression.source is not ValueSource.literal
            or expression.value != _STANDING_POSTURE
        ):
            continue
        current = node.node_id
        while True:
            following = successors.get(current, [])
            if len(following) != 1 or following[0] not in nodes:
                break
            current = following[0]
            if nodes[current].action_type not in _FROM_THE_SEAT:
                break
        if current != node.node_id and _is_sedentary(nodes[current]):
            found.add(node.node_id)
    return found


def _shared_postures(model: ProcessModel) -> tuple[str | None, str | None]:
    """The posture an activity is spent in, and the one it ends in, read off its process model.

    A participant has no model of her own for somebody else's activity, and inventing one per intent
    would be a second catalogue to keep in step with the first. The actor's model already says it:
    a meal sits down, eats and stands up; an evening in front of the television sits down and stays
    there. The first posture that is not upright is how the activity is spent; the last one is how
    it ends.
    """
    postures = [
        str(node.arguments["posture"].value)
        for node in model.nodes
        if node.action_type == "change_posture"
        and "posture" in node.arguments
        and node.arguments["posture"].source is ValueSource.literal
    ]
    held = next((item for item in postures if item not in _AMBULATORY_POSTURES), None)
    return held, (postures[-1] if postures else None)


def trace_semantic_digest(payload: dict[str, Any]) -> str:
    """The authoritative semantic digest of an execution trace payload (by-alias JSON shape)."""
    payload = {
        **payload,
        "activityExecutions": semantic_activity_executions(payload["activityExecutions"]),
    }
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
        self.zone = ZoneInfo(bundle.scenario.time_zone)
        # Normalised as well as read: the window start carries whatever offset its author wrote,
        # and every timestamp in the trace is measured from it.
        self.origin = localised(bundle.scenario.simulation_window.start, self.zone)
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
        self.action_catalog = load_action_catalog(
            bundle.behavior_package.catalogs.action_catalog.version
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
        self._sit_where_written_standing()
        self.kinematics = {item.resident_id: item for item in bundle.resident_kinematics}
        # Queued by when each activity was due, not by when it reached the queue. The two used to be
        # the same thing: a resident's own activities ask for her at their own minute. A shared one
        # asks for its participants only once the actor is free, and first-come put it behind
        # everything they had queued in the meantime — a television evening planned for 21:58 went
        # in behind a bedtime planned for 23:49.
        self.actor_locks = {
            item.resident_id: simpy.PriorityResource(self.env, capacity=1)
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
        # Which away activity each away activity hands its resident on to, without her coming home
        # in between. Filled in `run`. See `OUTING_CONTINUATION_GAP_SECONDS`.
        self.outing_continuations: dict[str, str] = {}
        # Who each activity empties its rooms of, as the scenario declares it, and the activities
        # running now. See `_privacy_conflicts`.
        residents = {item.resident_id for item in bundle.scenario.residents}
        self.exclusions: dict[str, frozenset[str]] = {
            activity.activity_id: frozenset(
                item
                for item in activity.extensions.get(PRIVACY_EXTENSION) or []
                if isinstance(item, str) and item in residents
            )
            for day in bundle.scenario.days
            for activity in day.activities
            if isinstance(activity.extensions.get(PRIVACY_EXTENSION), list)
        }
        self.room_uses: dict[str, _RoomUse] = {}
        self.horizon_end_us = _offset(self.origin, bundle.scenario.simulation_window.end)
        # Pick-ups, numbered in the order they happen, and the roles each running activity consumed.
        self.carry_counter = 0
        self.consumed_roles: defaultdict[str, set[str]] = defaultdict(set)
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

    def _walk_microseconds(
        self, actor: ResidentRuntime, path: NavigationPath, action_id: str
    ) -> int:
        """How long *this* walk takes this body.

        Drawn per walk rather than per resident, and keyed on the action that owns it so the run
        stays reproducible under replay and independent of how many walks precede this one -- the
        same rule `_execution_microseconds` follows for the length of an activity.
        """
        cruise = self.kinematics[actor.resident_id].walking_speed_meters_per_second
        if GAIT_SPEED_SIGMA > 0:
            drawn = self.streams.stream(f"gait:{action_id}").gauss(0.0, GAIT_SPEED_SIGMA)
            limit = GAIT_SPEED_LOG_LIMIT
            cruise *= math.exp(limit * math.tanh(drawn / limit))
        return max(1, int(round(_walk_seconds(path, cruise) * 1_000_000)))

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

    def _event_subject(self, candidate: Any) -> str:
        """The resident an event's preconditions are about: whoever does what it acts on.

        A resident-scoped precondition — is she at home, is she awake — was read off the first
        resident in the scenario whoever the event touched, so in a shared house an event delaying
        one person's shower asked whether the other person was at home. The activity it is triggered
        by, or failing that the first one it targets, names the right body; an event about the
        house and nobody in particular still reads the first resident, as it always did.
        """
        actors = {
            item.source_activity_id: item.actor_id
            for day in self.bundle.canonical_plan.days
            for item in day.activities
        }
        for activity_id in (
            candidate.trigger_activity_id,
            *(effect.target_id for effect in candidate.effects),
        ):
            if activity_id in actors:
                return actors[activity_id]
        return next(iter(self.state.residents))

    def _runtime_event_process(self, candidate: Any) -> Generator[Any, Any, None]:
        prepared = self.prepared_events[candidate.event_id]
        if candidate.trigger_activity_id is None:
            yield self.env.timeout(max(0, prepared.at_us - self.env.now))
        else:
            yield self.activity_start_events[candidate.trigger_activity_id]
        outcome = "not_sampled"
        if prepared.occurred:
            actor_id = self._event_subject(candidate)
            day = self._day_for(_at(self.origin, self.env.now, self.zone).date())
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
                evaluated_at=_at(self.origin, self.env.now, self.zone),
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
                at=_at(self.origin, self.env.now, self.zone),
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
                at=_at(self.origin, self.env.now, self.zone),
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
        if subject_type == "resident" and value is True and carried_role(path) is not None:
            self.carry_counter += 1
            holder = self.state.residents[actor_id]
            holder.carry_stamps[path.removeprefix(CARRYING_PREFIX)] = self.carry_counter
            holder.overdue_roles.discard(path.removeprefix(CARRYING_PREFIX))
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

    def _set_down(self, actor: ResidentRuntime, role: str, cause_id: str) -> None:
        """Her hands let go of `role`, which the process model itself never put down."""
        fact = f"{CARRYING_PREFIX}{role}"
        actor.carry_stamps.pop(role, None)
        actor.carry_timers.pop(role, None)
        actor.overdue_roles.discard(role)
        if actor.facts.get(fact) is not True:
            return
        actor.facts[fact] = False
        self._state_transition(
            "resident", actor.resident_id, fact, True, False, "set", "plan", cause_id
        )

    def _put_things_back(
        self, actor: ResidentRuntime, activity_id: str | None, execution_id: str
    ) -> None:
        """The end of an activity is where what it handled is put back or carried on.

        Anything not portable goes back now, and so does a portable thing she consumed here — the
        cup once the coffee is drunk. What is left, the coffee still to drink, is carried on under a
        timer; and whatever a timer found overdue while an activity held her goes down now.
        `activity_id` is None for a resident who only took part in someone else's activity: she
        handled nothing in it, and only what is overdue is hers to put down.
        """
        consumed = self.consumed_roles.pop(activity_id, set()) if activity_id else set()
        carried = sorted(
            role
            for fact, value in actor.facts.items()
            if value is True and (role := carried_role(fact)) is not None
        )
        for role in carried:
            stamp = actor.carry_stamps.get(role, 0)
            minutes = portable_minutes(role)
            if role in actor.overdue_roles or (
                activity_id is not None and (minutes is None or role in consumed)
            ):
                # One microsecond on, not now: a `take_item` that was the activity's last step
                # happened at this same instant, and the trace orders equal instants by id, so a
                # set-down written now could be read back as coming before the pick-up it undoes.
                actor.carry_timers[role] = stamp
                self.env.process(self._set_down_after(actor, role, stamp, 1, execution_id, False))
            elif minutes is not None and actor.carry_timers.get(role) != stamp:
                actor.carry_timers[role] = stamp
                self.env.process(
                    self._set_down_after(
                        actor, role, stamp, int(round(minutes * MINUTE_US)), execution_id, True
                    )
                )

    def _set_down_after(
        self,
        actor: ResidentRuntime,
        role: str,
        stamp: int,
        delay_us: int,
        cause_id: str,
        waits_for_activity: bool,
    ) -> Generator[Any, Any, None]:
        """Set `role` down after `delay_us`, unless it has been put down or picked up again since.

        A portable thing whose time runs out in the middle of another activity is not taken from her
        hands there: a process model may still be about to put it away, and taking it first would
        fail that `put_item`. It is marked overdue and goes down when that activity ends.
        """
        yield self.env.timeout(delay_us)
        if (
            actor.carry_stamps.get(role, 0) != stamp
            or actor.facts.get(f"{CARRYING_PREFIX}{role}") is not True
        ):
            return
        if waits_for_activity and self.actor_locks[actor.resident_id].count:
            actor.overdue_roles.add(role)
            return
        self._set_down(actor, role, cause_id)

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
        occurrence: int | str = 0,
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
        # A shared activity sends every participant out of the room it ended in, and an
        # identifier derived from the activity alone would name all of their walks the same.
        action_id = self.trace.identifier(
            "action", [activity.source_activity_id, RETURN_NODE_ID, occurrence]
        )
        started = self.env.now
        movement_us = self._walk_microseconds(actor, path, action_id)
        yield from self._travel(actor, path, movement_us, action_id)
        # The action is written here rather than through `_execute_action`, so the catalog effects
        # it declares have to be applied here too. `move_to` declares exactly one —
        # `resident.location := {destination}` — and skipping it left the fact saying `bathroom`
        # for every minute after a shower: over five months 1,466 of 12,080 stationary stretches,
        # 18,585 minutes, had the resident recorded in a room her own waypoints had already left.
        # Anything reading the trace by location rather than by trajectory believed it.
        self._apply_move_effects(actor, destination, action_id)
        self.trace.actions.append(
            ActionExecution(
                action_execution_id=action_id,
                activity_execution_id=execution_id,
                node_id=RETURN_NODE_ID,
                occurrence_index=0,
                action_type="move_to",
                actor_id=actor.resident_id,
                started_at=_at(self.origin, started, self.zone),
                ended_at=_at(self.origin, self.env.now, self.zone),
                status="completed",
                resolved_arguments={"destination": destination},
                provider_ids=[actor.resident_id],
            )
        )
        return action_id

    def _apply_move_effects(self, actor: ResidentRuntime, destination: str, action_id: str) -> None:
        """Apply what the catalog says a `move_to` does, for a walk the catalog never routed.

        Read from the action definition rather than written out, so the engine's own walk and an
        authored one can never come to mean different things.
        """
        definition = self.action_definitions["move_to"]
        arguments = {"destination": destination}
        for template in definition.effects:
            value = (
                template.value.format(**arguments)
                if isinstance(template.value, str)
                else template.value
            )
            self._apply_effect(
                StateEffect(
                    fact=template.fact_template.format(**arguments),
                    operation=template.operation,
                    value=value,
                ),
                actor.resident_id,
                action_id,
            )

    def _settle(
        self,
        actor: ResidentRuntime,
        cause_id: str,
        until_us: int | None,
        stream_key: str = "",
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
        # Two people leaving one dinner are two people settling, not one person drawn twice.
        stream = self.streams.stream(f"idle-settle:{cause_id}{stream_key}")
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
            actor, path, self._walk_microseconds(actor, path, action_id), action_id
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
            actor, path, self._walk_microseconds(actor, path, action_id), action_id, tag="return"
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
        # A chair somebody else is sitting on is not a seat. With one resident no piece is ever
        # taken and this changes nothing; with two, the nearest chair to the second body at the
        # table is the one the first is already on, and `berth_for` wraps rather than refuses, so
        # both bodies were put on the same point. A piece with room left — the other half of a
        # sofa, the other side of a bed — is still offered, which is the case berths exist for.
        lying = kinds is _RECLINING_FURNITURE
        free = [item for item in candidates if not self._piece_is_full(actor, item, lying=lying)]
        return min(free or candidates, key=lambda item: (self._reach(actor, item), item.entity_id))

    def _piece_is_full(self, actor: ResidentRuntime, entity: Any, *, lying: bool) -> bool:
        """Whether the piece already holds as many other bodies as it has places."""
        obstacle = next(
            (
                item
                for item in self.bundle.home_model.obstacles
                if item.obstacle_id == f"obstacle_{entity.entity_id}"
            ),
            None,
        )
        if obstacle is None:
            return False
        shape = Polygon([(point.x, point.y) for point in obstacle.boundary.vertices])
        others = sum(
            1
            for other in self.state.residents.values()
            if other.resident_id != actor.resident_id
            and other.resting_at is not None
            and other.region_id == entity.region_id
            and shape.covers(ShapelyPoint(other.resting_at.x, other.resting_at.y))
        )
        return others >= len(berths(obstacle.boundary, lying=lying))

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
        #
        # The exemption belongs to a *seated* body, though, and saying only `leaves_the_room` gave
        # it to a lying one as well: on one five-month export 380 of 8,131 movements were walked
        # with the posture reading `lying`, all of them inside a single room, the longest 2.58 m.
        # Reaching across the table without getting up is a person; crossing two and a half metres
        # of floor without getting off the bed is two channels of the model contradicting each
        # other. Nothing is within reach of a body lying down — `_within_reach` has already
        # returned every genuine reach as no path at all — so a walk that survives to here while
        # lying is a walk, and it starts by standing up.
        leaves_the_room = path.waypoints[-1].region_id != actor.region_id
        if actor.posture not in _AMBULATORY_POSTURES and (
            leaves_the_room or actor.posture == _RECLINING_POSTURE
        ):
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
                at=_at(self.origin, walk_started, self.zone),
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
                    at=_at(self.origin, walk_started + movement_us * fraction, self.zone),
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
                started_at=_at(self.origin, walk_started, self.zone),
                ended_at=_at(self.origin, self.env.now, self.zone),
                origin_region_id=origin_region,
                destination_region_id=actor.region_id,
                distance_meters=path.distance_meters,
                duration_microseconds=movement_us,
                waypoints=waypoints,
            )
        )

    def _shared_region(self, activity: CanonicalActivity) -> str | None:
        """The room a participant has to be in: the one the actor's own providers are in.

        Read from the binding rather than from the activity's declared location, because the table
        a meal is eaten at is whatever the home put the `consumption_area` in, and a participant
        sent to the room the catalog names would sit down in the kitchen while the actor ate in the
        living room.

        The front door is not where anything happens. An outing opens with `leave_home`, bound to
        the door in the living room, and reading that first sent the participant of every Saturday
        shop to the living room: five Saturdays out of five Paolo "bought groceries" on the sofa
        while Giulia was at the supermarket. Skipped as a provider rather than as an action, because
        a model that first walks to the door (`move_to_capability{home_exit}`) names it too.
        """
        regions = {item.region_id for item in self.bundle.home_model.regions}
        entities = {
            item.entity_id: item
            for item in self.bundle.home_model.entities
            if not any(offer.capability in _ENTRANCE_CAPABILITIES for offer in item.capabilities)
        }
        model = self.models[self._process_model_id(activity.source_activity_id)]
        for node in model.nodes:
            binding = self.bindings.get((activity.source_activity_id, node.node_id))
            if binding is None:
                continue
            for item in binding.capability_bindings:
                entity = entities.get(item.provider_id)
                if entity is not None and entity.region_id in regions:
                    return str(entity.region_id)
        return next((item for item in activity.location_ids if item in regions), None)

    def _record_engine_action(
        self,
        actor: ResidentRuntime,
        execution_id: str,
        action_id: str,
        node_id: str,
        action_type: str,
        started_us: float,
        arguments: dict[str, JsonValue],
        provider_ids: list[str] | None = None,
    ) -> None:
        self.trace.actions.append(
            ActionExecution(
                action_execution_id=action_id,
                activity_execution_id=execution_id,
                node_id=node_id,
                occurrence_index=0,
                action_type=action_type,
                actor_id=actor.resident_id,
                started_at=_at(self.origin, started_us, self.zone),
                ended_at=_at(self.origin, self.env.now, self.zone),
                status="completed",
                resolved_arguments=arguments,
                provider_ids=provider_ids if provider_ids is not None else [actor.resident_id],
            )
        )

    def _is_outside(self, region_id: str) -> bool:
        return any(
            item.region_id == region_id and item.kind in _OUTSIDE_REGION_KINDS
            for item in self.bundle.home_model.regions
        )

    def _cross_front_door(
        self,
        participant: ResidentRuntime,
        activity: CanonicalActivity,
        execution_id: str,
        action_type: str,
        node_id: str,
    ) -> Generator[Any, Any, str | None]:
        """Take a participant through the door the actor went through, the way the actor did.

        The door is the actor's: her `leave_home` or `enter_home` binding names it and says where to
        stand, so the participant walks to that point, spends the gesture there, and gets the same
        catalog effect on `at_home`. The action carries the door among its providers, which is what
        the entrance contact listens for — without it the flat is left by one body and the door
        opens for one.
        """
        capability = "home_egress" if action_type == "leave_home" else "home_ingress"
        model = self.models[self._process_model_id(activity.source_activity_id)]
        binding = next(
            (
                found
                for node in model.nodes
                if (found := self.bindings.get((activity.source_activity_id, node.node_id)))
                is not None
                and any(item.capability == capability for item in found.capability_bindings)
            ),
            None,
        )
        if binding is None:
            return None
        who = participant.resident_id
        action_id = self.trace.identifier("action", [activity.source_activity_id, node_id, who])
        started = self.env.now
        point = next(
            (
                item
                for item in self.bundle.home_model.interaction_points
                if item.interaction_point_id == binding.destination_interaction_point_id
            ),
            None,
        )
        if point is not None:
            kinetics = self.kinematics[who]
            path = plan_path(
                self.bundle.home_model,
                start_region_id=participant.region_id,
                start=participant.position,
                end_region_id=point.region_id,
                end=point.position,
                walking_speed_meters_per_second=kinetics.walking_speed_meters_per_second,
                body_radius_meters=kinetics.body_radius_meters,
                mobility_profile=kinetics.mobility_profile,
            )
            if path is not None and path.distance_meters > 1e-9:
                origin = participant.region_id
                walk_us = self._walk_microseconds(participant, path, action_id)
                yield from self._travel(participant, path, walk_us, action_id)
                if participant.region_id != origin:
                    self._apply_move_effects(participant, participant.region_id, action_id)
                self._set_execution_state(
                    participant, "performing_activity", "process_edge", action_id
                )
        yield self.env.timeout(int(round(_gesture_table()[action_type] * 1_000_000)))
        for template in self.action_definitions[action_type].effects:
            self._apply_effect(
                StateEffect(
                    fact=template.fact_template, operation=template.operation, value=template.value
                ),
                who,
                action_id,
                binding,
            )
        self._record_engine_action(
            participant,
            execution_id,
            action_id,
            node_id,
            action_type,
            started,
            {},
            provider_ids=[item.provider_id for item in binding.capability_bindings],
        )
        return action_id

    def _join_shared_activity(
        self,
        participant: ResidentRuntime,
        activity: CanonicalActivity,
        execution_id: str,
        posture: str | None,
    ) -> Generator[Any, Any, list[str]]:
        """Bring a participant to the activity and put her in the posture it is spent in.

        The plan already reserved her: `occupied_residents()` keeps her out of anything else for the
        interval. What never happened is her body. The engine ran the actor's process model and
        nothing more, so at a shared dinner the actor sat down at the table and the other resident
        stayed in the sitting room for three evenings out of three — a household on paper and one
        body at the table in the trace, the sensor log and the replay alike.

        She walks with the same body the actor walks with, sits on a piece of her own, and every
        step is an ordinary action under the shared execution, so the sensor projection sees her
        where she is without knowing anything about sharing.
        """
        action_ids: list[str] = []
        who = participant.resident_id
        participant.idle_since_us = None
        self._set_execution_state(participant, "performing_activity", "plan", execution_id)
        region = self._shared_region(activity)
        if (
            region is not None
            and self._is_outside(region)
            and participant.facts.get("at_home") is not False
        ):
            crossed = yield from self._cross_front_door(
                participant, activity, execution_id, "leave_home", JOIN_EGRESS_NODE_ID
            )
            if crossed is not None:
                action_ids.append(crossed)
        if region is not None and region != participant.region_id:
            point = self._settling_point(region)
            path = None
            if point is not None:
                kinetics = self.kinematics[who]
                path = plan_path(
                    self.bundle.home_model,
                    start_region_id=participant.region_id,
                    start=participant.position,
                    end_region_id=point.region_id,
                    end=point.position,
                    walking_speed_meters_per_second=kinetics.walking_speed_meters_per_second,
                    body_radius_meters=kinetics.body_radius_meters,
                    mobility_profile=kinetics.mobility_profile,
                )
            if path is not None and path.distance_meters > 1e-9:
                action_id = self.trace.identifier(
                    "action", [activity.source_activity_id, JOIN_NODE_ID, who]
                )
                started = self.env.now
                yield from self._travel(
                    participant,
                    path,
                    self._walk_microseconds(participant, path, action_id),
                    action_id,
                )
                self._apply_move_effects(participant, region, action_id)
                self._set_execution_state(
                    participant, "performing_activity", "process_edge", action_id
                )
                self._record_engine_action(
                    participant,
                    execution_id,
                    action_id,
                    JOIN_NODE_ID,
                    "move_to",
                    started,
                    {"destination": region},
                )
                action_ids.append(action_id)
        if posture in {_SITTING_POSTURE, _RECLINING_POSTURE} and participant.posture != posture:
            action_id = self.trace.identifier(
                "action", [activity.source_activity_id, JOIN_POSTURE_NODE_ID, who]
            )
            started = self.env.now
            yield from self._take_a_seat(participant, posture, action_id)
            seconds = self.kinematics[who].posture_transition_seconds.get(
                posture, _gesture_table()["change_posture"]
            )
            yield self.env.timeout(int(round(seconds * 1_000_000)))
            self._set_posture(participant, posture, "action_effect", action_id)
            self._set_execution_state(participant, "performing_activity", "process_edge", action_id)
            self._record_engine_action(
                participant,
                execution_id,
                action_id,
                JOIN_POSTURE_NODE_ID,
                "change_posture",
                started,
                {"posture": posture},
            )
            action_ids.append(action_id)
        return action_ids

    def _leave_shared_activity(
        self,
        participant: ResidentRuntime,
        activity: CanonicalActivity,
        execution_id: str,
        posture: str | None,
    ) -> Generator[Any, Any, list[str]]:
        """Let a participant go when the activity she was brought to is over.

        She ends it the way the actor's model ends it — on her feet if the meal ends with standing
        up, still on the sofa if the evening does not — and then she is an idle resident like any
        other, with the same walk out of a service room and the same settle.
        """
        action_ids: list[str] = []
        who = participant.resident_id
        if posture in _AMBULATORY_POSTURES and participant.posture not in _AMBULATORY_POSTURES:
            action_id = self.trace.identifier(
                "action", [activity.source_activity_id, LEAVE_POSTURE_NODE_ID, who]
            )
            started = self.env.now
            yield from self._stand_up(participant, action_id)
            self._record_engine_action(
                participant,
                execution_id,
                action_id,
                LEAVE_POSTURE_NODE_ID,
                "change_posture",
                started,
                {"posture": _STANDING_POSTURE},
            )
            action_ids.append(action_id)
        # Out with the actor, back with the actor: the engine brought her through the door, and
        # nothing else would ever walk her home — the return from a service room only knows rooms.
        if self._is_outside(participant.region_id) and participant.facts.get("at_home") is False:
            crossed = yield from self._cross_front_door(
                participant, activity, execution_id, "enter_home", LEAVE_INGRESS_NODE_ID
            )
            if crossed is not None:
                action_ids.append(crossed)
        next_us = self._next_commitment(who, int(self.env.now))
        returned = yield from self._return_from_service_room(
            participant, activity, execution_id, next_us, occurrence=who
        )
        if returned is not None:
            action_ids.append(returned)
        participant.idle_since_us = int(self.env.now)
        self._set_execution_state(participant, "idle", "plan", execution_id)
        self.env.process(self._settle(participant, execution_id, next_us, stream_key=f":{who}"))
        return action_ids

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
        if node.action_type in _upright_actions() and actor.posture not in _AMBULATORY_POSTURES:
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
        movement_us = self._walk_microseconds(actor, path, action_id) if path else 0
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
        if node.action_type == "consume" and "itemRole" in binding.resolved_arguments:
            self.consumed_roles[activity.source_activity_id].add(
                str(binding.resolved_arguments["itemRole"])
            )
        self.trace.actions.append(
            ActionExecution(
                action_execution_id=action_id,
                activity_execution_id=activity_execution_id,
                node_id=node.node_id,
                occurrence_index=occurrence,
                action_type=node.action_type or "",
                actor_id=actor.resident_id,
                started_at=_at(self.origin, started, self.zone),
                ended_at=_at(self.origin, self.env.now, self.zone),
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
        participants = [
            item
            for item in sorted(set(activity.participant_ids))
            if item != actor_id and item in self.state.residents
        ]
        # The actor first, waited for as long as any activity waits for its own resident. Then the
        # others, each for no longer than `SHARED_WAIT_LIMIT_SECONDS` from the moment the actor was
        # free: holding her while somebody else finishes is what froze a whole night. The bound is
        # also what keeps two shared activities waiting for each other's people from deadlocking —
        # they are not taken in one global order any more, so both give up instead.
        absent: list[str] = []
        with ExitStack() as held:
            yield held.enter_context(self.actor_locks[actor_id].request(priority=requested_us))
            free_us = int(self.env.now)
            for resident_id in participants:
                # Out between two halves of one outing: not somewhere a shared activity can reach.
                if self.state.residents[resident_id].outing_continues_into is not None:
                    absent.append(resident_id)
                    continue
                request = self.actor_locks[resident_id].request(priority=requested_us)
                remaining_us = free_us + SHARED_WAIT_LIMIT_SECONDS * 1_000_000 - int(self.env.now)
                if not request.triggered:
                    yield request | self.env.timeout(max(0, remaining_us))
                if request.triggered:
                    held.enter_context(request)
                else:
                    request.cancel()
                    absent.append(resident_id)
            participants = [item for item in participants if item not in absent]
            yield from self._transition_pause(
                self.state.residents[actor_id], requested_us, activity.source_activity_id
            )
            # The privacy the compiler kept between planned activities, kept once the day has
            # moved. A mandatory activity waits for the room; an optional one is given up below.
            # Asked after the pause and not before it: nothing yields between here and the moment
            # this activity claims the room, so nobody can walk in in between. Asked before it, a
            # wash checked an empty bathroom, paused for a minute, and started with the other
            # resident already at the toilet — once on the regenerated Ferri month.
            occupying = {actor_id, *participants}
            in_the_way = self._privacy_conflicts(activity, occupying)
            while in_the_way and activity.mandatory:
                yield simpy.events.AnyOf(self.env, [item.done for item in in_the_way])
                in_the_way = self._privacy_conflicts(activity, occupying)
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
            # The live half of serialising an object. A candidate that may overlap its own
            # resident is not placed against the objects it uses — it interrupts a block rather
            # than competing for the hour, and the compiler leaves it out of the resource model —
            # so whether the television or the toilet is free is only known now. Taken, the
            # candidate is given up like one whose moment has passed; waiting for it would hold
            # its resident back from the day she actually planned.
            object_taken = (
                conditions_ok
                and activity.can_overlap_for_actor
                and not activity.mandatory
                and bool(activity.required_resources)
                and not self.resource_coordinator._fits(
                    {item.resource_id: item.units for item in activity.required_resources}
                )
            )
            # Somebody the activity names never came. A shared evening in front of the television
            # without the other one is not the evening that was planned, so an optional activity
            # is given up; a dinner still happens, with whoever is at the table.
            nobody_came = bool(absent) and not activity.mandatory
            # She is out between two halves of one outing. A toilet trip or a phone call on the
            # sofa that came due meanwhile cannot happen, and running it would walk her home through
            # the street without the front door ever opening.
            continuing = self.state.residents[actor_id].outing_continues_into
            away = (
                continuing is not None
                and continuing != activity.source_activity_id
                and not activity.mandatory
            )
            # Somebody the room is private from is in it, or somebody in it is doing something the
            # room is private for. Waiting would hold her back from the day she planned, exactly as
            # for an object in use. Asked again here: the transition pause may have cleared it.
            room_taken = not activity.mandatory and bool(
                self._privacy_conflicts(activity, occupying)
            )
            # Due after the simulation window closed: the horizon stops at its end, so whatever the
            # day's delays pushed past it does not happen, mandatory or not.
            past_horizon = int(self.env.now) >= self.horizon_end_us
            if (
                past_horizon
                or away
                or not conditions_ok
                or object_taken
                or nobody_came
                or room_taken
            ):
                if activity.mandatory and not past_horizon:
                    raise SimulationFailure(
                        "PRECONDITION_FAILED",
                        f"Mandatory activity '{activity.source_activity_id}' failed "
                        "live preconditions.",
                    )
                if past_horizon:
                    reason, cause_id = "past-horizon", "simulation_window_ended"
                elif away:
                    reason, cause_id = "resident-away", "resident_away"
                elif room_taken and conditions_ok and not object_taken:
                    reason, cause_id = "room-occupied", "room_occupied"
                elif not conditions_ok:
                    reason, cause_id = "live-precondition", "live_precondition_failed"
                elif object_taken:
                    reason, cause_id = "object-taken", "object_in_use"
                else:
                    reason, cause_id = "participant-unavailable", "participant_unavailable"
                deviation_id = self.trace.identifier(
                    "deviation", [activity.source_activity_id, reason]
                )
                self.trace.deviations.append(
                    PlanDeviation(
                        deviation_id=deviation_id,
                        activity_execution_id=execution_id,
                        kind="optional_dropped",
                        cause_id=cause_id,
                    )
                )
                # Giving up on this activity is also the moment to ask again whether she should
                # still be standing where the last one left her.
                #
                # `_return_from_service_room` decides once, when the previous activity ends, and
                # defers when the next commitment is inside `IDLE_RETURN_AFTER_SECONDS` — she is
                # between two steps of the same morning and the walk is not worth taking. That
                # commitment is *this* one, and it has just evaporated: nothing else revisits the
                # decision, so she waits in the service room for the gap that follows instead.
                # Measured over five months, every one of the 43 idle bathroom stays past twenty
                # minutes had a dropped activity inside that window — sixteen past the hour, the
                # longest 111.8 minutes — against a median stay of 4.2. Sitting there a while is a
                # person; the tail was the engine forgetting she was in there.
                #
                # The walk is filed under the activity that was dropped, which is the only one that
                # can own it and is also the honest reading: the plan giving up is what sent her
                # out. The drop itself stays the instant it was, so a dropped activity is still a
                # zero-length statement that nothing happened.
                dropped_at_us = int(self.env.now)
                actor = self.state.residents[actor_id]
                returned = None
                if actor.execution_state == "idle":
                    next_us = self._next_commitment(actor_id, dropped_at_us)
                    returned = yield from self._return_from_service_room(
                        actor, activity, execution_id, next_us
                    )
                    if returned is not None:
                        # She has just been walked across the flat and is on her feet in a room
                        # with nothing to do. The settle the previous activity spawned ran out at
                        # the commitment this drop cancelled, so without this she stands there.
                        self.env.process(self._settle(actor, execution_id, next_us))
                self.trace.activities.append(
                    ActivityExecution(
                        activity_execution_id=execution_id,
                        source_activity_id=activity.source_activity_id,
                        actor_id=actor_id,
                        intent=activity.intent,
                        process_model_id=self._process_model_id(activity.source_activity_id),
                        planned_start=activity.scheduled_start,
                        planned_end=activity.scheduled_end,
                        actual_start=_at(self.origin, dropped_at_us, self.zone),
                        actual_end=_at(self.origin, dropped_at_us, self.zone),
                        status="dropped",
                        participant_ids=participants,
                        action_execution_ids=[returned] if returned is not None else [],
                        # The shift it waited through as well as the drop: listing only the drop
                        # left 556 of the Ferri month's deviations reachable from no activity.
                        deviation_ids=[*deviations, deviation_id],
                    )
                )
                return
            room_use = _RoomUse(
                occupying=frozenset(occupying),
                rooms=frozenset(activity.location_ids),
                excluded=self.exclusions.get(activity.source_activity_id, frozenset()),
                done=self.env.event(),
            )
            self.room_uses[execution_id] = room_use
            if absent:
                deviation_id = self.trace.identifier(
                    "deviation", [activity.source_activity_id, "participant-unavailable"]
                )
                self.trace.deviations.append(
                    PlanDeviation(
                        deviation_id=deviation_id,
                        activity_execution_id=execution_id,
                        kind="fallback_applied",
                        amount_microseconds=int(self.env.now) - free_us,
                        cause_id="participant_unavailable",
                    )
                )
                deviations.append(deviation_id)
            actor = self.state.residents[actor_id]
            actor.idle_since_us = None
            self._set_execution_state(actor, "performing_activity", "plan", execution_id)
            held_posture, final_posture = _shared_postures(
                self.models[self._process_model_id(activity.source_activity_id)]
            )
            joining = [
                self.env.process(
                    self._join_shared_activity(
                        self.state.residents[item], activity, execution_id, held_posture
                    )
                )
                for item in participants
            ]
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
            # One outing written as two activities: arrive already out, and stay out for the next.
            # Trimmed before the durations are shared out, so each keeps the length it was planned
            # with and the time a door crossing would have taken goes to what happens out there.
            if actor.outing_continues_into == activity.source_activity_id:
                phases = _without_departure(phases)
                actor.outing_continues_into = None
            hands_on = self.outing_continuations.get(activity.source_activity_id)
            if hands_on is not None:
                trimmed = _without_return(phases)
                if len(trimmed) == len(phases):
                    hands_on = None
                phases = trimmed
            intended = self._paced_duration(
                activity.source_activity_id,
                activity.duration_microseconds + self.extension_us[activity.source_activity_id],
            )
            # Cut at the end of the window. The compiler lets the last evening run past midnight
            # and marks it truncated, and the engine used to run it whole regardless: the Ferri
            # month ended at 00:00 on 1 November and its trace at 07:07, with 1,287 observations
            # from a morning outside the dataset — six hours of them a resident standing in the
            # living room because nothing planned beyond the horizon would ever put him to bed.
            intended = max(1, min(intended, self.horizon_end_us - int(self.env.now)))
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
            if hands_on is not None:
                actor.outing_continues_into = hands_on
            if joining:
                # A walk longer than a short activity arrives after it ended; she still arrived,
                # and leaves from where she got to.
                joined = yield simpy.events.AllOf(self.env, joining)
                for result in joined.values():
                    action_ids.extend(result)
                leaving = [
                    self.env.process(
                        self._leave_shared_activity(
                            self.state.residents[item], activity, execution_id, final_posture
                        )
                    )
                    for item in participants
                ]
                left = yield simpy.events.AllOf(self.env, leaving)
                for result in left.values():
                    action_ids.extend(result)
            if allocation is not None:
                self.resource_coordinator.release(allocation)
            for resource_id, units in sorted(requirements.items(), reverse=True):
                actor.held_resources.discard(resource_id)
                self._resource_event(
                    resource_id, activity.source_activity_id, actor_id, "released", units
                )
            for effect in activity.effects:
                self._apply_effect(effect, actor_id, execution_id)
            self._put_things_back(actor, activity.source_activity_id, execution_id)
            for item in participants:
                self._put_things_back(self.state.residents[item], None, execution_id)
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
                    actual_start=_at(self.origin, actual_start_us, self.zone),
                    actual_end=_at(self.origin, self.env.now, self.zone),
                    status=status,
                    participant_ids=participants,
                    action_execution_ids=action_ids,
                    deviation_ids=deviations,
                )
            )
            # The room is free when she has left it, which is when the activity ends — after the
            # walk out of the bathroom, not before it.
            del self.room_uses[execution_id]
            room_use.done.succeed()

    def _privacy_conflicts(
        self, activity: CanonicalActivity, occupying: set[str]
    ) -> list[_RoomUse]:
        """The running activities this one may not share its rooms with, by either one's privacy.

        The compiler keeps two planned activities apart when one empties its room of the other's
        resident, and the same rule as `solver.excluded_residents` is kept here once the day has
        drifted. Over the Ferri month six washes that declared the bathroom private had the other
        resident at the toilet beside them: a toilet trip is a candidate the compiler leaves out,
        and a wash that starts late starts on top of whatever is already there.
        """
        excluded = self.exclusions.get(activity.source_activity_id, frozenset())
        rooms = set(activity.location_ids)
        return [
            use
            for use in self.room_uses.values()
            if use.rooms & rooms
            and not use.occupying & occupying
            and (excluded & use.occupying or use.excluded & occupying)
        ]

    def _sit_where_written_standing(self) -> None:
        """Apply `_sits_down_where_written_standing` to the engine's own copies of models and
        bindings. The bundle is left as it came: its digest names the run."""
        seated: dict[str, set[str]] = {}
        for model_id, model in list(self.models.items()):
            found = _sits_down_where_written_standing(model)
            if not found:
                continue
            seated[model_id] = found
            self.models[model_id] = model.model_copy(
                update={
                    "nodes": [
                        node.model_copy(
                            update={
                                "arguments": {
                                    **node.arguments,
                                    "posture": node.arguments["posture"].model_copy(
                                        update={"value": _SITTING_POSTURE}
                                    ),
                                }
                            }
                        )
                        if node.node_id in found
                        else node
                        for node in model.nodes
                    ]
                }
            )
        for key, binding in list(self.bindings.items()):
            if binding.node_id in seated.get(binding.process_model_id, ()):
                self.bindings[key] = binding.model_copy(
                    update={
                        "resolved_arguments": {
                            **binding.resolved_arguments,
                            "posture": _SITTING_POSTURE,
                        }
                    }
                )

    def _outing_continuations(self, activities: list[CanonicalActivity]) -> dict[str, str]:
        """Pair each away activity with the one that follows it closely enough to be one outing.

        Only mandatory activities, because both halves have to happen: the first one leaves her
        outside on the strength of the second bringing her home, and an optional one may be given
        up. Only a resident's own activities without participants, so the door she does not walk
        through is hers alone. And only the next mandatory activity she is occupied by at all, so
        nothing she was due to do at home is jumped over.
        """
        model_ids: dict[str, str] = {}
        for binding in self.bundle.action_bindings:
            model_ids.setdefault(binding.source_activity_id, binding.process_model_id)

        def crosses_door(activity: CanonicalActivity, action_type: str) -> bool:
            model = self.models.get(model_ids.get(activity.source_activity_id, ""))
            return model is not None and any(
                node.action_type == action_type for node in model.nodes
            )

        occupied: defaultdict[str, list[CanonicalActivity]] = defaultdict(list)
        for item in activities:
            if item.mandatory:
                for resident_id in {item.actor_id, *item.participant_ids}:
                    occupied[resident_id].append(item)
        pairs: dict[str, str] = {}
        for resident_id, items in occupied.items():
            items.sort(key=lambda item: (item.scheduled_start, item.sequence_index))
            for first, second in pairwise(items):
                if (
                    first.actor_id != resident_id
                    or second.actor_id != resident_id
                    or first.participant_ids
                    or second.participant_ids
                ):
                    continue
                gap = (second.scheduled_start - first.scheduled_end).total_seconds()
                if not 0 <= gap <= OUTING_CONTINUATION_GAP_SECONDS:
                    continue
                if crosses_door(first, "enter_home") and crosses_door(second, "leave_home"):
                    pairs[first.source_activity_id] = second.source_activity_id
        return pairs

    def run(self) -> ExecutionTrace:
        for candidate in self.bundle.scenario.runtime_event_candidates:
            self.env.process(self._runtime_event_process(candidate))
        activities = self._selected_activities()
        for item in activities:
            planned = _offset(self.origin, item.scheduled_start)
            # The participants as well as the actor: a resident whose dinner is in five minutes is
            # not a resident with nothing coming, whoever is cooking it.
            for resident_id in {item.actor_id, *item.participant_ids}:
                self.commitments_by_actor.setdefault(resident_id, []).append(
                    planned + self.delay_us[item.source_activity_id]
                )
        for starts in self.commitments_by_actor.values():
            starts.sort()
        self.outing_continuations = self._outing_continuations(activities)
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
        # By time alone, which keeps the order they happened in wherever two share an instant. The
        # identifier is a hash and says nothing about order: tie-broken by it, 579 groups of the
        # Ferri month's execution-state changes came out reversed — `moving` recorded after
        # `performing_activity` with each one's previous value naming the other — and a release and
        # an acquisition of one toilet at the same microsecond read as two bodies holding it.
        self.trace.transitions.sort(key=lambda item: item.at)
        self.trace.resources.sort(key=lambda item: item.at)
        self.trace.runtime_events.sort(key=lambda item: (item.evaluated_at, item.event_id))
        self.trace.deviations.sort(key=lambda item: item.deviation_id)
        final_state = FinalWorldState(
            at=_at(self.origin, trace_end_us, self.zone),
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
            ended_at=_at(self.origin, trace_end_us, self.zone),
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
