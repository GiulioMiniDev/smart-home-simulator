"""Roll a confirmed horizon outline into the concrete days an authoring bundle needs (ADR-018).

This is the half of outline-first authoring the model does not do. It takes the arc —
recurring_activities,
phases, events, commitments — and produces every day of the horizon: cadence occurrences placed in
their bands, shifted by the drive state the previous day left behind, wobbled per habit by the
jitter that habit declares, with events fitted into their windows and the displaced occurrences
either dropped or moved.

Four rules, all decided in ADR-018 and none left to chance here:

1. **Phases override cadences, never silently.** A phase either suspends a habit or replaces its
   cadence for its own span. The contract already refuses two overlapping phases that touch the
   same habit, so at most one variant is ever active on a day.
2. **Drives and jitter do different jobs.** `plan_rhythms` supplies the slow autocorrelated
   shift — a short night moves the whole following morning — and each habit's `jitter_minutes`
   sizes the fast wobble around it. An anchor stays punctual, an optional habit wanders. Both draw
   their wobble from `irregularity.stray_minutes`, so both keep a rare wide occurrence that no
   bounded draw can produce.
3. **Displacement is per habit.** An event names the recurring activities it pushes off the day and
says, for
   each, whether that occurrence is skipped or rescheduled onto the nearest free day.
4. **The compiler is given room.** Windows are derived from the jitter a habit declares rather
   than from one global constant, so the placement engine has something to place instead of a
   schedule already pinned to the minute.

Everything is seeded: the same outline and seed always yield the same bundle. The external path
had no such guarantee — re-running one prompt produced a different file every time.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from smart_home_sim.behavior.service import load_action_catalog
from smart_home_sim.domain.authoring import SimulationAuthoringBundle
from smart_home_sim.domain.behavior import (
    PersonalProcessPackage,
    ProcessModel,
    ProcessNodeKind,
    ValueSource,
)
from smart_home_sim.domain.environment import capabilities_for_entity_type
from smart_home_sim.domain.models import (
    BRANCH_EXTENSION,
    JOINT_BRANCH,
    PRIVACY_EXTENSION,
    RESOURCE_ROLE_ALIASES,
    SEPARATE_BRANCH,
    Activity,
    AuthorType,
    Condition,
    ConditionOperator,
    DateTimeWindow,
    DayPlan,
    DependencyGroup,
    DurationRange,
    LocationKind,
    Provenance,
    Resident,
    ResidentInitialState,
    ResourceRequirement,
    SimulationWindow,
    VersionedReference,
)
from smart_home_sim.environment.service import _BODY_SUPPORTING_TYPES, _standing_roles
from smart_home_sim.hybrid_planning.cadence import (
    ActivityOccurrence,
    CadenceCalendar,
    CalendarDay,
    build_cadence_calendar,
)
from smart_home_sim.hybrid_planning.day_generation import (
    DEFAULT_INTENT,
    EVENING_CLEARANCE_MINUTES,
    RHYTHM_EMITTED_INTENTS,
    WAKE_CLEARANCE_MINUTES,
    activity_from_intent,
    at_offset,
    build_day_plan,
    label_to_intent,
    window_around,
)
from smart_home_sim.hybrid_planning.drives import DayRhythm, RhythmProfile, plan_rhythms
from smart_home_sim.hybrid_planning.habits import (
    DECLARED_HABITS_EXTENSION,
    evidence_from_plan,
    measure_habits,
)
from smart_home_sim.hybrid_planning.horizon import _scheduled_drive_load
from smart_home_sim.hybrid_planning.intents import (
    INTENT_CATALOG,
    IntentCategory,
    intent_spec,
)
from smart_home_sim.hybrid_planning.irregularity import (
    EXCEPTION_WIDTH_MULTIPLE,
    stray_minutes,
)
from smart_home_sim.hybrid_planning.outline import (
    DeclaredHabits,
    DeclaredJointActivity,
    DeclaredResidentHabits,
    Displacement,
    FixedCommitment,
    HabitGroundTruth,
    HorizonOutline,
    JointActivity,
    OutlineEvent,
    OutlinePhase,
    OutlineResident,
    OutlineWorld,
    RelationKind,
    SharingMode,
)
from smart_home_sim.hybrid_planning.package_authoring import ACTIVITY_CATALOG_VERSION
from smart_home_sim.hybrid_planning.recurring_activities import (
    ActivityCadence,
    BehavioralProfile,
    CadencePeriod,
    RecurringActivity,
    RecurringActivityKind,
    Weekday,
)
from smart_home_sim.hybrid_planning.world import PlanningWorld, assemble_scenario

# Capabilities no piece of furniture provides: the resident carries them, or the floor does.
# Requiring a room to offer `posture_control` would refuse every override ever written.
_UNFURNISHED_CAPABILITIES = frozenset(
    {"reachable", "transport_reachable", "posture_control", "interaction_point"}
)

GENERATOR_NAME = "smart-home-sim.hybrid_planning.expander"
GENERATOR_VERSION = "1.0.0"

# Floor on the room handed to the compiler. The eight-month bundle that motivated ADR-018 gave
# every one of its 3 870 activities exactly 12 minutes, which is why a placement engine spent
# thirteen hours placing nothing.
MINIMUM_FLEX_MINUTES = 15
# How far a rescheduled occurrence may travel to find a day that is not itself displaced.
RESCHEDULE_SEARCH_DAYS = 7

# Waking and the night are produced by the drive model, which owns bedtime, night length and the
# wake that follows. There is exactly one of each per day and the rhythm places both, so a habit
# declaring them would be scheduled a second time and its band would argue with a night already
# placed. The outline states who the resident is; the rhythm decides when she sleeps.
#
# Napping is deliberately *not* in this set. The drive model's nap is a response to accumulated
# sleep debt — `drives.py` calls it "behaviour, not a habit occurrence" — and is a different thing
# from a resident who habitually dozes off after lunch. That one is a routine and belongs in the
# profile like any other. The two compose without help: `_free_slot` drops the debt nap into the
# widest free gap of the afternoon, so it lands beside a habitual nap when the window still has
# room and is skipped when it does not. On a napping profile that means the occasional day with
# two — which is what a short night on top of a nap routine actually looks like.
RHYTHM_OWNED_INTENTS = frozenset({"wake_up", "sleep"})

# Kinds whose occurrences the scheduler may drop when a day cannot hold them all.
#
# `kind` used to reach nothing: every expanded activity was mandatory, so an author declaring the
# television optional was declaring it to no one. A day with a long evening event then had no
# give — a six-hour visit to relatives on New Year's Eve, plus a mandatory television, reading and
# hygiene, is not a schedule but a contradiction, and the horizon was rejected whole for it.
# Anchors and contextual habits stay mandatory: those are the skeleton of the day, and a day that
# cannot fit them is genuinely over-constrained and should say so.
_SACRIFICIAL_KINDS = frozenset({RecurringActivityKind.optional, RecurringActivityKind.rare})

# The intents `INTENT_CATALOG` exposes are the *in-home* alphabet: each carries a room and a
# reference process model, and they are what a habit inside the dwelling performs.
_HOME_INTENTS = {spec.intent_id: spec.default_location for spec in INTENT_CATALOG}
# Time away needs no such detail; `away_intent_specs` supplies those, taken from the activity
# catalog by category, so a case can say "she is at work" without the vocabulary growing an intent
# per occupation.


def _intent_location(intent: str) -> str | None:
    try:
        return intent_spec(intent).default_location
    except KeyError:
        return None


class ExpansionError(ValueError):
    """The outline is valid but cannot be rolled into a horizon."""


@dataclass(frozen=True)
class ExpansionResult:
    bundle: SimulationAuthoringBundle
    # The bands as the outline declared them, per resident: the half of the habit ground truth that
    # is true by definition, and the half a run's export measures against.
    declared_habits: DeclaredHabits
    # The same bands measured on the expanded plan, `measuredOn: expanded_plan`. Only for telling
    # the author, before any run exists, that a band she drew holds nothing; never published,
    # because the plan is not what the residents did.
    planned_bands: list[HabitGroundTruth]
    day_count: int
    activity_count: int
    # Occurrences an event pushed off their day, by policy, for the report the researcher reads.
    skipped_occurrences: int
    rescheduled_occurrences: int
    dropped_occurrences: int


def _rng(seed: int, *parts: object) -> random.Random:
    key = "|".join(str(part) for part in (seed, *parts))
    return random.Random(int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16))


def _to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _to_hhmm(total: int) -> str:
    clamped = max(0, min(total, 24 * 60 - 1))
    return f"{clamped // 60:02d}:{clamped % 60:02d}"


def _resident_profile(outline: HorizonOutline, resident: OutlineResident) -> BehavioralProfile:
    """One resident's own recurring activities plus the shared ones she takes part in.

    The joint activities are folded into every participant's profile rather than rolled in a
    household calendar of their own, and that is what makes the participants agree without anyone
    negotiating. `_due_times` is keyed by the activity identifier and the horizon seed, so the same
    joint activity folded into two profiles falls due on the same days, at the same target time,
    in both — and it keeps every phase, displacement and cadence mechanism working on a shared
    activity exactly as it works on a private one.

    Whether an occurrence is then emitted once for the household or once per participant is decided
    in one place, per day, by `_plan_sharing`.
    """
    shared = [item.activity for item in outline.joint_activities_for(resident.resident_id)]
    if not shared:
        return resident.profile
    return resident.profile.model_copy(
        update={"recurring_activities": [*resident.profile.recurring_activities, *shared]}
    )


def _phase_profile(profile: BehavioralProfile, phase: OutlinePhase) -> BehavioralProfile:
    """The profile as it stands during one phase, with that phase's overrides applied."""
    replacements = {
        item.recurring_activity_id: item.cadence
        for item in phase.activity_overrides
        if item.cadence is not None
    }
    recurring_activities = [
        activity.model_copy(update={"cadence": replacements[activity.recurring_activity_id]})
        if activity.recurring_activity_id in replacements
        else activity
        for activity in profile.recurring_activities
    ]
    return profile.model_copy(update={"recurring_activities": recurring_activities})


def _effective_calendar(
    outline: HorizonOutline, resident: OutlineResident, seed: int
) -> CadenceCalendar:
    """One calendar for the horizon, taking each phase's overridden activities from its own
    variant.

    `_due_times` is computed per habit, so rebuilding the whole calendar with one habit's cadence
    swapped leaves every other habit's schedule identical. That is what makes splicing sound:
    the baseline and the variant agree everywhere the override does not apply.
    """
    profile = _resident_profile(outline, resident)
    baseline = build_cadence_calendar(
        profile,
        start_date=outline.start_date,
        months=outline.months,
        seed=seed,
        timezone=outline.time_zone,
    ).calendar

    # Per day: every habit an active phase overrides, and the occurrences its variant scheduled.
    # The two are tracked separately on purpose. A replacement cadence that thins a daily habit to
    # twice a week schedules nothing on most days of the phase, and the baseline occurrence has to
    # go on those days too — keying the removal off the variant's occurrences instead would leave
    # the original cadence running untouched wherever the new one is silent.
    overridden_by_date: dict[str, set[str]] = {}
    variant_by_date: dict[str, list[ActivityOccurrence]] = {}
    for phase in resident.phases:
        overridden = {item.recurring_activity_id for item in phase.activity_overrides}
        if not overridden:
            continue
        stopped = {
            item.recurring_activity_id for item in phase.activity_overrides if item.suspended
        }
        variant = build_cadence_calendar(
            _phase_profile(profile, phase),
            start_date=outline.start_date,
            months=outline.months,
            seed=seed,
            timezone=outline.time_zone,
        ).calendar
        by_date = {day.date: day for day in variant.days}
        for day in baseline.days:
            if not phase.start_date <= date.fromisoformat(day.date) <= phase.end_date:
                continue
            overridden_by_date.setdefault(day.date, set()).update(overridden)
            variant_day = by_date.get(day.date)
            if variant_day is None:
                continue
            variant_by_date.setdefault(day.date, []).extend(
                occurrence
                for occurrence in variant_day.occurrences
                if occurrence.recurring_activity_id in overridden
                and occurrence.recurring_activity_id not in stopped
            )

    days: list[CalendarDay] = []
    for day in baseline.days:
        dropped = overridden_by_date.get(day.date, set())
        kept = [item for item in day.occurrences if item.recurring_activity_id not in dropped]
        kept.extend(variant_by_date.get(day.date, []))
        kept.sort(key=lambda item: (item.target_time, item.recurring_activity_id))
        days.append(day.model_copy(update={"occurrences": kept}))
    return baseline.model_copy(update={"days": days})


def _event_dates(event: OutlineEvent, seed: int) -> list[date]:
    """Deterministically pick the days an event lands on inside its declared window."""
    span = [
        event.earliest_date + timedelta(days=offset)
        for offset in range((event.latest_date - event.earliest_date).days + 1)
    ]
    if event.weekdays:
        allowed = {item.value for item in event.weekdays}
        span = [day for day in span if day.strftime("%A").lower() in allowed]
    if len(span) < event.occurrences:
        raise ExpansionError(
            f"event {event.event_id!r} cannot fit {event.occurrences} occurrences "
            f"in {len(span)} eligible day(s)"
        )
    chosen = _rng(seed, "event", event.event_id).sample(span, event.occurrences)
    return sorted(chosen)


@dataclass(frozen=True)
class _PlacedEvent:
    event: OutlineEvent
    day: date


