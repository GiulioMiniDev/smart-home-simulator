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
   bounds the fast wobble around it. An anchor stays punctual, an optional habit wanders.
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
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from smart_home_sim.domain.authoring import SimulationAuthoringBundle
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import (
    Activity,
    AuthorType,
    DateTimeWindow,
    DayPlan,
    DurationRange,
    Provenance,
    Resident,
    ResidentInitialState,
    SimulationWindow,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.cadence import (
    ActivityOccurrence,
    CadenceCalendar,
    CalendarDay,
    build_cadence_calendar,
)
from smart_home_sim.hybrid_planning.day_generation import (
    DEFAULT_INTENT,
    RHYTHM_EMITTED_INTENTS,
    at_offset,
    build_day_plan,
    label_to_intent,
    window_around,
)
from smart_home_sim.hybrid_planning.drives import DayRhythm, RhythmProfile, plan_rhythms
from smart_home_sim.hybrid_planning.horizon import _scheduled_drive_load
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG, intent_spec
from smart_home_sim.hybrid_planning.outline import (
    Displacement,
    FixedCommitment,
    HabitComposition,
    HabitDayTypeObservation,
    HabitGroundTruth,
    HabitObservation,
    HorizonOutline,
    OutlineEvent,
    OutlineWorld,
)
from smart_home_sim.hybrid_planning.package_authoring import ACTIVITY_CATALOG_VERSION
from smart_home_sim.hybrid_planning.recurring_activities import (
    ActivityCadence,
    BehavioralProfile,
    CadencePeriod,
    RecurringActivity,
    RecurringActivityKind,
)
from smart_home_sim.hybrid_planning.world import PlanningWorld, assemble_scenario

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
    habit_ground_truth: HabitGroundTruth
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


def _phase_profile(outline: HorizonOutline, phase_index: int) -> BehavioralProfile:
    """The profile as it stands during one phase, with that phase's overrides applied."""
    phase = outline.phases[phase_index]
    replacements = {
        item.recurring_activity_id: item.cadence
        for item in phase.activity_overrides
        if item.cadence is not None
    }
    recurring_activities = [
        activity.model_copy(update={"cadence": replacements[activity.recurring_activity_id]})
        if activity.recurring_activity_id in replacements
        else activity
        for activity in outline.profile.recurring_activities
    ]
    return outline.profile.model_copy(update={"recurring_activities": recurring_activities})


def _effective_calendar(outline: HorizonOutline, seed: int) -> CadenceCalendar:
    """One calendar for the horizon, taking each phase's overridden activities from its own
    variant.

    `_due_times` is computed per habit, so rebuilding the whole calendar with one habit's cadence
    swapped leaves every other habit's schedule identical. That is what makes splicing sound:
    the baseline and the variant agree everywhere the override does not apply.
    """
    baseline = build_cadence_calendar(
        outline.profile,
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
    for index, phase in enumerate(outline.phases):
        overridden = {item.recurring_activity_id for item in phase.activity_overrides}
        if not overridden:
            continue
        stopped = {
            item.recurring_activity_id for item in phase.activity_overrides if item.suspended
        }
        variant = build_cadence_calendar(
            _phase_profile(outline, index),
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


def _event_dates(outline: HorizonOutline, event: OutlineEvent, seed: int) -> list[date]:
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


def _place_events(outline: HorizonOutline, seed: int) -> dict[str, list[_PlacedEvent]]:
    placed: dict[str, list[_PlacedEvent]] = {}
    for event in outline.events:
        for day in _event_dates(outline, event, seed):
            placed.setdefault(day.isoformat(), []).append(_PlacedEvent(event=event, day=day))
    return placed


def _daily_capacity(outline: HorizonOutline) -> dict[str, int]:
    """How many occurrences of each habit one day may legitimately hold.

    One, for everything that recurs weekly or monthly. For a daily habit it is whatever the cadence
    asks for, taken at its widest across the baseline and any phase that replaces it, because a
    displaced occurrence may be rescheduled into a phase with a different rhythm and the answer
    must not depend on which side of the boundary it lands.
    """
    capacity: dict[str, int] = {}
    cadences: dict[str, list[ActivityCadence]] = defaultdict(list)
    for activity in outline.profile.recurring_activities:
        cadences[activity.recurring_activity_id].append(activity.cadence)
    for phase in outline.phases:
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
    outline: HorizonOutline, baseline: dict[str, RecurringActivity], day: date
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
    for phase in outline.phases:
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
    earliest, latest = _band(activity.start_window.preferred.date(), window_start, window_end, tz)
    jitter = max(recurring.cadence.jitter_minutes, 0)
    if jitter > 0:
        offset = _rng(seed, "jitter", activity.activity_id).randint(-jitter, jitter)
        # Clamped to the declared band: the wobble says how irregular the habit is, it does not
        # give it permission to leave the hours its author allowed. Unclamped, a 45-minute jitter
        # pushed an evening habit whose band closed at 22:30 past bedtime.
        preferred = max(earliest, min(preferred + timedelta(minutes=offset), latest))
    # The drives may have carried the occurrence outside its declared band; the band then follows
    # the occurrence rather than contradicting it. The guard is built in real elapsed time so the
    # band cannot end up straddling a DST transition on the wrong side of its own preferred moment.
    guard = window_around(preferred, timedelta(minutes=MINIMUM_FLEX_MINUTES))
    earliest = min(earliest, guard.earliest)
    latest = max(latest, guard.latest)
    return activity.model_copy(
        update={
            "start_window": DateTimeWindow(earliest=earliest, preferred=preferred, latest=latest),
            "mandatory": recurring.kind not in _SACRIFICIAL_KINDS,
        }
    )


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


def _resolve_overlaps(activities: list[Activity]) -> list[Activity]:
    """Push preferred starts forward so a day's plan does not ask to be in two places at once.

    Widening windows gave the compiler room, but it also let neighbouring bands overlap: dinner
    may prefer 20:40 while television prefers 20:55 and dinner runs an hour. Left alone the
    compiler has to reject and re-place 18% of all preferred values, and each rejection costs it a
    search. A person does not plan two things over each other in the first place, so the day is
    made coherent here and the compiler is left to confirm it — which is the cheap case — while
    the wide windows stay available for the collisions that are genuine, like an all-day event.

    Only the preferred moment moves; the declared window is never narrowed, so nothing the author
    allowed becomes unreachable.
    """
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
        fixed = any(label.startswith("commitment:") for label in activity.labels)
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


def _commitment_spans(outline: HorizonOutline, day: date) -> list[tuple[int, int]]:
    """The day's fixed commitments as (start, end) minutes after midnight."""
    return [
        (_to_minutes(commitment.start_time), _to_minutes(commitment.end_time))
        for commitment in outline.fixed_commitments
        if _commitment_active_on(commitment, day)
    ]


def _first_commitment_by_day(
    outline: HorizonOutline, days: Sequence[CalendarDay]
) -> dict[date, int]:
    """When the earliest fixed commitment starts on each day, in minutes after midnight.

    The drive model shapes the night from the resident's chronotype alone, which is right for a day
    she owns and wrong for a day someone else has already claimed part of. Handing it the start of
    the first commitment is what turns a free-running wake into an alarm.
    """
    starts: dict[date, int] = {}
    for calendar_day in days:
        day = date.fromisoformat(calendar_day.date)
        minutes = [
            _to_minutes(commitment.start_time)
            for commitment in outline.fixed_commitments
            if _commitment_active_on(commitment, day)
        ]
        if minutes:
            starts[day] = min(minutes)
    return starts


def _commitment_activities(
    outline: HorizonOutline, day: date, tz: ZoneInfo, index: int
) -> list[Activity]:
    """Materialise the fixed commitments that fall on this day.

    A commitment is the one thing in the outline with real clock times, because its hours are set
    by someone other than the resident. It is therefore emitted with a tight window: there is
    nothing for the placement engine to decide, and widening it would invite the compiler to move
    a shift that cannot move. Everything else on the day gives way to it instead.
    """
    activities: list[Activity] = []
    for offset, commitment in enumerate(outline.fixed_commitments):
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
                actor_id=outline.resident_id,
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
    return activities


# A band's dominant activity has to hold a minute on at least this share of the applicable days
# before that minute counts as part of the band's effective window. Half is the weakest claim
# worth publishing — "on most days, this is what is happening here" — and it keeps a rare late
# night from stretching the window.
EFFECTIVE_DAY_SHARE = 0.5


def _band_minutes_in_order(spans: list[tuple[int, int]]) -> list[int]:
    """The band's minutes in traversal order, so a band that wraps reads 21:30 -> 06:29."""
    return [minute for start, end in spans for minute in range(start, end)]


def _longest_run(minutes: list[int], occupied: set[int]) -> list[int]:
    best: list[int] = []
    current: list[int] = []
    for minute in minutes:
        if minute in occupied:
            current.append(minute)
            if len(current) > len(best):
                best = current
        else:
            current = []
    return best


def _compose(by_intent: dict[str, float], total: float) -> list[HabitComposition]:
    return [
        HabitComposition(
            intent=intent,
            minutes=round(minutes, 1),
            share=round(minutes / total, 4) if total else 0.0,
        )
        for intent, minutes in sorted(by_intent.items(), key=lambda item: -item[1])
    ]


def _clock(minute: int) -> str:
    return f"{minute // 60 % 24:02d}:{minute % 60:02d}"


def _measure_habits(outline: HorizonOutline, days: list[DayPlan], seed: int) -> HabitGroundTruth:
    """Measure what each declared habit band actually contains across the generated horizon.

    For every applicable day and every band, each planned activity contributes the minutes its
    interval overlaps the band. An activity that starts before the band or runs past its end
    counts only for the part inside — the night band and a sleep block that crosses midnight are
    the case that forces this. The remainder of the band, during which the plan has the resident
    doing nothing the outline named, is reported as `unaccounted` rather than silently dropped:
    the same "other" column the habit-segmentation paper prints beside its own results.

    Three measurements beyond that, all of them things an evaluation would otherwise have to
    reconstruct from the activity log:

    - a band scoped to particular weekdays is measured over those days only, so its shares are not
      diluted by the days it does not claim;
    - a band that is *not* scoped is additionally measured over weekdays and weekend separately,
      because that is where an undeclared split hides;
    - the band's dominant activity is tracked minute by minute, so the window the author declared
      can be compared against the stretch the behaviour actually occupies.
    """
    observations: list[HabitObservation] = []
    for segment in outline.habits:
        spans = segment.minute_spans()
        band_minutes = sum(end - start for start, end in spans)
        applicable = [day for day in days if segment.applies_on(day.date)]

        by_intent: dict[str, float] = {}
        by_class: dict[str, dict[str, float]] = {"weekday": {}, "weekend": {}}
        class_days = {"weekday": 0, "weekend": 0}
        occupancy: dict[str, Counter[int]] = defaultdict(Counter)

        for day in applicable:
            day_class = "weekend" if day.date.weekday() >= 5 else "weekday"
            class_days[day_class] += 1
            for activity in day.activities:
                if activity.start_window is None or activity.duration is None:
                    continue
                begin = activity.start_window.preferred
                minutes = float(activity.duration.preferred_minutes)
                # Minutes since the start of the activity's own day, so an interval running past
                # midnight is measured against the following day's copy of the band as well.
                offset = begin.hour * 60 + begin.minute
                for shift in (0, -24 * 60):
                    lo = offset + shift
                    hi = lo + minutes
                    for start, end in spans:
                        first = max(lo, start)
                        last = min(hi, end)
                        overlap = last - first
                        if overlap <= 0:
                            continue
                        by_intent[activity.intent] = by_intent.get(activity.intent, 0.0) + overlap
                        bucket = by_class[day_class]
                        bucket[activity.intent] = bucket.get(activity.intent, 0.0) + overlap
                        occupancy[activity.intent].update(range(int(first), int(last)))

        total = float(band_minutes * len(applicable))
        covered = sum(by_intent.values())
        unaccounted = max(0.0, total - covered)

        dominant = max(by_intent, key=lambda intent: by_intent[intent]) if by_intent else None
        effective: list[int] = []
        if dominant is not None and applicable:
            floor = EFFECTIVE_DAY_SHARE * len(applicable)
            held = {minute for minute, count in occupancy[dominant].items() if count >= floor}
            effective = _longest_run(_band_minutes_in_order(spans), held)

        day_types = [
            HabitDayTypeObservation(
                day_type=day_class,  # type: ignore[arg-type]
                day_count=class_days[day_class],
                total_minutes=round(float(band_minutes * class_days[day_class]), 1),
                composition=_compose(
                    by_class[day_class], float(band_minutes * class_days[day_class])
                ),
                unaccounted_minutes=round(
                    max(
                        0.0,
                        float(band_minutes * class_days[day_class])
                        - sum(by_class[day_class].values()),
                    ),
                    1,
                ),
                unaccounted_share=round(
                    max(
                        0.0,
                        1
                        - sum(by_class[day_class].values())
                        / (band_minutes * class_days[day_class]),
                    ),
                    4,
                )
                if class_days[day_class]
                else 0.0,
            )
            for day_class in ("weekday", "weekend")
            if class_days[day_class]
        ]
        # Restating `composition` under another name helps nobody: the split is published only
        # when the band actually spans both kinds of day.
        if len(day_types) < 2:
            day_types = []

        observations.append(
            HabitObservation(
                habit_id=segment.habit_id,
                label=segment.label,
                window_start=segment.window_start,
                window_end=segment.window_end,
                crosses_midnight=segment.crosses_midnight,
                weekdays=list(segment.weekdays),
                day_count=len(applicable),
                total_minutes=round(total, 1),
                composition=_compose(by_intent, total),
                unaccounted_minutes=round(unaccounted, 1),
                unaccounted_share=round(unaccounted / total, 4) if total else 0.0,
                dominant_intent=dominant,
                effective_start=_clock(effective[0]) if effective else None,
                effective_end=_clock(effective[-1] + 1) if effective else None,
                effective_minutes=float(len(effective)),
                effective_share=round(len(effective) / band_minutes, 4) if band_minutes else 0.0,
                day_types=day_types,
            )
        )
    return HabitGroundTruth(
        outline_id=outline.outline_id,
        resident_id=outline.resident_id,
        time_zone=outline.time_zone,
        start_date=outline.start_date,
        end_date=outline.end_date,
        seed=seed,
        habits=observations,
        provenance=Provenance(
            author_type=AuthorType.rule_generator,
            generator_name=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            parameters={"outlineId": outline.outline_id, "seed": seed},
        ),
    )


def _planning_world(outline: HorizonOutline) -> PlanningWorld:
    world: OutlineWorld = outline.world
    return PlanningWorld(
        world_id=f"{outline.outline_id}-world",
        persona_id=outline.profile.persona_id,
        scenario_id=outline.outline_id,
        title=outline.title,
        time_zone=outline.time_zone,
        seed=0,
        home_model=world.home_model,
        activity_catalog=VersionedReference(
            reference_id="activity_catalog", version=ACTIVITY_CATALOG_VERSION
        ),
        residents=[Resident(resident_id=outline.resident_id)],
        external_people=world.external_people,
        locations=world.locations,
        resources=world.resources,
        resident_placements=[
            ResidentInitialState(
                resident_id=outline.resident_id,
                location_id=world.start_location_id,
                facts=world.resident_facts,
            )
        ],
        resource_facts=world.resource_facts,
        environment_facts=world.environment_facts,
        provenance=outline.provenance,
    )


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
    for activity in outline.profile.recurring_activities:
        if activity.intent is None:
            inferred = label_to_intent(activity.label, activity.kind.value)
            if inferred == DEFAULT_INTENT:
                unresolved.append(
                    f"activity {activity.recurring_activity_id!r} ({activity.label!r})"
                )
            continue
        if _intent_location(activity.intent) is None:
            unknown.append(f"activity {activity.recurring_activity_id!r} -> {activity.intent!r}")
    for event in outline.events:
        if event.intent is not None and _intent_location(event.intent) is None:
            unknown.append(f"event {event.event_id!r} -> {event.intent!r}")
    for commitment in outline.fixed_commitments:
        if commitment.intent is None:
            unresolved.append(f"commitment {commitment.commitment_id!r}")
        elif _intent_location(commitment.intent) is None:
            unknown.append(f"commitment {commitment.commitment_id!r} -> {commitment.intent!r}")
    # Both lists are reported together: the fix is one regeneration, so it should be told
    # everything it has to change rather than one item per attempt.
    problems: list[str] = []
    if unknown:
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
        for activity in outline.profile.recurring_activities
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
    """Refuse a package that does not implement every intent the horizon will contain.

    The days carry more intents than the outline declares: the rhythm always adds a wake and a
    night, and adds a debt nap, a nocturnal bathroom trip or an unplanned reach-out when the drive
    state calls for one. A package written only against the declared activities therefore leaves
    those days referencing behaviour nobody authored — which ingestion reports as one
    `MISSING_PROCESS_BINDING` per activity. On the first real eight-month case that was 628
    errors for five missing models, so the check belongs here, before the days exist.
    """
    implemented = {binding.intent for binding in package.bindings}
    declared = {
        activity.intent
        for activity in outline.profile.recurring_activities
        if activity.intent is not None
    }
    declared |= {event.intent for event in outline.events if event.intent is not None}
    declared |= {
        commitment.intent
        for commitment in outline.fixed_commitments
        if commitment.intent is not None
    }
    missing_declared = sorted(declared - implemented)
    missing_rhythm = sorted(RHYTHM_EMITTED_INTENTS - implemented)
    problems: list[str] = []
    if missing_declared:
        problems.append(
            "the outline declares intents the process package does not implement: "
            + ", ".join(missing_declared)
        )
    if missing_rhythm:
        problems.append(
            "the rhythm emits these intents on its own and the process package must implement "
            "them too: " + ", ".join(missing_rhythm)
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


def expand_outline(
    outline: HorizonOutline,
    package: PersonalProcessPackage,
    *,
    seed: int = 0,
) -> ExpansionResult:
    """Turn one outline into one authoring bundle covering the whole horizon.

    The result is an ordinary `SimulationAuthoringBundle` and enters the unchanged ingestion flow,
    which is what keeps every frozen contract downstream untouched.
    """
    _check_intents(outline)
    _check_locations(outline)
    _check_package_covers(outline, package)
    calendar = _effective_calendar(outline, seed)
    placed = _place_events(outline, seed)
    calendar, skipped, moved, dropped = _apply_displacement(
        calendar, placed, _daily_capacity(outline)
    )

    rhythm_profile = replace(
        RhythmProfile.from_persona(
            outline.profile.persona_id, outline.rhythm.age, outline.rhythm.health
        ),
        chronotype_bedtime_minutes=_to_minutes(outline.rhythm.chronotype_bedtime),
    )
    meals, social = _scheduled_drive_load(calendar.days)
    rhythms: dict[str, DayRhythm] = plan_rhythms(
        rhythm_profile,
        [date.fromisoformat(day.date) for day in calendar.days],
        seed=seed,
        meals_by_day=meals,
        social_by_day=social,
        first_commitment_by_day=_first_commitment_by_day(outline, calendar.days),
    )

    tz = ZoneInfo(outline.time_zone)
    recurring_activities = _activities_by_id(outline.profile)
    days: list[DayPlan] = []
    for calendar_day in calendar.days:
        day_events = placed.get(calendar_day.date, [])
        plan = build_day_plan(
            calendar_day,
            timezone=outline.time_zone,
            actor_id=outline.resident_id,
            rhythm=rhythms.get(calendar_day.date),
            seed=seed,
            busy_minutes=[
                *_commitment_spans(outline, date.fromisoformat(calendar_day.date)),
                *_event_spans(day_events, seed),
            ],
        )
        effective = _effective_activities(
            outline, recurring_activities, date.fromisoformat(calendar_day.date)
        )
        bands = _sub_bands(plan.activities, effective)
        activities = [
            _wobble(
                activity,
                effective.get(_recurring_activity_id_of(activity) or ""),
                tz,
                seed,
                bands.get(activity.activity_id),
            )
            for activity in plan.activities
        ]
        for index, item in enumerate(day_events):
            activities.append(
                _event_activity(item, len(activities) + index, tz, outline.resident_id, seed)
            )
        activities.extend(
            _commitment_activities(
                outline, date.fromisoformat(calendar_day.date), tz, len(activities)
            )
        )
        activities = _resolve_overlaps(activities)
        if calendar_day is calendar.days[-1]:
            # The horizon stops at midnight after the last day, so whatever is still running then
            # is truncated rather than made infeasible. This is what the flag is for; the evening
            # activities of every other day have the next morning to spill into.
            activities = [
                item.model_copy(update={"allow_boundary_truncation": True}) for item in activities
            ]
        days.append(plan.model_copy(update={"activities": activities}))

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
    ground_truth = _measure_habits(outline, days, seed)
    # The bands travel inside the scenario as well as beside it. Nothing downstream of ingestion
    # ever sees the outline, so without this the application holds a horizon it cannot say how to
    # divide — and a dataset exported from the app would carry the sensor log and the oracle but
    # not the target a segmentation algorithm is scored against.
    scenario = scenario.model_copy(
        update={
            "extensions": {
                **scenario.extensions,
                "habitGroundTruth": json.loads(ground_truth.model_dump_json(by_alias=True)),
            }
        }
    )
    return ExpansionResult(
        bundle=SimulationAuthoringBundle(scenario=scenario, personal_process_package=package),
        habit_ground_truth=ground_truth,
        day_count=len(days),
        activity_count=sum(len(day.activities) for day in days),
        skipped_occurrences=skipped,
        rescheduled_occurrences=moved,
        dropped_occurrences=dropped,
    )


__all__ = [
    "ExpansionError",
    "ExpansionResult",
    "expand_outline",
]