def _place_events(resident: OutlineResident, seed: int) -> dict[str, list[_PlacedEvent]]:
    placed: dict[str, list[_PlacedEvent]] = {}
    for event in resident.events:
        for day in _event_dates(event, seed):
            placed.setdefault(day.isoformat(), []).append(_PlacedEvent(event=event, day=day))
    return placed


def _daily_capacity(profile: BehavioralProfile, phases: Sequence[OutlinePhase]) -> dict[str, int]:
    """How many occurrences of each habit one day may legitimately hold.

    One, for everything that recurs weekly or monthly. For a daily habit it is whatever the cadence
    asks for, taken at its widest across the baseline and any phase that replaces it, because a
    displaced occurrence may be rescheduled into a phase with a different rhythm and the answer
    must not depend on which side of the boundary it lands.
    """
    capacity: dict[str, int] = {}
    cadences: dict[str, list[ActivityCadence]] = defaultdict(list)
    for activity in profile.recurring_activities:
        cadences[activity.recurring_activity_id].append(activity.cadence)
    for phase in phases:
        for override in phase.activity_overrides:
            if override.cadence is not None:
                cadences[override.recurring_activity_id].append(override.cadence)
    for recurring_activity_id, declared in cadences.items():
        capacity[recurring_activity_id] = max(
            item.times_per_period if item.period is CadencePeriod.day else 1 for item in declared
        )
    return capacity


def _apply_displacement(
    calendar: CadenceCalendar,
    placed: dict[str, list[_PlacedEvent]],
    capacity: dict[str, int],
) -> tuple[CadenceCalendar, int, int, int]:
    """Remove the occurrences events push off their day, moving the ones asked to move.

    A rescheduled occurrence looks forward for the nearest day inside the horizon that is not
    displaced for that habit and still has room for it. Finding none, it is dropped and counted:
    silently keeping it would put one more of the habit on a day than its cadence ever asks for,
    and silently losing it would hide the fact from whoever reads the report.
    """
    by_date = {day.date: day for day in calendar.days}
    order = [day.date for day in calendar.days]
    displaced: dict[str, dict[str, Displacement]] = {}
    for key, events in placed.items():
        for item in events:
            for entry in item.event.displaces:
                displaced.setdefault(key, {})[entry.recurring_activity_id] = entry.policy

    occurrences: dict[str, list[ActivityOccurrence]] = {
        day.date: list(day.occurrences) for day in calendar.days
    }
    skipped = 0
    moved = 0
    dropped = 0
    for key in order:
        policies = displaced.get(key, {})
        if not policies:
            continue
        remaining: list[ActivityOccurrence] = []
        for occurrence in occurrences[key]:
            policy = policies.get(occurrence.recurring_activity_id)
            if policy is None:
                remaining.append(occurrence)
                continue
            if policy is Displacement.skip:
                skipped += 1
                continue
            target = _nearest_free_day(
                order, key, occurrence.recurring_activity_id, displaced, occurrences, capacity
            )
            if target is None:
                dropped += 1
                continue
            occurrences[target].append(occurrence)
            occurrences[target].sort(
                key=lambda item: (item.target_time, item.recurring_activity_id)
            )
            moved += 1
        occurrences[key] = remaining

    days = [by_date[key].model_copy(update={"occurrences": occurrences[key]}) for key in order]
    return calendar.model_copy(update={"days": days}), skipped, moved, dropped


def _nearest_free_day(
    order: list[str],
    key: str,
    recurring_activity_id: str,
    displaced: dict[str, dict[str, Displacement]],
    occurrences: dict[str, list[ActivityOccurrence]],
    capacity: dict[str, int],
) -> str | None:
    start = order.index(key)
    room = capacity.get(recurring_activity_id, 1)
    for offset in range(1, RESCHEDULE_SEARCH_DAYS + 1):
        index = start + offset
        if index >= len(order):
            break
        candidate = order[index]
        if recurring_activity_id in displaced.get(candidate, {}):
            continue
        running = sum(
            1
            for item in occurrences[candidate]
            if item.recurring_activity_id == recurring_activity_id
        )
        if running >= room:
            continue
        return candidate
    return None


def _activities_by_id(profile: BehavioralProfile) -> dict[str, RecurringActivity]:
    return {activity.recurring_activity_id: activity for activity in profile.recurring_activities}


def _effective_activities(
    phases: Sequence[OutlinePhase], baseline: dict[str, RecurringActivity], day: date
) -> dict[str, RecurringActivity]:
    """The habits as they stand on one day, with the cadence any active phase replaced.

    `_effective_calendar` already places the occurrences from the variant cadence; everything that
    reads a cadence *afterwards* has to read the same one. It did not: the window handed to the
    compiler came from the baseline, so a habit a phase moved to a later band was given the earlier
    band's hours, and a habit a phase split into more occurrences a day was measured against the
    wrong number of sub-bands. The contract forbids two phases overriding one habit at once, so
    there is never a choice to make here.
    """
    replacements: dict[str, ActivityCadence] = {}
    for phase in phases:
        if not phase.start_date <= day <= phase.end_date:
            continue
        for override in phase.activity_overrides:
            if override.cadence is not None:
                replacements[override.recurring_activity_id] = override.cadence
    if not replacements:
        return baseline
    return {
        habit_id: activity.model_copy(update={"cadence": replacements[habit_id]})
        if habit_id in replacements
        else activity
        for habit_id, activity in baseline.items()
    }


def _recurring_activity_id_of(activity: Activity) -> str | None:
    for label in activity.labels:
        if label.startswith("activity:"):
            return label.removeprefix("activity:")
    return None


def _band(day_date: date, start: str, end: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    return at_offset(day_date, _to_minutes(start), tz), at_offset(day_date, _to_minutes(end), tz)


def _sub_bands(
    activities: Sequence[Activity], recurring: dict[str, RecurringActivity]
) -> dict[str, tuple[str, str]]:
    """The slice of its habit's band each occurrence of a multi-occurrence daily habit owns.

    A habit recurring several times a day is placed one occurrence per equal sub-band, and the
    window handed to the compiler has to say the same thing. Handing each of them the *whole* band
    instead — which is right for a habit that happens once — makes every occurrence free to sit
    anywhere among the others, and the compiler is then asked to choose an ordering rather than to
    confirm one. It does not scale: four working blocks and three bathroom visits inside bands of
    nine and eleven hours exhausted CP-SAT's budget on the feasibility probes alone, and a horizon
    that expands cleanly was rejected with `SOLVER_NOT_OPTIMAL` and no day named.

    The occurrences are matched to sub-bands in time order, which is the order they were drawn in,
    so occurrence *i* is given back the sub-band it came from.
    """
    by_habit: dict[str, list[Activity]] = defaultdict(list)
    for activity in activities:
        habit_id = _recurring_activity_id_of(activity)
        if habit_id is None or activity.start_window is None:
            continue
        declared = recurring.get(habit_id)
        if declared is None or declared.cadence.period is not CadencePeriod.day:
            continue
        if declared.cadence.times_per_period < 2:
            continue
        by_habit[habit_id].append(activity)

    bands: dict[str, tuple[str, str]] = {}
    for habit_id, occurrences in by_habit.items():
        cadence = recurring[habit_id].cadence
        low = _to_minutes(cadence.window_start)
        width = (_to_minutes(cadence.window_end) - low) / cadence.times_per_period
        ordered = sorted(
            occurrences,
            key=lambda item: (item.start_window.preferred, item.activity_id),  # type: ignore[union-attr]
        )
        for index, activity in enumerate(ordered):
            # More occurrences than sub-bands means one was rescheduled onto a day that already
            # ran the habit; it keeps the last sub-band rather than reaching past the band's end.
            slot = min(index, cadence.times_per_period - 1)
            bands[activity.activity_id] = (
                _to_hhmm(int(low + slot * width)),
                _to_hhmm(int(low + (slot + 1) * width)),
            )
    return bands


def _wobble(
    activity: Activity,
    recurring: RecurringActivity | None,
    tz: ZoneInfo,
    seed: int,
    band: tuple[str, str] | None = None,
    lights_out: datetime | None = None,
    wake: datetime | None = None,
) -> Activity:
    """Wobble the preferred time by the habit's jitter, and open the window to its declared band.

    The two are deliberately different quantities. Jitter is how irregular this habit is, so it
    moves the *preferred* moment — an anchor barely, an optional habit visibly. The *window* is
    the band the author declared, which is their statement that anywhere in there is acceptable;
    handing that whole band to the compiler is what lets it resolve a collision rather than
    report one. Deriving both from jitter, as an earlier revision did, left a five-hour Christmas
    with fifteen minutes of room and made the day infeasible.

    ``band`` narrows that statement for one occurrence of a habit that recurs several times a day,
    where the author's band is divided rather than shared: see `_sub_bands`.

    ``lights_out`` is tonight's, and it bounds the result whatever the band says. `_shift` already
    placed the occurrence before it; the wobble is the last thing to touch the preferred moment, so
    it is the last place the bound can be honoured. An author's band that runs to 23:15 is a
    statement about her usual evenings, not about the evening she went to bed at 22:01.

    ``wake`` is this morning's, and it is the same argument at the other end of the day — which
    for a long time only the evening had. `_shift` floors every occurrence at the wake, and then
    this function threw that floor away by rebuilding the window from the author's declared band,
    which knows nothing about the night that has just ended. A night that ran long therefore put
    breakfast, the shower and the morning run *before* the wake they follow: 99 days of one
    generated year, and on the worst of them the resident woke at 09:36 having already eaten,
    washed and been out running. A band that opens at 07:00 is a statement about her usual
    mornings, not about the morning she slept until nine.
    """
    if activity.start_window is None:
        return activity
    preferred = activity.start_window.preferred
    if recurring is None:
        return activity.model_copy(
            update={
                "start_window": window_around(preferred, timedelta(minutes=MINIMUM_FLEX_MINUTES))
            }
        )

    window_start, window_end = band or (
        recurring.cadence.window_start,
        recurring.cadence.window_end,
    )
    day_date = activity.start_window.preferred.date()
    earliest, latest = _band(day_date, window_start, window_end, tz)
    jitter = max(recurring.cadence.jitter_minutes, 0)
    if jitter > 0:
        # `jitter_minutes` is now the standard deviation of an ordinary occurrence rather than a
        # hard bound on every one: about two thirds of them fall inside the declared minutes, and
        # the mixture's rare wide component supplies the tail no uniform inside ±jitter can have.
        # The reading the author is given — how far a single occurrence wanders — is unchanged, and
        # so is the ranking their numbers express; only the punctual habits stop being unnaturally
        # punctual. Read as a bound, Giulia's evening hygiene kept 84% of its occurrences within an
        # hour of the usual time; read as a deviation, 76%, against Aruba's 46% for its own
        # closest daily habit.
        # Rounded to the minute, and that is not cosmetic. `TimeAxis` takes its resolution from the
        # finest unit the scenario actually uses, so one preferred time carrying seconds drags the
        # whole horizon down to microsecond ticks: 67% of a year's activities landed off the minute
        # and every window of the compile returned UNKNOWN inside its deterministic budget. The
        # plan has always been written in whole minutes; the mixture must not be what changes that.
        offset = round(stray_minutes(_rng(seed, "jitter", activity.activity_id), float(jitter)))
        # Clamped to the declared band, plus the width of the tail. The band is the author's
        # statement that anywhere in there is ordinary, and the excursion is precisely the day that
        # is not ordinary, so a clamp on the band alone deletes the component that was added: with
        # it, dinner over a year never once left 19:30-21:45 and hygiene never left 21:15-23:15.
        # The allowance is bounded rather than absent because unclamped, a 45-minute jitter pushed
        # an evening habit whose band closed at 22:30 past bedtime. It costs the compiler nothing:
        # the guard below widens the *window* to follow the occurrence, so the placement engine
        # keeps every hour it had and gains the ones the excursion reached into.
        allowance = timedelta(minutes=round(jitter * EXCEPTION_WIDTH_MULTIPLE))
        preferred = max(
            earliest - allowance, min(preferred + timedelta(minutes=offset), latest + allowance)
        )
    if wake is not None and activity.intent not in RHYTHM_OWNED_INTENTS:
        floor = wake + timedelta(minutes=WAKE_CLEARANCE_MINUTES)
        if earliest < floor:
            # Translated, not narrowed, and that distinction is the whole of it. Clamping the early
            # edge alone left a 07:05-08:15 breakfast with fifteen minutes of window on the morning
            # the wake landed at 09:07 — and the jog, the shower and the medication with fifteen
            # minutes each, all over the same quarter of an hour. Three mandatory occurrences and
            # one window is not a schedule: MAIN_PLAN_INFEASIBLE on 2026-09-01, the very day the
            # bound was written for. The band is the author's statement of how much room the
            # occurrence has; a late wake moves that room down the day, it does not shrink it.
            shift = floor - earliest
            earliest += shift
            preferred += shift
            latest += shift
    if activity.intent not in RHYTHM_OWNED_INTENTS:
        # Kept inside the day, at both ends. The tail of the mixture is deliberately allowed to
        # reach outside the author's band, and the band is not the day: a 45-minute jitter on an
        # early breakfast reaches back past midnight, and the evening reaches forward past it, and
        # either one lands the occurrence on a date its own day plan does not list —
        # `ACTIVITY_ASSIGNED_TO_WRONG_DAY`, an error, 110 of them over a year when only the
        # evening was bounded. The night is the one activity exempt from this: it is emitted onto
        # the day it happens on, which is what `sleep_starts_next_day` decides.
        opens = datetime.combine(day_date, time.min.replace(tzinfo=preferred.tzinfo))
        if wake is not None:
            opens = max(opens, wake + timedelta(minutes=WAKE_CLEARANCE_MINUTES))
        closes = datetime.combine(
            day_date + timedelta(days=1), time.min.replace(tzinfo=preferred.tzinfo)
        )
        if lights_out is not None:
            closes = min(closes, lights_out)
        last_moment = closes - timedelta(minutes=EVENING_CLEARANCE_MINUTES)
        # A wake so late that it passes lights-out is a day with no waking hours in it, which the
        # rhythm does not produce; the `min` is there so that if one ever appears the window stays
        # ordered rather than the horizon failing on `earliest <= preferred <= latest`.
        preferred = max(min(opens, last_moment), min(preferred, last_moment))
    # The drives may have carried the occurrence outside its declared band; the band then follows
    # the occurrence rather than contradicting it. The guard is built in real elapsed time so the
    # band cannot end up straddling a DST transition on the wrong side of its own preferred moment.
    guard = window_around(preferred, timedelta(minutes=MINIMUM_FLEX_MINUTES))
    earliest = min(earliest, guard.earliest)
    latest = max(latest, guard.latest)
    if wake is not None and activity.intent not in RHYTHM_OWNED_INTENTS:
        # The guard above may have re-opened the early edge below the floor the translation set,
        # and the window is a hard bound in the compiler: left open, the band's early edge is
        # somewhere the solver may still place the occurrence, and it will if that resolves a
        # collision more cheaply. Closing it here costs nothing, because the late edge travelled
        # with the rest of the band and the room is still there.
        earliest = max(earliest, min(wake + timedelta(minutes=WAKE_CLEARANCE_MINUTES), preferred))
    return activity.model_copy(
        update={
            "start_window": DateTimeWindow(earliest=earliest, preferred=preferred, latest=latest),
            "mandatory": recurring.kind not in _SACRIFICIAL_KINDS,
        }
    )


# A night on this list that starts before this hour came from yesterday evening: it is the night
# the day woke up from, not the one it is heading into, and it must not bound the evening.
_INHERITED_NIGHT_BEFORE_HOUR = 12


def _wake(plan: DayPlan) -> datetime | None:
    """The latest moment this day's waking hours can begin.

    The mirror of `_lights_out`, and read the same way: the wake the rhythm placed on this day's
    list, which belongs to the night that is ending. There is exactly one per day — the intent is
    rhythm-owned, so no habit can declare a second — and if a day somehow carries none the bound
    is simply not applied.

    The *latest* edge rather than the preferred moment, because the bound has to hold whatever the
    compiler decides. Windows are hard bounds there, so a morning floored at the preferred wake
    can still open ten minutes before a wake placed at its own late edge, and 982 of one year's
    windows could. Floored at the late edge it cannot, and since the compiler also forbids a
    resident's activities from overlapping, "starts after the wake starts" is then "starts after
    the wake is over". The cost is at most the fifteen minutes of the wake's own flex.
    """
    for activity in plan.activities:
        if activity.intent == "wake_up" and activity.start_window is not None:
            return activity.start_window.latest
    return None


# A stretch of the waking day this long with nothing in it is not a person, it is a pause button.
# Read off the replay: three hours and forty minutes lying motionless on a sofa, one dot that does
# not move for an afternoon.
#
# The gaps themselves are not the defect — the real reference log leaves a third of its time
# unannotated, more than a generated year does. What differs is what is *in* them: Aruba's
# unannotated hours are a person moving about doing things nobody wrote down, and ours were empty.
# Under this contract liveliness needs an activity, and an activity carries a label, so the filler
# is annotated. That is the right way round: a sparse annotation scheme is an evaluation choice and
# can be applied afterwards by hiding classes. Labels can be taken away; they cannot be invented.
FILL_CANDIDATES_PER_DAY = 9
# Clear of the wake and of lights-out, like the bathroom candidates.
FILL_WAKE_MARGIN_MINUTES = 60
FILL_NIGHT_MARGIN_MINUTES = 45
# What she does with an afternoon nobody claimed, most-preferred first. Only those the package
# actually implements are used, so no horizon is refused for a filler it never asked for.
# `read_and_rest` is deliberately absent. It is already the most frequent intent of a generated
# year and one of the two the recogniser confuses most — filling with it would double the class
# whose confusion the dataset exists to measure.
FILL_INTENTS = (
    "watch_television",
    "tidy_living_room_and_hallway",
    "prepare_and_drink_hot_drink",
    "phone_call",
)
FILL_LABEL = "unclaimed_hours"
# Short, because a filler is what happens in a gap and not what the gap is for. Left to its own
# category a television block drew seventy-one minutes and became the evening.
# (minimumMinutes, medianMinutes, maximumMinutes, logSigma)
FILL_SHAPE = (8, 22, 55, 0.40)


# The two arms of a degradable shared activity. `joint` is worth more than both halves of
# `separate` put together, which is how the objective's first stage — the sum of `priority` over
# present optional activities — expresses "share it if it fits" without a new objective term.
JOINT_BRANCH_PRIORITY = 90
SEPARATE_BRANCH_PRIORITY = 40


def _separate_priority(participants: int) -> int:
    """What one meal of the separate arm is worth, so that all of them still lose to the shared one.

    Forty is right for two people and wrong for three: three separate dinners at forty outweigh one
    shared at ninety, and a family would never eat together however well the day fitted. Nothing in
    a household is binary, so the halves are sized by how many there are.
    """
    return min(SEPARATE_BRANCH_PRIORITY, (JOINT_BRANCH_PRIORITY - 1) // max(1, participants))


def _other_participants(participants: Sequence[str], actor_id: str) -> list[str]:
    """The participants other than the one the activity belongs to.

    `participantIds` names the people taking part *besides* the actor; repeating the actor there is
    a validation failure, and `occupied_residents()` adds the actor back anyway, so the two readings
    occupy exactly the same set of people.
    """
    return [item for item in participants if item != actor_id]


# How long a stretch has to be before it is worth calling a wait rather than a gap between two
# things. Below this the resident has not settled anywhere and the room she is about to be in says
# nothing useful about where she is.
WAIT_MINIMUM_MINUTES = 10


def _waiting_rooms(activities: Sequence[Activity]) -> list[tuple[datetime, datetime, str]]:
    """The stretches that end in a shared activity, and the room it is about to happen in.

    The wait is a residue rather than a mechanism: anchoring a shared activity to the last
    participant who becomes free is what produces it. One of them finishes cooking at 12:40, the
    table is not laid until 13:05, and nobody wrote those twenty-five minutes.

    They are nonetheless *something*. Left alone they are exactly what `simulation/behaviour.py`
    counts as long idle — the family that already accounts for 402 minutes a day and for 22.7% of
    the sensor log being emitted by a motionless body. A wait has a shape a reader recognises: it
    happens where the shared activity is about to happen, it is interruptible, and it ends the
    moment the other one arrives. So no `wait_for_resident` intent is coined — the catalogue is
    closed, and in any case nobody waits, they tidy the kitchen and look at the clock. The filler
    that was going there anyway is simply put in the right room.
    """
    shared = [
        item
        for item in activities
        if item.participant_ids and item.start_window is not None and item.duration is not None
    ]
    stretches: list[tuple[datetime, datetime, str]] = []
    for activity in shared:
        assert activity.start_window is not None
        begins = activity.start_window.preferred
        ends_before = [
            other.start_window.preferred + timedelta(minutes=other.duration.preferred_minutes)
            for other in activities
            if other is not activity
            and other.start_window is not None
            and other.duration is not None
            and other.start_window.preferred + timedelta(minutes=other.duration.preferred_minutes)
            <= begins
        ]
        if not ends_before:
            continue
        opens = max(ends_before)
        if begins - opens >= timedelta(minutes=WAIT_MINIMUM_MINUTES):
            stretches.append((opens, begins, activity.location_ids[0]))
    return stretches


def _offer_both_arms(
    activities: list[Activity],
    degradable: Mapping[str, tuple[tuple[str, ...], int]],
    day_date: date,
) -> list[Activity]:
    """Write the shared version and the separate one, and let the compiler pick.

    Each participant keeps the occurrence her own calendar already holds — that is the separate
    arm, one meal each — and the host gains a second copy naming every participant, which is the
    shared arm. Both are optional, both belong to one exclusive group, and exactly one of them is
    scheduled.

    The shared arm cannot be shorter than `minimumSharedMinutes`. Without that floor the choice was
    never made: the objective prefers the shared arm, a twelve-minute dinner is still a dinner, and
    the compiler served a couple a shared meal squeezed to its catalogue minimum rather than two
    ordinary ones — with degradation on or off, the same twelve minutes. The floor is the author's
    own statement that below it the occasion is not a shared one, which is exactly the point at
    which the separate arm should win.

    The trap, from the comment on `_cook_before_eating`: the solver reads a dependency as
    `presence(meal) <= presence(cooking)`, so the separate meals must each keep their own
    preparation rather than inherit the shared one. They do, because they are the activities the
    day already had; nothing is re-pointed at the shared copy.
    """
    if not degradable:
        return activities
    offered: list[Activity] = []
    for activity in activities:
        recurring = _recurring_activity_id_of(activity) or ""
        declared = degradable.get(recurring)
        if declared is None or activity.participant_ids:
            offered.append(activity)
            continue
        participants, floor = declared
        group = f"{day_date.isoformat()}:{recurring}"
        offered.append(
            activity.model_copy(
                update={
                    "mandatory": False,
                    "priority": _separate_priority(len(participants)),
                    "extensions": {
                        **activity.extensions,
                        BRANCH_EXTENSION: {"group": group, "branch": SEPARATE_BRANCH},
                    },
                }
            )
        )
        if activity.actor_id != participants[0]:
            continue
        duration = activity.duration
        if duration is not None and floor > duration.minimum_minutes:
            shortest = min(float(floor), duration.maximum_minutes)
            duration = DurationRange(
                minimum_minutes=shortest,
                preferred_minutes=max(duration.preferred_minutes, shortest),
                maximum_minutes=duration.maximum_minutes,
            )
        offered.append(
            activity.model_copy(
                update={
                    "activity_id": f"{activity.activity_id}__joint",
                    "duration": duration,
                    "participant_ids": _other_participants(participants, activity.actor_id),
                    "mandatory": False,
                    "priority": JOINT_BRANCH_PRIORITY,
                    "extensions": {
                        **activity.extensions,
                        BRANCH_EXTENSION: {"group": group, "branch": JOINT_BRANCH},
                    },
                }
            )
        )
    return offered


# Fillers that need nothing the room holds: a phone call is made wherever she is.
_FILL_ANYWHERE = frozenset({"phone_call"})


def _can_happen_in(intent: str, room: str) -> bool:
    if intent in _FILL_ANYWHERE:
        return True
    try:
        return intent_spec(intent).default_location == room
    except KeyError:
        return False


def _seed_filler_candidates(
    activities: list[Activity],
    available: tuple[str, ...],
    wake: datetime | None,
    lights_out: datetime | None,
    day_date: date,
    actor_id: str,
    seed: int,
    index_offset: int = 0,
) -> list[Activity]:
    """Chances to do something with a stretch of day the plan left empty.

    Seeded on a grid and turned down by the engine, for the same reason the bathroom candidates
    are: the planner can only see the gaps in its own plan, and the ones that matter are the
    execution's. A Saturday afternoon that reads as ninety minutes on the day plan ran to three
    hours and forty in the trace — a dot motionless on a sofa, which is what the replay showed and
    what no plan-time measurement could have told us.

    They are annotated, and deliberately. Liveliness needs an activity under this contract and an
    activity carries a label; a sparse annotation scheme is an evaluation choice and is applied
    afterwards by hiding classes. Labels can be taken away, not invented.
    """
    if not available or wake is None or lights_out is None:
        return activities
    opens = wake + timedelta(minutes=FILL_WAKE_MARGIN_MINUTES)
    closes = lights_out - timedelta(minutes=FILL_NIGHT_MARGIN_MINUTES)
    room = (closes - opens).total_seconds() / 60
    if room < 120:
        return activities
    step = room / FILL_CANDIDATES_PER_DAY
    precondition = (Condition(fact="the_hours_are_unclaimed", operator=ConditionOperator.truthy),)
    waits = _waiting_rooms(activities)
    added: list[Activity] = []
    for slot in range(FILL_CANDIDATES_PER_DAY):
        index = index_offset + len(activities) + len(added)
        rng = _rng(seed, "filler", day_date.isoformat(), index)
        offset = step * (slot + 0.5) + rng.uniform(-step / 3, step / 3)
        moment = opens + timedelta(minutes=offset)
        # A candidate that falls inside a wait is put in the room the wait is for, when it can
        # happen there. Everything else is left where the catalog puts it: moved regardless, the
        # Ferri month had fifteen television evenings in a kitchen with no television, the set
        # switched on in the living room and watched from the kitchen's service point.
        where = next((location for start, end, location in waits if start <= moment < end), None)
        intent = available[rng.randrange(len(available))]
        if where is not None and not _can_happen_in(intent, where):
            where = None
        added.append(
            activity_from_intent(
                intent,
                day_date,
                moment,
                actor_id,
                index=index,
                label=FILL_LABEL,
                nested=True,
                duration_shape=FILL_SHAPE,
                preconditions=precondition,
                seed=seed,
                location=where,
            )
        )
    return activities + added


def _lights_out(plan: DayPlan) -> datetime | None:
    """The moment this day's evening has to be over by.

    Normally that is when its own night begins. Two cases make it less obvious than it was. A day
    whose lights-out falls after midnight has that night on *tomorrow's* list, so there is nothing
    here to read and the bound is midnight — the evening still has to end when the day does. And a
    day that inherited a night from yesterday evening has a sleep block in the small hours, which
    is the night it is waking from; bounding the evening by that one clamps the whole day back to
    00:15, so it is skipped by the hour it starts at.
    """
    for activity in reversed(plan.activities):
        if activity.intent != "sleep" or activity.start_window is None:
            continue
        moment = activity.start_window.preferred
        if moment.hour >= _INHERITED_NIGHT_BEFORE_HOUR:
            return moment
    for activity in plan.activities:
        if activity.start_window is not None:
            midnight = time.min.replace(tzinfo=activity.start_window.preferred.tzinfo)
            return datetime.combine(plan.date + timedelta(days=1), midnight)
    return None


def _event_placement(placed: _PlacedEvent, seed: int) -> tuple[int, int, int]:
    """Where inside its band this occurrence lands: (start, latest start, duration) in minutes.

    Drawn here rather than inside `_event_activity` because the drive layer has to know the hours
    an event takes *before* the day plan exists — an unplanned call dropped into a Sunday that a
    four-hour family dinner already owns is two mandatory activities over the same hour. The draw
    is keyed on the event and the day, so both callers get the same answer.
    """
    event = placed.event
    low = _to_minutes(event.window_start)
    high = _to_minutes(event.window_end)
    rng = _rng(seed, "event-time", event.event_id, placed.day.isoformat())
    # Start late enough that the shortest acceptable duration still ends inside the declared band.
    latest_start = max(low, high - event.minimum_minutes)
    start_minutes = rng.randint(low, latest_start)
    return start_minutes, latest_start, rng.randint(event.minimum_minutes, event.maximum_minutes)


def _event_spans(placed: Sequence[_PlacedEvent], seed: int) -> list[tuple[int, int]]:
    """The day's placed events as (start, end) minutes after midnight, ends taken generously."""
    return [
        (start, start + item.event.maximum_minutes)
        for item in placed
        for start, _, _ in (_event_placement(item, seed),)
    ]


def _event_activity(
    placed: _PlacedEvent, index: int, tz: ZoneInfo, actor_id: str, seed: int
) -> Activity:
    event = placed.event
    low = _to_minutes(event.window_start)
    start_minutes, latest_start, preferred = _event_placement(placed, seed)
    moment = at_offset(placed.day, start_minutes, tz)
    # An event without an explicit intent is mapped from its label, exactly as a habit is.
    intent = event.intent or label_to_intent(event.label)
    location = _intent_location(intent)
    if location is None:
        raise ExpansionError(
            f"event {event.event_id!r} names intent {intent!r}, which the catalog does not define"
        )
    # Like a habit, an event is given its whole declared band, not a sliver around the draw.
    earliest = at_offset(placed.day, low, tz)
    latest = at_offset(placed.day, latest_start, tz)
    return Activity(
        activity_id=f"{placed.day.isoformat()}_{index:02d}_event_{event.event_id}",
        actor_id=actor_id,
        intent=intent,
        location_ids=[location],
        start_window=DateTimeWindow(
            earliest=earliest, preferred=moment, latest=max(latest, moment)
        ),
        duration=DurationRange(
            minimum_minutes=event.minimum_minutes,
            preferred_minutes=preferred,
            maximum_minutes=event.maximum_minutes,
        ),
        mandatory=True,
        labels=[f"event:{event.event_id}"],
    )


def _resolve_overlaps(activities: list[Activity], lights_out: datetime | None) -> list[Activity]:
    """Push preferred starts forward so a day's plan does not ask to be in two places at once.

    Widening windows gave the compiler room, but it also let neighbouring bands overlap: dinner
    may prefer 20:40 while television prefers 20:55 and dinner runs an hour. Left alone the
    compiler has to reject and re-place 18% of all preferred values, and each rejection costs it a
    search. A person does not plan two things over each other in the first place, so the day is
    made coherent here and the compiler is left to confirm it — which is the cheap case — while
    the wide windows stay available for the collisions that are genuine, like an all-day event.

    Only the preferred moment moves; the declared window is never narrowed, so nothing the author
    allowed becomes unreachable. And it never moves past lights-out: overlapping the night is
    legitimate work for the compiler, which can shorten either side, but *starting* after it is not
    something the compiler can repair into sense — the resident would be going to bed and then
    turning the television on.

    ``lights_out`` comes from `_lights_out`, the same reading `_wobble` is given, rather than being
    worked out here a second time. Doing it here meant taking the earliest `sleep` on the list, and
    since a night that runs past midnight belongs to the day it ends on, the earliest sleep on such
    a day is the night the resident is *waking from* — 01:22, not 23:50. Every waking hour is after
    that, so the bound below rejected every push and the pass did nothing at all on those days.
    They are not rare, and they became less rare when the bedtime distribution was widened to match
    the real log: 156 of 365 nights cross midnight for a 23:45 chronotype. `_lights_out` already
    documents the trap and steps around it by the hour the block starts at.
    """
    night = (
        lights_out - timedelta(minutes=EVENING_CLEARANCE_MINUTES)
        if lights_out is not None
        else None
    )
    ordered = sorted(
        activities,
        key=lambda item: (
            item.start_window.preferred if item.start_window else datetime.max,
            item.activity_id,
        ),
    )
    resolved: list[Activity] = []
    free_from: datetime | None = None
    for activity in ordered:
        window = activity.start_window
        if window is None or activity.duration is None:
            resolved.append(activity)
            continue
        preferred = window.preferred
        # A commitment's hours are not the resident's to move, so it anchors the day rather than
        # yielding to it: it still pushes the frontier forward, it just never slides itself.
        #
        # The wake anchors for a different reason. It is not queued behind the night, it is where
        # the night ends, so sliding it to clear the sleep block is backwards — and it is how the
        # last of the out-of-order mornings survived the bound `_wobble` now applies: pushed past
        # a breakfast whose own window was too narrow to be pushed after it, the resident had
        # breakfast at 08:10 and woke at 08:15. Left where it is, it pushes the morning instead,
        # and the overlap with the night is the one thing the compiler is genuinely good at: the
        # night's duration has fifteen per cent of give either way.
        fixed = activity.intent == "wake_up" or any(
            label.startswith("commitment:") for label in activity.labels
        )
        if (
            not fixed
            and free_from is not None
            and preferred < free_from <= window.latest
            # Never across local midnight: an activity belongs to the day whose date its preferred
            # start names, so a push past it silently reassigns the activity to a day that does not
            # list it and the scenario is rejected with ACTIVITY_ASSIGNED_TO_WRONG_DAY. It is the
            # terminal night that gets caught — a long evening running to 00:04 against a 23:54
            # lights-out whose window still reaches 00:09 — and the night is exactly the one
            # activity nothing follows, so leaving it on its own preferred moment costs nothing:
            # the window is untouched and the compiler still has the room to settle the overlap.
            and free_from.date() == preferred.date()
            and (night is None or activity.intent == "sleep" or free_from <= night)
        ):
            preferred = free_from
        resolved.append(
            activity.model_copy(
                update={
                    "start_window": DateTimeWindow(
                        earliest=min(window.earliest, preferred),
                        preferred=preferred,
                        latest=max(window.latest, preferred),
                    )
                }
            )
        )
        # The furthest end seen so far, not the last one seen: a short activity starting after a
        # long one must not reset the frontier and let the next one slide back under it.
        end = preferred + timedelta(minutes=activity.duration.preferred_minutes)
        free_from = end if free_from is None else max(free_from, end)
    return resolved


def _commitment_active_on(commitment: FixedCommitment, day: date) -> bool:
    if day.strftime("%A").lower() not in {item.value for item in commitment.weekdays}:
        return False
    if commitment.start_date is not None and day < commitment.start_date:
        return False
    return not (commitment.end_date is not None and day > commitment.end_date)


def _commitment_spans(resident: OutlineResident, day: date) -> list[tuple[int, int]]:
    """The day's fixed commitments as (start, end) minutes after midnight."""
    return [
        (_to_minutes(commitment.start_time), _to_minutes(commitment.end_time))
        for commitment in resident.fixed_commitments
        if _commitment_active_on(commitment, day)
    ]


def _commitment_spans_by_day(
    resident: OutlineResident, days: Sequence[CalendarDay]
) -> dict[date, list[tuple[int, int]]]:
    """Every fixed commitment of each day, as (start, end) minutes after midnight.

    The drive model shapes the night from the resident's chronotype alone, which is right for a day
    she owns and wrong for a day someone else has already claimed part of. The first morning
    commitment turns a free-running wake into an alarm; the whole spans are what let a night shift
    be recognised as one, so that the sleep moves to the morning after it instead of being laid
    over the hours the resident is at work.
    """
    spans: dict[date, list[tuple[int, int]]] = {}
    for calendar_day in days:
        day = date.fromisoformat(calendar_day.date)
        today = [
            (_to_minutes(commitment.start_time), _to_minutes(commitment.end_time))
            for commitment in resident.fixed_commitments
            if _commitment_active_on(commitment, day)
        ]
        if today:
            spans[day] = sorted(today)
    return spans


def _commitment_activities(
    resident: OutlineResident, day: date, tz: ZoneInfo, index: int
) -> list[Activity]:
    """Materialise the fixed commitments that fall on this day.

    A commitment is the one thing in the outline with real clock times, because its hours are set
    by someone other than the resident. It is therefore emitted with a tight window: there is
    nothing for the placement engine to decide, and widening it would invite the compiler to move
    a shift that cannot move. Everything else on the day gives way to it instead.
    """
    activities: list[Activity] = []
    emitted: dict[str, tuple[FixedCommitment, Activity]] = {}
    for offset, commitment in enumerate(resident.fixed_commitments):
        if not _commitment_active_on(commitment, day):
            continue
        assert commitment.intent is not None  # guaranteed by _check_intents
        location = _intent_location(commitment.intent)
        assert location is not None
        start = at_offset(day, _to_minutes(commitment.start_time), tz)
        minutes = _to_minutes(commitment.end_time) - _to_minutes(commitment.start_time)
        activities.append(
            Activity(
                activity_id=f"{day.isoformat()}_{index + offset:02d}_commitment_"
                f"{commitment.commitment_id}",
                actor_id=resident.resident_id,
                intent=commitment.intent,
                location_ids=[location],
                start_window=window_around(start, timedelta(minutes=MINIMUM_FLEX_MINUTES)),
                duration=DurationRange(
                    minimum_minutes=minutes, preferred_minutes=minutes, maximum_minutes=minutes
                ),
                mandatory=True,
                labels=[f"commitment:{commitment.commitment_id}"],
            )
        )
        emitted[commitment.commitment_id] = (commitment, activities[-1])
    return _back_to_back(list(emitted.values()), activities)


def _back_to_back(
    emitted: list[tuple[FixedCommitment, Activity]], activities: list[Activity]
) -> list[Activity]:
    """A commitment that ends when another begins is followed by it, with nothing in between.

    The author wrote the commute as ending at 07:00 and the shift as starting at 07:00. Each got the
    tight window every commitment gets, and the compiler used the slack between them: three
    mornings in a month it moved the shift to 07:12 and put breakfast at home in the gap, so the
    resident travelled to the hospital, came back to eat and left again. A zero-lag dependency says
    what the declaration already meant. Only between commitments of one day: the two halves of a
    night shift sit either side of midnight, and the engine joins those.
    """
    follows: dict[str, str] = {}
    for first, first_activity in emitted:
        for second, second_activity in emitted:
            if first is not second and first.end_time == second.start_time:
                follows[second_activity.activity_id] = first_activity.activity_id
    if not follows:
        return activities
    return [
        item.model_copy(
            update={
                "dependency_groups": [
                    *item.dependency_groups,
                    DependencyGroup(
                        activity_ids=[follows[item.activity_id]],
                        minimum_lag_minutes=0,
                        maximum_lag_minutes=0,
                    ),
                ]
            }
        )
        if item.activity_id in follows
        else item
        for item in activities
    ]


# A meal has to be cooked before it is eaten, and nothing said so. Preparing lunch and eating it
# are two habits with two bands, the author's bands overlap by the best part of two hours, and
# between the two activities there was no ordering of any kind — no dependency, no precondition.
# The compiler is then free, and on a day with no slack it takes the freedom: it put `eat_lunch`
# at 12:19, squeezed to its twelve-minute minimum, and left `prepare_simple_lunch` at its own
# preferred 13:32. Twelve dinners of twenty-nine and five lunches of nine came out that way over
# one generated month, and what the replay showed was a woman at the stove making a lunch she had
# finished ninety minutes earlier.
#
# Breakfast joined the table when `prepare_breakfast` got a reference process model and with it a
# place in the authoring vocabulary. Until then the row would have been unreachable: no outline
# could declare a breakfast preparation, so there was never one to order the meal after.
_MEAL_AFTER_PREPARATION: dict[str, str] = {
    "eat_breakfast": "prepare_breakfast",
    "eat_lunch": "prepare_simple_lunch",
    "eat_dinner": "prepare_light_dinner",
}


def _cook_before_eating(activities: list[Activity]) -> list[Activity]:
    """Make each meal depend on the day's own preparation of it, where the day has one.

    The dependency is deliberately not added when the cooking is sacrificial and the meal is not.
    The solver reads a dependency as `presence(meal) <= presence(cooking)`, so tying a mandatory
    meal to an optional preparation makes the preparation mandatory by the back door — and on the
    day that could not fit it, over-constrains a horizon that used to schedule. Where the author
    made the cooking optional, an uncooked lunch is what they asked for.
    """
    earliest: dict[str, Activity] = {}
    for activity in activities:
        current = earliest.get(activity.intent)
        if current is None or activity.start_window.preferred < current.start_window.preferred:
            earliest[activity.intent] = activity
    updated: list[Activity] = []
    for activity in activities:
        cooking = earliest.get(_MEAL_AFTER_PREPARATION.get(activity.intent, ""))
        if (
            cooking is None
            or activity.dependency_groups
            or (activity.mandatory and not cooking.mandatory)
        ):
            updated.append(activity)
            continue
        updated.append(
            activity.model_copy(
                update={
                    "dependency_groups": [
                        DependencyGroup(activity_ids=[cooking.activity_id], minimum_lag_minutes=0)
                    ]
                }
            )
        )
    return updated


def _planning_world(outline: HorizonOutline) -> PlanningWorld:
    world: OutlineWorld = outline.world
    return PlanningWorld(
        world_id=f"{outline.outline_id}-world",
        # The persona identifier picks the rhythm archetype and names the world; with a
        # household it is the first resident's, because the field holds one and a house does not
        # have a persona. Every resident's own rhythm is built from her own `OutlineRhythm`.
        persona_id=outline.residents[0].profile.persona_id,
        scenario_id=outline.outline_id,
        title=outline.title,
        time_zone=outline.time_zone,
        seed=0,
        home_model=world.home_model,
        activity_catalog=VersionedReference(
            reference_id="activity_catalog", version=ACTIVITY_CATALOG_VERSION
        ),
        residents=[
            Resident(resident_id=item.resident_id, display_name=item.display_name or None)
            for item in outline.residents
        ],
        external_people=world.external_people,
        locations=world.locations,
        resources=world.resources,
        resident_placements=[
            ResidentInitialState(
                resident_id=item.resident_id,
                # Housemates have two bedrooms and are asleep in different ones; a couple sharing
                # a room leaves the field alone and both start where the household starts.
                location_id=outline.start_location_of(item),
                # A horizon opens at midnight of its first day, and the night that would have put
                # her to bed belongs to the evening before, which is outside it. Without saying so,
                # `awake` defaults true and the engine stands her up: the run began with six hours
                # of a resident on her feet in a dark bedroom, every horizon, and it is the first
                # thing anyone watching the replay sees. The persona world has always declared it;
                # this path never did.
                facts={"awake": False, **world.resident_facts},
            )
            for item in outline.residents
        ],
        resource_facts=world.resource_facts,
        environment_facts=world.environment_facts,
        provenance=outline.provenance,
    )


def _declared_activities(outline: HorizonOutline) -> list[RecurringActivity]:
    """Every recurring activity in the document, private and shared alike.

    The checks below are about the *horizon*, not about any one person, so they read the household
    flat. A joint dinner whose intent the package does not implement is exactly as fatal as a
    private one, and reporting it once rather than once per participant is what keeps the repair a
    single regeneration.
    """
    return [
        *(
            activity
            for resident in outline.residents
            for activity in resident.profile.recurring_activities
        ),
        *(item.activity for item in outline.household.joint_activities),
    ]


def _declared_events(outline: HorizonOutline) -> list[OutlineEvent]:
    return [event for resident in outline.residents for event in resident.events]


def _declared_commitments(outline: HorizonOutline) -> list[FixedCommitment]:
    return [item for resident in outline.residents for item in resident.fixed_commitments]


def _check_intents(outline: HorizonOutline) -> None:
    """Every habit and event must resolve to a catalog intent, and say so rather than be guessed.

    Label-keyword inference exists for the local pipeline, which writes those labels itself. On an
    externally authored outline it misfires silently: "Teach at Idioms High School" matches no
    keyword and lands on the default intent, so the scenario ends up performing `read_and_rest`
    while the package in the same document implements `pm_work_shift`. Both documents are
    individually valid and they disagree — the same shape of defect as an unenforced prompt rule,
    which is why the fallback is refused here instead of being improved.
    """
    unknown: list[str] = []
    unresolved: list[str] = []
    declared_activities = _declared_activities(outline)
    for activity in declared_activities:
        if activity.intent is None:
            inferred = label_to_intent(activity.label, activity.kind.value)
            if inferred == DEFAULT_INTENT:
                unresolved.append(
                    f"activity {activity.recurring_activity_id!r} ({activity.label!r})"
                )
            continue
        if _intent_location(activity.intent) is None:
            unknown.append(f"activity {activity.recurring_activity_id!r} -> {activity.intent!r}")
    for event in _declared_events(outline):
        if event.intent is not None and _intent_location(event.intent) is None:
            unknown.append(f"event {event.event_id!r} -> {event.intent!r}")
    for commitment in _declared_commitments(outline):
        if commitment.intent is None:
            unresolved.append(f"commitment {commitment.commitment_id!r}")
        elif _intent_location(commitment.intent) is None:
            unknown.append(f"commitment {commitment.commitment_id!r} -> {commitment.intent!r}")
    # Both lists are reported together: the fix is one regeneration, so it should be told
    # everything it has to change rather than one item per attempt.
    problems: list[str] = []
    if unknown:
        # A proposed intent is refused like any other until a researcher adds it, but the refusal
        # says where the fix is: in the vocabulary, not in the outline.
        proposed = [
            item.intent_id
            for item in outline.vocabulary_proposals.activities
            if _intent_location(item.intent_id) is None
        ]
        if proposed:
            unknown.append(
                "proposed and not yet in the vocabulary: "
                + ", ".join(repr(item) for item in proposed)
                + " (add them from the import preview, then import again)"
            )
        problems.append(
            "declare an intent the activity catalog does not define: " + "; ".join(unknown)
        )
    if unresolved:
        problems.append(
            "declare no intent and their label matches none, so it would silently become "
            f"{DEFAULT_INTENT!r}: " + "; ".join(unresolved)
        )
    owned = [
        f"activity {activity.recurring_activity_id!r} -> {activity.intent!r}"
        for activity in declared_activities
        if activity.intent in RHYTHM_OWNED_INTENTS
    ]
    if owned:
        problems.append(
            "declare an intent the drive model already produces, so it would be scheduled twice: "
            + "; ".join(owned)
        )
    if problems:
        raise ExpansionError(" | ".join(problems))


def _check_package_covers(outline: HorizonOutline, package: PersonalProcessPackage) -> None:
    """Refuse a package that does not implement, for each resident, every intent her days contain.

    The days carry more intents than the outline declares: the rhythm always adds a wake and a
    night, and adds a debt nap, a nocturnal bathroom trip or an unplanned reach-out when the drive
    state calls for one. A package written only against the declared activities therefore leaves
    those days referencing behaviour nobody authored — which ingestion reports as one
    `MISSING_PROCESS_BINDING` per activity. On the first real eight-month case that was 628
    errors for five missing models, so the check belongs here, before the days exist.

    Per resident, because a binding is. A package that implements dinner for one of two people has
    implemented it for one person, and read as a set of intents it looked complete. The shared
    activities count for every participant rather than only for whoever hosts them: the host is the
    first participant still in on the day, which changes with the calendar, and an activity allowed
    to degrade is performed by each of them separately.
    """
    bound: dict[str, set[str]] = defaultdict(set)
    for binding in package.bindings:
        bound[binding.resident_id].add(binding.intent)
    problems: list[str] = []
    for resident in outline.residents:
        who = resident.resident_id
        declared = {
            activity.intent
            for activity in [
                *resident.profile.recurring_activities,
                *(item.activity for item in outline.joint_activities_for(who)),
            ]
            if activity.intent is not None
        }
        declared |= {event.intent for event in resident.events if event.intent is not None}
        declared |= {
            commitment.intent
            for commitment in resident.fixed_commitments
            if commitment.intent is not None
        }
        missing_declared = sorted(declared - bound[who])
        missing_rhythm = sorted(RHYTHM_EMITTED_INTENTS - bound[who])
        if missing_declared:
            problems.append(
                f"the outline declares intents the process package does not implement for "
                f"{who!r}: " + ", ".join(missing_declared)
            )
        if missing_rhythm:
            problems.append(
                f"the rhythm emits these intents on its own and the process package must implement "
                f"them for {who!r} too: " + ", ".join(missing_rhythm)
            )
    if problems:
        raise ExpansionError(" | ".join(problems))


def _check_locations(outline: HorizonOutline) -> None:
    """Fail early and once if the world lacks a room the activity catalog places intents in.

    Without this the mismatch surfaces as one `UNKNOWN_ACTIVITY_LOCATION` per activity — 1 784 of
    them on the reference outline — which buries the single fact that actually needs fixing.
    """
    declared = {item.location_id for item in outline.world.locations}
    required = {spec.default_location for spec in INTENT_CATALOG}
    missing = sorted(required - declared)
    if missing:
        raise ExpansionError(
            "the outline world does not declare the location(s) the activity catalog places "
            f"intents in: {', '.join(missing)}"
        )


def _check_activity_locations(outline: HorizonOutline, package: PersonalProcessPackage) -> None:
    """Refuse a habit sent to a room that is not there, or that cannot perform it.

    An override is the outline saying "this habit happens *here*", and the two ways of getting it
    wrong both fail silently rather than loudly. A room that is not declared resolves to nothing,
    and a room with no furniture answering what the process model needs resolves to the per-region
    service anchor — which has no footprint, no contact sensor and no position of its own, so the
    activity runs in the middle of an empty room and the sensor log simply does not record it.
    Reading in a study with no chair in it is the case this exists for.

    The capability is the right unit to check, not the role: an action naming a role binds by name
    and an action naming none binds by capability, but every one of them needs *some* object in the
    room offering the capability. Checked against the same tables the binder uses.

    Neither failure exists outside the home. `outdoors` is where the activity catalog already puts
    `evening_walk` and `buy_groceries`, `_check_locations` above requires the world to declare it,
    and the world declares it `external` rather than `room` — so an outline naming it explicitly
    was saying something true, and was refused for it. It carries no resident-owned furniture by
    design, which is why the capability half is skipped there too; see the same exclusion, with the
    same reason, in `validate_rooms_are_furnished`.
    """
    rooms = {item.location_id for item in outline.world.locations if item.kind is LocationKind.room}
    away = {
        item.location_id for item in outline.world.locations if item.kind is LocationKind.external
    }
    by_room: dict[str, set[str]] = {}
    # A type the vocabulary does not know offers every capability, as it does for the binder
    # (`_offers`), the materializer and the preflight. Read here as offering none, it refused the
    # one way an outline can furnish what the vocabulary lacks: a yoga mat, in a vocabulary where
    # no piece of furniture declares `exercise_support`, was rejected by this check and would
    # have been bound to by every stage after it.
    permissive: set[str] = set()
    for resource in outline.world.resources:
        known = capabilities_for_entity_type(resource.resource_type)
        if known is None:
            permissive.add(resource.location_id)
        else:
            by_room.setdefault(resource.location_id, set()).update(known)
    models = {item.process_model_id: item for item in package.process_models}
    by_intent = {item.intent: models.get(item.process_model_id) for item in package.bindings}
    actions = load_action_catalog(package.catalogs.action_catalog.version)
    definitions = {item.action_type: item for item in actions.actions}

    problems: list[str] = []
    for activity in _declared_activities(outline):
        room = activity.location
        if room is None:
            continue
        if room in away:
            continue
        if room not in rooms:
            problems.append(
                f"recurring activity {activity.recurring_activity_id!r} happens in {room!r}, "
                "which the outline world does not declare as a room"
            )
            continue
        if room in permissive:
            continue
        intent = activity.intent or label_to_intent(activity.label, activity.kind.value)
        model = by_intent.get(intent)
        if model is None:
            continue
        needed: set[str] = set()
        for node in model.nodes:
            definition = definitions.get(node.action_type or "")
            if definition is None:
                continue
            needed.update(
                item.capability
                for item in definition.required_capabilities
                if item.capability not in _UNFURNISHED_CAPABILITIES
            )
        unmet = sorted(needed - by_room.get(room, set()))
        if unmet:
            problems.append(
                f"recurring activity {activity.recurring_activity_id!r} happens in {room!r}, "
                f"which holds nothing offering {', '.join(unmet)}"
            )
    if problems:
        raise ExpansionError(" | ".join(problems))


# The fixtures that make a room a bathroom. A room holding exactly one of them is private by
# default: two people cannot use one toilet or one shower at once, and the norm that keeps the
# second one outside while the first is in there is the ordinary one rather than the exception.
# Washbasins are absent on purpose — a basin is the fixture people *do* share a bathroom over.
_SANITARY_RESOURCE_TYPES = frozenset({"toilet", "shower", "bathtub"})


@dataclass(frozen=True)
class _PrivacyRule:
    """One resolved statement: while `subject` does `intents` in `location`, `excluded` stay out."""

    subject_id: str
    location_id: str
    excluded: frozenset[str]
    # Empty means the room is private whatever the subject is doing in it.
    intents: frozenset[str]

    def covers(self, resident_id: str, location_ids: Sequence[str], intent: str) -> bool:
        if resident_id != self.subject_id or self.location_id not in location_ids:
            return False
        return not self.intents or intent in self.intents


def _default_private_locations(outline: HorizonOutline) -> list[str]:
    """The rooms nobody had to declare, because getting this default wrong is not symmetric.

    Declared nothing, two residents are independent and a room with a single sanitary fixture is
    private. The two mistakes do not cost the same: a wrong permissive default is two people in one
    shower cabin — physically impossible, and silently false everywhere downstream of the plan —
    while a wrong restrictive default is a slightly formal cohabitation that a reader can see in
    the trace and correct in one line. Permissive settings are chosen, never inherited.

    A room the household explicitly shares is left alone, which is the one line.
    """
    fixtures: dict[str, int] = defaultdict(int)
    for resource in outline.world.resources:
        if resource.resource_type in _SANITARY_RESOURCE_TYPES:
            fixtures[resource.location_id] += 1
    shared = set(outline.household.shared_location_ids)
    return sorted(
        location_id
        for location_id, count in fixtures.items()
        if count == 1 and location_id not in shared
    )


def _privacy_rules(outline: HorizonOutline) -> list[_PrivacyRule]:
    """Every declared and defaulted privacy statement, resolved onto ordered pairs.

    Three sources, all of them ending in the same shape so the marking pass reads one list:

    - `location_privacy`, the directional form, plus its mirror where the author took the symmetric
      shorthand. Between two adults the norm is almost always reciprocal and is written once;
      between a parent and a small child it is not, and a symmetric-only contract could not say so;
    - a `sharing_policy` of `exclusive`, which is the same statement keyed by intent instead of by
      room: whichever room that intent happens in, the other member of the pair is not in it;
    - the sanitary default above.
    """
    roster = set(outline.resident_ids)
    rules: list[_PrivacyRule] = []

    def add(subject: str, location: str, excluded: set[str], intents: set[str]) -> None:
        narrowed = (excluded or roster) - {subject}
        if narrowed:
            rules.append(
                _PrivacyRule(
                    subject_id=subject,
                    location_id=location,
                    excluded=frozenset(narrowed),
                    intents=frozenset(intents),
                )
            )

    for declared in outline.household.location_privacy:
        excluded = set(declared.excluded_resident_ids)
        add(declared.subject_id, declared.location_id, excluded, set(declared.intents))
        if declared.symmetric:
            for other in excluded or (roster - {declared.subject_id}):
                add(other, declared.location_id, {declared.subject_id}, set(declared.intents))

    for policy in outline.household.sharing_policies:
        if policy.sharing is not SharingMode.exclusive:
            continue
        first, second = policy.between
        for subject, other in ((first, second), (second, first)):
            location = _intent_location(policy.intent)
            if location is not None:
                add(subject, location, {other}, {policy.intent})

    for location_id in _default_private_locations(outline):
        for subject in sorted(roster):
            add(subject, location_id, set(), set())
    return rules


def _mark_privacy(activities: list[Activity], rules: Sequence[_PrivacyRule]) -> list[Activity]:
    """Write on each activity who may not be in its room while it runs.

    The compiler never sees the outline, so the declaration has to travel with the day. It rides in
    `Activity.extensions` rather than in a new field because the scenario contract is frozen at
    1.0.0 and this is exactly what the escape hatch is for; the solver turns it into a pairwise
    non-overlap and a scenario that never heard of a household carries nothing and compiles as it
    always did.
    """
    if not rules:
        return activities
    marked: list[Activity] = []
    for activity in activities:
        excluded: set[str] = set()
        for rule in rules:
            if rule.covers(activity.actor_id, activity.location_ids, activity.intent):
                excluded |= rule.excluded
        # Whoever is taking part is, by definition, welcome: a shared shower is one use with two
        # participants, and the rule that empties the room is about the people who are not in it.
        excluded -= {*activity.participant_ids, activity.actor_id}
        if not excluded:
            marked.append(activity)
            continue
        marked.append(
            activity.model_copy(
                update={
                    "extensions": {
                        **activity.extensions,
                        PRIVACY_EXTENSION: sorted(excluded),
                    }
                }
            )
        )
    return marked


# What a body holds for as long as it is using it. A switch has one state, so a second `activate`
# of a tap that is already running fails its precondition and stops the run; a sanitary fixture
# holds one person. Everything else in a room — a chair, a shelf, the refrigerator door that is
# open for three seconds — is shared by being used in turn inside the same hour, and serialising
# whole activities over it would invent a queue no household has.
_HELD_CAPABILITIES = frozenset({"switchable", "personal_care_support"})


class _DeviceUses:
    """Which of the world's objects an activity holds, so the plan says so before anyone runs it.

    This is the serialisation half of ADR-026's two orthogonal declarations (the design document,
    §6.2). Privacy says who may be in the room; this says how many uses an object bears at once,
    and the answer was always `Resource.capacity`: a shower taken by two is one use with two
    participants, two independent showers at the same instant are two uses of one jet. The compiler
    has turned `required_resources` into `add_cumulative` since M3, and the engine queues a second
    request behind the first; neither ever fired, because nothing wrote a requirement. Two morning
    washes at one basin were placed on top of each other and the second tap failed at run time.

    The object is the one the environment binder will choose, found the way it finds it: the role
    the action names, else a word the action says, else the object the process just walked to,
    else the first provider — the activity's own rooms before any other, then by id. The binder
    needs a built home and runs after compilation, so it cannot be asked; the household test checks
    the two answers agree on a real run.
    """

    def __init__(self, outline: HorizonOutline, package: PersonalProcessPackage) -> None:
        catalog = load_action_catalog(package.catalogs.action_catalog.version)
        self._definitions = {item.action_type: item for item in catalog.actions}
        models = {item.process_model_id: item for item in package.process_models}
        self._models: dict[tuple[str, str], list[ProcessModel]] = defaultdict(list)
        for binding in package.bindings:
            model = models.get(binding.process_model_id)
            if model is not None:
                self._models[(binding.resident_id, binding.intent)].append(model)
        self._resources = list(outline.world.resources)
        self._members = {
            item.location_id: list(item.member_location_ids) for item in outline.world.locations
        }
        self._cache: dict[tuple[str, str, tuple[str, ...]], list[str]] = {}

    def of(self, activity: Activity) -> list[str]:
        key = (activity.actor_id, activity.intent, tuple(activity.location_ids))
        if key not in self._cache:
            rooms = self._rooms(activity.location_ids)
            held: set[str] = set()
            for model in self._models.get((activity.actor_id, activity.intent), []):
                held |= self._held_by(model, activity, rooms)
            self._cache[key] = sorted(held)
        return self._cache[key]

    def _rooms(self, location_ids: Sequence[str]) -> set[str]:
        rooms: set[str] = set()
        pending = list(location_ids)
        while pending:
            location_id = pending.pop()
            members = self._members.get(location_id, [])
            if members:
                pending.extend(item for item in members if item not in rooms)
            else:
                rooms.add(location_id)
        return rooms

    def _held_by(self, model: ProcessModel, activity: Activity, rooms: set[str]) -> set[str]:
        arguments: dict[str, dict[str, object]] = {}
        for node in model.nodes:
            if node.kind is not ProcessNodeKind.action:
                continue
            resolved: dict[str, object] = {}
            for name, expression in node.arguments.items():
                if expression.source is ValueSource.literal:
                    resolved[name] = expression.value
                elif expression.source is ValueSource.activity_intent:
                    resolved[name] = activity.intent
                elif expression.source is ValueSource.activity_location and expression.index < len(
                    activity.location_ids
                ):
                    resolved[name] = activity.location_ids[expression.index]
            arguments[node.node_id] = resolved
        standing = _standing_roles(model, arguments, self._definitions)

        held: set[str] = set()
        for node in model.nodes:
            definition = self._definitions.get(node.action_type or "")
            if node.kind is not ProcessNodeKind.action or definition is None:
                continue
            for requirement in definition.required_capabilities:
                if requirement.capability not in _HELD_CAPABILITIES:
                    continue
                found = self._provider(
                    requirement.capability,
                    arguments[node.node_id].get(requirement.parameter_name or ""),
                    arguments[node.node_id],
                    standing.get(node.node_id),
                    rooms,
                )
                if found is not None:
                    held.add(found)
        return held

    def _provider(
        self,
        capability: str,
        role: object,
        arguments: Mapping[str, object],
        standing: str | None,
        rooms: set[str],
    ) -> str | None:
        if role is not None:
            found = self._candidates(capability, str(role), rooms)
            # A role that names a capability rather than a role, as the binder allows.
            return found[0] if found else self._first_offering(str(role), rooms)
        for hint in sorted(str(value) for value in arguments.values() if isinstance(value, str)):
            found = self._candidates(capability, hint, rooms)
            if found:
                return found[0]
        if standing is not None:
            found = self._candidates(capability, standing, rooms)
            if found:
                return found[0]
        found = self._candidates(capability, None, rooms)
        return found[0] if found else None

    def _candidates(self, capability: str, role: str | None, rooms: set[str]) -> list[str]:
        # An object of a type the vocabulary does not know offers every capability, and the binder
        # takes it only after the room's own backstop — so it is held only where the process names
        # it. Guessed by capability, the Ferri outline's outdoor `exercise_surface` was held by all
        # 133 of the month's meal preparations, in a kitchen it is not in.
        matching = [
            item
            for item in self._resources
            if _offers(item.resource_type, capability)
            and (
                role is None
                or role
                in {
                    item.resource_id,
                    item.resource_type,
                    *RESOURCE_ROLE_ALIASES.get(item.resource_type, ()),
                }
            )
            and not (
                capabilities_for_entity_type(item.resource_type) is None
                and role not in {item.resource_id, item.resource_type}
            )
        ]
        return [
            item.resource_id
            for item in sorted(
                matching, key=lambda item: (item.location_id not in rooms, item.resource_id)
            )
        ]

    def _first_offering(self, capability: str, rooms: set[str]) -> str | None:
        matching = sorted(
            (
                item
                for item in self._resources
                if _offers(item.resource_type, capability)
                and capabilities_for_entity_type(item.resource_type) is not None
            ),
            key=lambda item: (
                item.location_id not in rooms,
                item.resource_type not in _BODY_SUPPORTING_TYPES,
                item.resource_id,
            ),
        )
        return matching[0].resource_id if matching else None


def _offers(resource_type: str, capability: str) -> bool:
    allowed = capabilities_for_entity_type(resource_type)
    return allowed is None or capability in allowed


def _mark_device_uses(activities: list[Activity], uses: _DeviceUses) -> list[Activity]:
    """Write on each activity the objects it holds, one use each, for the compiler and the engine.

    One use per activity whoever takes part: the shared shower is the host's process holding the
    jet, and the participant who joins her holds nothing of her own. The candidates the engine may
    turn down are marked too, but the compiler leaves them out and the engine arbitrates them live.
    """
    marked: list[Activity] = []
    for activity in activities:
        held = [
            item
            for item in uses.of(activity)
            if item not in {requirement.resource_id for requirement in activity.required_resources}
        ]
        if not held:
            marked.append(activity)
            continue
        marked.append(
            activity.model_copy(
                update={
                    "required_resources": [
                        *activity.required_resources,
                        *(ResourceRequirement(resource_id=item) for item in held),
                    ]
                }
            )
        )
    return marked


@dataclass(frozen=True)
class _ResidentHorizon:
    """Everything about one resident that is settled for the whole horizon, computed once.

    The per-day loop reads this and decides nothing structural: which days hold which occurrences,
    which events landed where, and which hours are already spoken for are all horizon-level facts,
    and recomputing them inside the loop is how two residents would start disagreeing about the
    same calendar.
    """

    resident: OutlineResident
    profile: BehavioralProfile
    calendar: CadenceCalendar
    days_by_date: dict[str, CalendarDay]
    placed_events: dict[str, list[_PlacedEvent]]
    recurring: dict[str, RecurringActivity]
    activity_locations: dict[str, str]
    # Commitments and placed events, as minutes after midnight. Known before any plan exists,
    # which is what lets co-presence be decided before the days are built.
    busy_by_date: dict[str, list[tuple[int, int]]]
    skipped: int
    rescheduled: int
    dropped: int


def _resident_horizon(
    outline: HorizonOutline, resident: OutlineResident, seed: int
) -> _ResidentHorizon:
    profile = _resident_profile(outline, resident)
    calendar = _effective_calendar(outline, resident, seed)
    placed = _place_events(resident, seed)
    calendar, skipped, moved, dropped = _apply_displacement(
        calendar, placed, _daily_capacity(profile, resident.phases)
    )
    return _ResidentHorizon(
        resident=resident,
        profile=profile,
        calendar=calendar,
        days_by_date={day.date: day for day in calendar.days},
        placed_events=placed,
        recurring=_activities_by_id(profile),
        # The rooms the outline overrode, by activity. Read once: a habit's room is a property of
        # the horizon, not of the day, so it cannot change between one calendar day and the next.
        activity_locations={
            item.recurring_activity_id: item.location
            for item in profile.recurring_activities
            if item.location is not None
        },
        busy_by_date={
            day.date: [
                *_commitment_spans(resident, date.fromisoformat(day.date)),
                *_event_spans(placed.get(day.date, []), seed),
            ]
            for day in calendar.days
        },
        skipped=skipped,
        rescheduled=moved,
        dropped=dropped,
    )


@dataclass(frozen=True)
class _SharedOccurrence:
    """One day's verdict on one shared activity: who is in, and whether it is one sitting."""

    joint: JointActivity
    participants: tuple[str, ...]
    shared: bool

    @property
    def recurring_activity_id(self) -> str:
        return self.joint.activity.recurring_activity_id

    @property
    def host_id(self) -> str:
        """The participant the single interval is emitted under.

        Somebody has to be the activity's `actor_id`, because the contract has one; the others ride
        on `participant_ids`, and the compiler occupies all of them alike through
        `occupied_residents()`. The first participant in household order is chosen so that the host
        is always built before the residents who have to be told those hours are taken.
        """
        return self.participants[0]


def _free_spans(window: tuple[int, int], busy: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """What is left of a band once the hours somebody else already owns are cut out of it."""
    spans = [window]
    for start, end in busy:
        remaining: list[tuple[int, int]] = []
        for low, high in spans:
            if end <= low or start >= high:
                remaining.append((low, high))
                continue
            if low < start:
                remaining.append((low, start))
            if high > end:
                remaining.append((end, high))
        spans = remaining
    return spans


def _overlap(first: list[tuple[int, int]], second: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return [
        (low, high)
        for a_low, a_high in first
        for b_low, b_high in second
        if (low := max(a_low, b_low)) < (high := min(a_high, b_high))
    ]


def _plan_sharing(
    outline: HorizonOutline, horizons: Sequence[_ResidentHorizon], seed: int
) -> dict[str, list[_SharedOccurrence]]:
    """Decide, per day, which of the household's shared activities actually happen together.

    This is the principle of ADR-018 extended to cohabitation: the author declares *the propensity
    to share*, and a deterministic pass decides *which concrete occurrences are shared*. Nobody
    writes "on Tuesday the 14th they have dinner together" — who is even in the house that Tuesday
    is known only after the commitments are placed and the events have landed.

    Three gates, and their order is the substance:

    1. **Who is still in.** A participant whose phase suspended the activity, or whose event
       displaced today's occurrence, is not at the table. With fewer than two left there is nothing
       to share, and whoever remains does it alone — which is what her own calendar already says.
    2. **Co-presence.** The participants' free stretches inside the declared band are intersected,
       and the longest one has to be worth sitting down for. A propensity can never conjure a
       shared dinner on a day whose bands do not meet, whatever number the author wrote; and
       `minimum_shared_minutes` is what stops a twelve-minute breakfast squeezed against somebody's
       departure from being published as a shared breakfast.
    3. **The draw.** Only for `optional_joint`, and only once the first two hold. One draw per
       (activity, day) from the horizon seed — the expander's existing pattern, deterministic
       without an evaluation order or a tie-break to get wrong, which a predicate language would
       have needed and where a bug would have been silent.

    A `joint` activity skips the third gate: given feasibility it happens, and the wait in front of
    it belongs to whoever got home first.
    """
    by_resident = {item.resident.resident_id: item for item in horizons}
    verdicts: dict[str, list[_SharedOccurrence]] = defaultdict(list)
    for joint in outline.household.joint_activities:
        activity_id = joint.activity.recurring_activity_id
        for calendar_day in horizons[0].calendar.days:
            iso = calendar_day.date
            present: list[tuple[str, ActivityOccurrence]] = []
            for who in joint.participant_ids:
                day = by_resident[who].days_by_date.get(iso)
                occurrence = next(
                    (
                        item
                        for item in (day.occurrences if day is not None else ())
                        if item.recurring_activity_id == activity_id
                    ),
                    None,
                )
                if occurrence is not None:
                    present.append((who, occurrence))
            if not present:
                continue
            participants = tuple(who for who, _ in present)
            if len(present) < 2:
                verdicts[iso].append(
                    _SharedOccurrence(joint=joint, participants=participants, shared=False)
                )
                continue
            common: list[tuple[int, int]] | None = None
            for who, occurrence in present:
                band = (_to_minutes(occurrence.window_start), _to_minutes(occurrence.window_end))
                free = _free_spans(band, by_resident[who].busy_by_date.get(iso, []))
                common = free if common is None else _overlap(common, free)
            widest = max((high - low for low, high in (common or [])), default=0)
            shared = widest >= max(joint.minimum_shared_minutes, 1)
            if shared and joint.sharing is SharingMode.optional_joint:
                assert joint.propensity is not None  # guaranteed by the contract
                draw = _rng(seed, "sharing", activity_id, iso).random()
                shared = draw < joint.propensity.on(date.fromisoformat(iso))
            verdicts[iso].append(
                _SharedOccurrence(joint=joint, participants=participants, shared=shared)
            )
    return dict(verdicts)


def _company_at_home(
    resident_id: str,
    days: Sequence[CalendarDay],
    sharing: dict[str, list[_SharedOccurrence]],
    social: dict[date, int],
) -> dict[date, int]:
    """A shared occurrence is company, whatever its intent happens to be called.

    `_scheduled_drive_load` counts social contact by intent category, which is right for a visit
    and wrong for a housemate: having dinner with the person you live with *is* company, and the
    intent of it is `eat_dinner`. Left uncounted, the need for company climbs in a resident who is
    never alone, hits its ceiling, stops varying, and sends her out every evening of the horizon to
    fix a loneliness the house had already fixed.

    Only occurrences that were actually shared count, and only the ones the category did not
    already count, so a declared visit is not paid for twice.
    """
    counted = dict(social)
    for day in days:
        extra = 0
        for occasion in sharing.get(day.date, ()):
            if not occasion.shared or resident_id not in occasion.participants:
                continue
            activity = occasion.joint.activity
            intent = activity.intent or label_to_intent(activity.label, activity.kind.value)
            if intent_spec(intent).category is not IntentCategory.social:
                extra += 1
        if extra:
            key = date.fromisoformat(day.date)
            counted[key] = counted.get(key, 0) + extra
    return counted


def _resident_rhythms(
    horizon: _ResidentHorizon, sharing: dict[str, list[_SharedOccurrence]], seed: int
) -> dict[str, DayRhythm]:
    """One chain of nights per resident. Sleep debt is personal and does not pool."""
    resident = horizon.resident
    rhythm_profile = replace(
        RhythmProfile.from_persona(
            horizon.profile.persona_id, resident.rhythm.age, resident.rhythm.health
        ),
        chronotype_bedtime_minutes=_to_minutes(resident.rhythm.chronotype_bedtime),
    )
    # Shared occurrences sit in every participant's calendar, so a joint dinner already scales the
    # hunger of everyone who eats it; without that the non-hosting resident would accumulate an
    # appetite nothing ever spends.
    meals, social = _scheduled_drive_load(horizon.calendar.days)
    return plan_rhythms(
        rhythm_profile,
        [date.fromisoformat(day.date) for day in horizon.calendar.days],
        seed=seed,
        meals_by_day=meals,
        social_by_day=_company_at_home(
            resident.resident_id, horizon.calendar.days, sharing, social
        ),
        commitment_spans_by_day=_commitment_spans_by_day(resident, horizon.calendar.days),
    )


def _span_of(activity: Activity) -> tuple[int, int] | None:
    """The activity's preferred hours as minutes after midnight, or nothing if it has none."""
    if activity.start_window is None or activity.duration is None:
        return None
    start = activity.start_window.preferred
    low = start.hour * 60 + start.minute
    return low, low + activity.duration.preferred_minutes


def _resident_day(
    outline: HorizonOutline,
    horizon: _ResidentHorizon,
    rhythms: dict[str, DayRhythm],
    calendar_day: CalendarDay,
    *,
    tz: ZoneInfo,
    fillable: tuple[str, ...],
    seed: int,
    index_offset: int,
    busy_minutes: Sequence[tuple[int, int]],
    hosted: Mapping[str, tuple[str, ...]],
    degradable: Mapping[str, tuple[str, ...]],
) -> DayPlan:
    """One resident's own day, built exactly as a single-resident horizon builds it.

    The household is visible here in three places and nowhere else: `busy_minutes`, the hours a
    shared activity has already claimed on behalf of a participant who is not hosting it; the
    occurrences the caller removed from `calendar_day` because the household emits them once; and
    `hosted`, the shared occurrences this resident *is* hosting, which are named with their
    participants before the fillers are seeded so that the wait in front of one lands in the room
    it is a wait for.
    """
    resident = horizon.resident
    day_date = date.fromisoformat(calendar_day.date)
    day_events = horizon.placed_events.get(calendar_day.date, [])
    plan = build_day_plan(
        calendar_day,
        timezone=outline.time_zone,
        actor_id=resident.resident_id,
        rhythm=rhythms.get(calendar_day.date),
        previous_rhythm=rhythms.get((day_date - timedelta(days=1)).isoformat()),
        seed=seed,
        busy_minutes=busy_minutes,
        activity_locations=horizon.activity_locations,
        index_offset=index_offset,
    )
    effective = _effective_activities(resident.phases, horizon.recurring, day_date)
    bands = _sub_bands(plan.activities, effective)
    activities = [
        _wobble(
            activity,
            effective.get(_recurring_activity_id_of(activity) or ""),
            tz,
            seed,
            bands.get(activity.activity_id),
            _lights_out(plan),
            _wake(plan),
        )
        for activity in plan.activities
    ]
    # One interval, every participant named on it. `occupied_residents()` reads `participant_ids`
    # and occupies all of them, so the household's dinner keeps everybody who eats it out of
    # anything else for its duration — and the solver pushes it past whichever of them is still on
    # the way home, which is where the wait in front of it comes from.
    activities = [
        activity.model_copy(
            update={
                "participant_ids": _other_participants(
                    hosted[_recurring_activity_id_of(activity) or ""], activity.actor_id
                )
            }
        )
        if (_recurring_activity_id_of(activity) or "") in hosted
        else activity
        for activity in activities
    ]
    activities = _offer_both_arms(activities, degradable, day_date)
    for index, item in enumerate(day_events):
        activities.append(
            _event_activity(
                item, index_offset + len(activities) + index, tz, resident.resident_id, seed
            )
        )
    activities.extend(
        _commitment_activities(resident, day_date, tz, index_offset + len(activities))
    )
    activities = _seed_filler_candidates(
        activities,
        fillable,
        _wake(plan),
        _lights_out(plan),
        day_date,
        resident.resident_id,
        seed,
        index_offset=index_offset,
    )
    activities = _resolve_overlaps(activities, _lights_out(plan))
    activities = _cook_before_eating(activities)
    activities = _to_own_bedroom(activities, _bedroom_of(outline, resident))
    return plan.model_copy(update={"activities": activities})


# How long the one who got home first waits for the one still on the way, at most. The design's
# own figure for "arrives, and then they eat together" (§6.3): long enough to finish cooking and
# lay the table, short enough that a meal an hour after somebody walked in is not the same meal.
SHARED_ARRIVAL_MAXIMUM_LAG_MINUTES = 20


def _anchor_to_last_arrival(activities: list[Activity], away: frozenset[str]) -> list[Activity]:
    """Start a shared activity soon after the last participant comes home, not merely after.

    No-overlap already keeps a shared lunch out of the hours a participant is still at work, so it
    cannot begin before she is back; nothing kept it from beginning three hours later, with the one
    who got home first "waiting" through an afternoon. The design names the missing piece: a
    dependency on the later participant's return, with a maximum lag.

    Added only where it cannot manufacture an impossible day. The absence has to be mandatory —
    a dependency reads `presence(shared) <= presence(absence)` — and has to end inside the shared
    activity's window whatever the compiler does with it: at its latest end no later than the
    latest start, and at its earliest end no earlier than the lag before the earliest start. An
    absence that is over well before the band opens involves no waiting at all, and one that ends
    after it closes is a day `_plan_sharing` has already declared unshared.

    Anchored to the latest arrival only. Everybody else is home by then, so the one dependency is
    the whole statement.
    """
    shared = [item for item in activities if item.participant_ids and item.start_window]
    if not shared:
        return activities
    absences = [
        item
        for item in activities
        if item.mandatory
        and not item.can_overlap_for_actor
        and item.start_window is not None
        and item.duration is not None
        and item.location_ids
        and item.location_ids[0] in away
    ]
    lag = timedelta(minutes=SHARED_ARRIVAL_MAXIMUM_LAG_MINUTES)
    anchors: dict[str, Activity] = {}
    for activity in shared:
        window = activity.start_window
        assert window is not None
        people = {activity.actor_id, *activity.participant_ids}
        candidates = []
        for absence in absences:
            if absence.actor_id not in people:
                continue
            assert absence.start_window is not None and absence.duration is not None
            earliest_end = absence.start_window.earliest + timedelta(
                minutes=absence.duration.minimum_minutes
            )
            latest_end = absence.start_window.latest + timedelta(
                minutes=absence.duration.maximum_minutes
            )
            if latest_end <= window.latest and earliest_end + lag >= window.earliest:
                candidates.append((latest_end, absence.activity_id, absence))
        if candidates:
            anchors[activity.activity_id] = max(candidates, key=lambda item: item[:2])[2]
    if not anchors:
        return activities
    return [
        item.model_copy(
            update={
                "dependency_groups": [
                    *item.dependency_groups,
                    DependencyGroup(
                        activity_ids=[anchors[item.activity_id].activity_id],
                        minimum_lag_minutes=0,
                        maximum_lag_minutes=SHARED_ARRIVAL_MAXIMUM_LAG_MINUTES,
                    ),
                ]
            }
        )
        if item.activity_id in anchors
        else item
        for item in activities
    ]


# What a body sleeps in. A room holding one of these is somewhere a resident can have her nights.
_SLEEPING_RESOURCE_TYPES = frozenset({"bed", "single_bed", "double_bed", "sofa_bed"})
# The intents that happen in the resident's own bedroom rather than in the room the catalog names:
# the night, the waking from it, the nap in her bed. The nocturnal toilet trip is the fourth, and
# it is the *return* half of it that is hers.
_OWN_BEDROOM_INTENTS = frozenset({"sleep", "wake_up", "rest_or_nap"})
_RETURNS_TO_BED_INTENTS = frozenset({"night_toilet_visit"})


def _bedroom_of(outline: HorizonOutline, resident: OutlineResident) -> str | None:
    """The room this resident sleeps in, when it is not the one the catalog puts every night in.

    A resident starts the horizon asleep, so where she is at midnight of the first day is where her
    bed is; `start_location_id` says so for the housemate in the second bedroom. It was only ever
    read for that first midnight, and every night after it she walked to the catalog's `bedroom`
    and lay down in her housemate's bed — two friends splitting the rent sharing one, which is the
    first thing §6 of the design says they do not do. Honoured only where the room holds something
    to sleep in, so a horizon that opens with somebody dozing on the sofa is not moved there for
    every night of it.
    """
    room = outline.start_location_of(resident)
    default = _intent_location("sleep")
    if room == default:
        return None
    beds = {
        item.location_id
        for item in outline.world.resources
        if item.resource_type in _SLEEPING_RESOURCE_TYPES
    }
    return room if room in beds else None


def _to_own_bedroom(activities: list[Activity], bedroom: str | None) -> list[Activity]:
    """Put the nights, and the returns to bed, in the resident's own room."""
    default = _intent_location("sleep")
    if bedroom is None or default is None:
        return activities
    moved: list[Activity] = []
    for activity in activities:
        rooms = list(activity.location_ids)
        if activity.intent in _OWN_BEDROOM_INTENTS and rooms[:1] == [default]:
            rooms[0] = bedroom
        elif activity.intent in _RETURNS_TO_BED_INTENTS and rooms[1:2] == [default]:
            rooms[1] = bedroom
        moved.append(
            activity
            if rooms == activity.location_ids
            else activity.model_copy(update={"location_ids": rooms})
        )
    return moved


def _commitment_spans_on(resident: OutlineResident, weekday: Weekday) -> list[tuple[int, int]]:
    return [
        (_to_minutes(item.start_time), _to_minutes(item.end_time))
        for item in resident.fixed_commitments
        if weekday in item.weekdays
    ]


def _check_household(outline: HorizonOutline) -> None:
    """Refuse a household whose declarations cannot all be true at once, and say which.

    Two failures that a solver would otherwise discover late and report as an infeasible day with
    no reason attached. Both are cheap here because both are properties of the *declaration* rather
    than of any particular day: fixed commitments recur by weekday, and a privacy rule does not
    change over the horizon.

    - **A shared activity whose participants are never both free for it.** A propensity above zero
      on an activity whose bands never meet produces a shared occurrence that is declared and never
      happens, and the only way to notice is to read the trace. The check is the same one
      `_plan_sharing` performs per day, run over the seven weekdays against the commitments alone:
      if no weekday admits it, no date will either.
    - **Two people and one bed.** Privacy over the room the night happens in cannot hold for a pair
      who both sleep every night: there is one such room, each of them needs about eight hours of
      it, and the day has twenty-four. The solver would spend its budget proving that.

    Both are raised as sentences a researcher can act on, which is the argument §6.2 makes for
    privacy over capacity: "Marco does not share the bathroom while he washes, and Luca's morning
    has no other window" is readable, and `capacity 1 exceeded` is not.
    """
    problems: list[str] = []
    by_id = {item.resident_id: item for item in outline.residents}

    for joint in outline.household.joint_activities:
        cadence = joint.activity.cadence
        band = (_to_minutes(cadence.window_start), _to_minutes(cadence.window_end))
        allowed = cadence.weekdays or list(Weekday)
        widest = 0
        for weekday in allowed:
            common: list[tuple[int, int]] | None = None
            for who in joint.participant_ids:
                free = _free_spans(band, _commitment_spans_on(by_id[who], weekday))
                common = free if common is None else _overlap(common, free)
            widest = max(widest, max((high - low for low, high in (common or [])), default=0))
        needed = max(joint.minimum_shared_minutes, 1)
        if widest < needed:
            problems.append(
                f"shared activity {joint.activity.recurring_activity_id!r} asks "
                f"{', '.join(joint.participant_ids)} for {needed} minute(s) together inside "
                f"{cadence.window_start}-{cadence.window_end}, and their fixed commitments never "
                f"leave them more than {widest}"
            )

    night = _intent_location("sleep")
    # Two friends splitting the rent do not share a bed (§6), and a house that follows the family
    # gives them two rooms (§11). Declared housemates who would still spend every night in one room
    # are refused here, in a sentence, unless the household chose to share it — permissive settings
    # are chosen, never inherited. A couple, a parent with a child and siblings may share a room.
    separate = {RelationKind.housemates, RelationKind.other}
    shared_rooms = set(outline.household.shared_location_ids)
    for relation in outline.household.relations:
        if relation.kind not in separate:
            continue
        rooms = {
            who: _bedroom_of(outline, by_id[who]) or night
            for who in relation.between
            if who in by_id
        }
        if len(rooms) == 2 and len(set(rooms.values())) == 1:
            room = next(iter(rooms.values()))
            if room not in shared_rooms:
                problems.append(
                    f"{' and '.join(sorted(rooms))} are {relation.kind.value} and would both sleep "
                    f"in {room!r} every night; give one of them a start location in a room with a "
                    "bed of its own, or share the room in household.sharedLocationIds"
                )
    if night is not None:
        for privacy in outline.household.location_privacy:
            if privacy.location_id != night or privacy.intents:
                continue
            excluded = privacy.excluded_resident_ids or [
                item for item in outline.resident_ids if item != privacy.subject_id
            ]
            if excluded:
                problems.append(
                    f"{privacy.subject_id!r} does not share {night!r} with "
                    f"{', '.join(sorted(excluded))}, and there is one such room for two nights "
                    "of about eight hours each"
                )
    if problems:
        raise ExpansionError(" | ".join(problems))


def expand_outline(
    outline: HorizonOutline,
    package: PersonalProcessPackage,
    *,
    seed: int = 0,
) -> ExpansionResult:
    """Turn one outline into one authoring bundle covering the whole horizon.

    The result is an ordinary `SimulationAuthoringBundle` and enters the unchanged ingestion flow,
    which is what keeps every frozen contract downstream untouched.

    One house, one log, N residents. Each resident's day is built the way a single-resident horizon
    has always built it — her own calendar, her own drives, her own fillers, her own overlap pass —
    and the days are then merged into one plan per date. The household enters in three places and
    no others: a shared occurrence is emitted once with its participants named, the residents who
    are not hosting it are told those hours are taken, and a private activity is marked with who it
    keeps out of the room. Everything else that makes cohabitation work was already in the
    compiler, which keeps one no-overlap chain per resident and serialises the uses of a shower
    that only has one jet.
    """
    _check_intents(outline)
    _check_locations(outline)
    _check_activity_locations(outline, package)
    _check_package_covers(outline, package)
    _check_household(outline)

    horizons = [_resident_horizon(outline, resident, seed) for resident in outline.residents]
    sharing = _plan_sharing(outline, horizons, seed)
    rhythms = [_resident_rhythms(horizon, sharing, seed) for horizon in horizons]
    privacy = _privacy_rules(outline)
    uses = _DeviceUses(outline, package)
    away = frozenset(
        item.location_id for item in outline.world.locations if item.kind is LocationKind.external
    )

    tz = ZoneInfo(outline.time_zone)
    # Only what each resident's own bindings can perform: a filler is behaviour nobody declared, so
    # it must not be the reason a horizon is refused. Per resident, not per package — read off the
    # whole household, a coffee only one of two people has a process for was offered to both, and
    # a month for a couple was refused 62 times for the one who never makes it.
    implemented: dict[str, set[str]] = defaultdict(set)
    for binding in package.bindings:
        implemented[binding.resident_id].add(binding.intent)
    fillable = {
        resident.resident_id: tuple(
            item for item in FILL_INTENTS if item in implemented[resident.resident_id]
        )
        for resident in outline.residents
    }

    days: list[DayPlan] = []
    calendar_dates = [day.date for day in horizons[0].calendar.days]
    for iso in calendar_dates:
        occasions = sharing.get(iso, [])
        hosted = {
            item.recurring_activity_id: item
            for item in occasions
            if item.shared and not item.joint.degrade_to_independent
        }
        # A degradable occurrence is written twice and chosen once, so nobody's calendar loses it:
        # every participant keeps the meal she would have had alone, and the host gains a second
        # copy naming everyone. Which of the two survives is the compiler's, because it is the only
        # layer that can see whether the shared version fits the day.
        degradable = {
            item.recurring_activity_id: (item.participants, item.joint.minimum_shared_minutes)
            for item in occasions
            if item.shared and item.joint.degrade_to_independent
        }
        merged: list[Activity] = []
        shell: DayPlan | None = None
        # Filled in as each host's day is built, and read by the participants built after it. The
        # host is the first participant in household order, so the hours are always known in time.
        borrowed: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for horizon, chain in zip(horizons, rhythms, strict=True):
            who = horizon.resident.resident_id
            calendar_day = horizon.days_by_date[iso]
            elsewhere = {
                activity_id
                for activity_id, occasion in hosted.items()
                if occasion.host_id != who and who in occasion.participants
            }
            plan = _resident_day(
                outline,
                horizon,
                chain,
                calendar_day.model_copy(
                    update={
                        "occurrences": [
                            item
                            for item in calendar_day.occurrences
                            if item.recurring_activity_id not in elsewhere
                        ]
                    }
                ),
                tz=tz,
                fillable=fillable[who],
                seed=seed,
                index_offset=len(merged),
                busy_minutes=[*horizon.busy_by_date.get(iso, []), *borrowed[who]],
                hosted={
                    activity_id: occasion.participants
                    for activity_id, occasion in hosted.items()
                    if occasion.host_id == who
                },
                degradable=degradable,
            )
            for activity in plan.activities:
                occasion = hosted.get(_recurring_activity_id_of(activity) or "")
                if occasion is None or occasion.host_id != who:
                    continue
                span = _span_of(activity)
                if span is not None:
                    for other in occasion.participants:
                        if other != who:
                            borrowed[other].append(span)
            merged.extend(_mark_device_uses(_mark_privacy(list(plan.activities), privacy), uses))
            if shell is None:
                shell = plan
        assert shell is not None  # residents is non-empty by contract
        # Only now: the host's shared lunch and the other participant's shift are written in two
        # different residents' days, and the dependency needs both.
        merged = _anchor_to_last_arrival(merged, away)
        if iso == calendar_dates[-1]:
            # The horizon stops at midnight after the last day, so whatever is still running then
            # is truncated rather than made infeasible. This is what the flag is for; the evening
            # activities of every other day have the next morning to spill into.
            merged = [
                item.model_copy(update={"allow_boundary_truncation": True}) for item in merged
            ]
        days.append(shell.model_copy(update={"activities": merged}))

    window = SimulationWindow(
        start=datetime.combine(outline.start_date, time.min, tz),
        end=datetime.combine(outline.end_date, time.min, tz),
    )
    scenario = assemble_scenario(
        _planning_world(outline),
        days=days,
        window=window,
        seed=seed,
        provenance=Provenance(
            author_type=AuthorType.rule_generator,
            generator_name=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            generated_at=window.start,
            parameters={"outlineId": outline.outline_id, "seed": seed},
        ),
    )
    declared = DeclaredHabits(
        outline_id=outline.outline_id,
        time_zone=outline.time_zone,
        start_date=outline.start_date,
        end_date=outline.end_date,
        seed=seed,
        residents=[
            DeclaredResidentHabits(resident_id=item.resident_id, habits=item.habits)
            for item in outline.residents
        ],
        joint_activities=[
            DeclaredJointActivity(
                recurring_activity_id=item.activity.recurring_activity_id,
                intent=item.activity.intent
                or label_to_intent(item.activity.label, item.activity.kind.value),
                participant_ids=list(item.participant_ids),
                sharing=item.sharing,
                propensity=item.propensity,
            )
            for item in outline.household.joint_activities
        ],
    )
    planned = measure_habits(
        declared,
        evidence_from_plan(
            days, outline.resident_ids, started_at=window.start, ended_at=window.end
        ),
    )
    # Only the declaration travels inside the scenario. Nothing downstream of ingestion ever sees
    # the outline, so without this a run could not say how its days divide; and nothing measured
    # travels with it, because the only thing worth publishing as measured is what a run did, which
    # the export measures from that run's trace.
    scenario = scenario.model_copy(
        update={
            "extensions": {
                **scenario.extensions,
                DECLARED_HABITS_EXTENSION: json.loads(declared.model_dump_json(by_alias=True)),
            }
        }
    )
    # The package names the scenario it was written for, and on this path that scenario does not
    # exist until now: its version is whatever this expander stamps, so a package cannot know it and
    # can only be told it. Models that were told still wrote `2.0.0`, the outline's schema version,
    # and a whole horizon was refused for a number with no other possible value. The identifier is
    # left alone — a package written for another outline is a real mistake, and is still reported.
    if (
        package.source_scenario_id == scenario.scenario_id
        and package.source_scenario_version != scenario.schema_version
    ):
        package = package.model_copy(update={"source_scenario_version": scenario.schema_version})
    return ExpansionResult(
        bundle=SimulationAuthoringBundle(scenario=scenario, personal_process_package=package),
        declared_habits=declared,
        planned_bands=planned,
        day_count=len(days),
        activity_count=sum(len(day.activities) for day in days),
        skipped_occurrences=sum(item.skipped for item in horizons),
        rescheduled_occurrences=sum(item.rescheduled for item in horizons),
        dropped_occurrences=sum(item.dropped for item in horizons),
    )


__all__ = [
    "ExpansionError",
    "ExpansionResult",
    "expand_outline",
]
