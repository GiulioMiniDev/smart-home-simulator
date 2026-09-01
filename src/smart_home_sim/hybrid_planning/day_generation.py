"""Stage C (deterministic substrate): turn a cadence calendar into simulatable scenario days.

Every activity in a day must use one of the shared canonical intents (the only ones the process
package can execute), so each due activity is mapped to an intent and each day gets a minimal
scaffold
(wake at the start, sleep at the end). The result is a scenario chunk (world + days) that compiles
and simulates. The LLM day layer will later enrich and vary these days; this substrate guarantees a
valid, simulatable day always exists and is the fallback.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from smart_home_sim.domain.models import (
    Activity,
    Condition,
    ConditionOperator,
    DateTimeWindow,
    DayContext,
    DayPlan,
    DurationRange,
    Scenario,
    SimulationWindow,
)
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar, CalendarDay
from smart_home_sim.hybrid_planning.drives import DayRhythm
from smart_home_sim.hybrid_planning.intents import IntentCategory, intent_spec
from smart_home_sim.hybrid_planning.world import PlanningWorld, assemble_scenario

WAKE_TIME = "06:00"
SLEEP_TIME = "22:30"
_WINDOW_FLEX = timedelta(minutes=15)
DEFAULT_INTENT = "read_and_rest"

# Substring keywords mapping a free-text activity label to a canonical intent. The *longest*
# matching keyword wins, not the first one listed: with first-match-wins the generic "wash"
# swallowed "wash up the dishes", and "hygiene" made `evening_hygiene` unreachable, so activities
# were silently recorded in the ground truth as the wrong one.
_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("take_morning_medication", ("medication", "medicine", "pill", "tablet", "insulin")),
    ("morning_toilet_and_shower", ("shower",)),
    ("morning_toilet_and_wash", ("wash", "toilet", "hygiene", "brush")),
    ("use_toilet", ("toilet break", "bathroom break", "bathroom visit")),
    ("prepare_and_drink_hot_drink", ("coffee break", "tea break", "hot drink", "make coffee")),
    ("evening_hygiene", ("evening hygiene", "bedtime wash", "evening wash", "night hygiene")),
    ("eat_breakfast", ("breakfast", "coffee", "morning tea")),
    ("eat_lunch", ("lunch",)),
    ("eat_dinner", ("dinner", "supper", "evening meal")),
    ("weekly_meal_preparation", ("batch cook", "meal prep", "weekly cook")),
    ("prepare_simple_lunch", ("cook", "prepare food", "prepare meal")),
    ("buy_groceries", ("groceries", "grocery", "shopping", "market", "supermarket", "errand")),
    ("put_groceries_away", ("put away", "store groceries")),
    ("clean_kitchen", ("clean", "dishes", "wash up")),
    ("tidy_living_room_and_hallway", ("tidy", "declutter", "housework")),
    ("start_laundry", ("laundry", "washing machine")),
    ("hang_laundry", ("hang laundry", "hang the laundry", "hang out the washing", "dry clothes")),
    ("indoor_light_exercise", ("exercise", "stretch", "workout", "yoga", "gym")),
    # Bare "work" is safe here only because the longest keyword wins: "workout" (7) and
    # "housework" (9) both beat it and keep their own intents. Before this row a persona whose
    # profile said "morning work block" was silently recorded as `read_and_rest`.
    ("work_from_home", ("work", "desk", "freelance", "office", "email", "client")),
    ("evening_walk", ("walk", "stroll", "outdoors", "outside", "garden")),
    ("watch_television", ("tv", "television", "watch", "documentary", "news")),
    ("phone_call", ("call", "phone", "video call", "visit", "chat")),
    ("rest_or_nap", ("nap", "rest", "lie down")),
    ("read_and_rest", ("read", "book", "relax")),
    ("sleep", ("sleep", "bed")),
)

_CATEGORY_DURATION_MINUTES: dict[IntentCategory, tuple[int, int, int]] = {
    IntentCategory.sleep_wake: (10, 15, 20),
    IntentCategory.hygiene: (10, 20, 30),
    IntentCategory.medication: (5, 10, 15),
    IntentCategory.meal: (20, 30, 45),
    IntentCategory.cooking: (20, 30, 45),
    IntentCategory.chores: (15, 25, 40),
    IntentCategory.laundry: (10, 20, 30),
    IntentCategory.exercise: (20, 30, 45),
    IntentCategory.outdoor: (30, 45, 70),
    IntentCategory.errand: (40, 60, 90),
    IntentCategory.leisure: (30, 45, 70),
    IntentCategory.social: (15, 25, 40),
    IntentCategory.home_work: (45, 95, 165),
}
# The overnight sleep is the terminal activity of a one-day scenario; it truncates safely at the
# day boundary (allowBoundaryTruncation), so a natural length is fine.
_SLEEP_DURATION = (360, 420, 480)

# Stochastic-behaviour path only (see `_sample_duration`). The solver minimises deviation from
# preferredMinutes, so with a fixed preferred every occurrence lands on exactly that value and the
# range above acts as a *ceiling* variability can only shave: observed durations pile up against
# the maximum with near-zero variance. Real ADL durations are right-skewed instead, so here the
# preferred value is drawn per occurrence from a log-normal and the bounds are widened to leave the
# tail room. (minimumMinutes, medianMinutes, maximumMinutes, logSigma)
_CATEGORY_DURATION_SHAPE: dict[IntentCategory, tuple[int, int, int, float]] = {
    IntentCategory.sleep_wake: (5, 15, 40, 0.35),
    IntentCategory.hygiene: (6, 18, 45, 0.35),
    IntentCategory.medication: (3, 8, 20, 0.30),
    IntentCategory.meal: (12, 28, 75, 0.32),
    IntentCategory.cooking: (12, 30, 80, 0.35),
    IntentCategory.chores: (8, 24, 70, 0.38),
    IntentCategory.laundry: (8, 18, 45, 0.30),
    IntentCategory.exercise: (12, 28, 60, 0.30),
    IntentCategory.outdoor: (20, 45, 120, 0.35),
    IntentCategory.errand: (25, 55, 140, 0.33),
    IntentCategory.leisure: (15, 45, 150, 0.45),
    IntentCategory.social: (8, 22, 75, 0.45),
    # A block of home work, not a working day: the day is several of these, and how many is the
    # cadence's business. The median is a long Pomodoro run and the ceiling is the morning someone
    # does not get up from — four hours is where an uninterrupted stretch stops being plausible and
    # `validate_home_work_is_fragmented` starts saying so.
    IntentCategory.home_work: (25, 90, 240, 0.40),
}

# Intents whose duration has nothing to do with their category's. A category is a coarse grouping
# — `hygiene` holds a twenty-minute shower and a two-minute visit to the toilet — and where the gap
# is that wide the category default is not an approximation but a wrong number: an afternoon break
# drawn from `cooking` would have the resident making coffee for half an hour. The drive layer
# already worked around this for its own activities by passing a shape per timeline entry
# (`_NIGHT_VISIT_SHAPE` below is exactly that); this is the same override for the intents a
# *declared* habit can name. Category, then override: the table wins where it has an entry.
# (minimumMinutes, medianMinutes, maximumMinutes, logSigma)
_INTENT_DURATION_SHAPE: dict[str, tuple[int, int, int, float]] = {
    "use_toilet": (2, 6, 15, 0.35),
    "prepare_and_drink_hot_drink": (5, 13, 35, 0.35),
}

# A nocturnal bathroom trip: short, and its own intent since activity catalog 1.4.0. It borrowed
# `morning_toilet_and_wash` for as long as that was the only executable toilet intent, which put a
# morning routine in the ground truth at two in the morning — 73 of its 75 occurrences on a
# generated year fell between midnight and six. Worse than the label, the borrowed process was a
# daytime one and ended wherever its last action left the resident, so she stood at the washbasin
# until the next thing in the plan came for her and `wake_up` walked her back to a bedroom she had
# never left. `night_toilet_visit` ends by going back to bed.
_NIGHT_VISIT_INTENT = "night_toilet_visit"
# The daytime counterpart, and the first activity the *engine* decides rather than the planner.
#
# A person voids six to eight times in a waking day; Miriam managed 1.4, because a toilet visit
# only ever reached the day if an author had declared one, and the outline that declares a bladder
# has not been written. The planner therefore seeds candidates through the waking hours and each
# carries one precondition — `bladder_is_full` — which is false until the engine's own drive says
# otherwise. The surplus is dropped at execution with `optional_dropped`, which is a mechanism that
# already existed and had nothing to use it.
#
# This is also the shape of the gap the real log has and the generated one does not. CASAS Aruba
# leaves 29 unannotated gaps a day with a median of four minutes; a generated year leaves 11.8 with
# a median of sixteen. The long gaps already match — 1.94 a day on both sides. What is missing is
# the short ones, and a bathroom trip is the shortest honest thing a person does.
_TOILET_INTENT = "use_toilet"
_TOILET_LABEL = "bladder_drive"
# How many chances a day the engine is given. Above the six to eight a person makes, because the
# drive turns most of them down: seeding at the target would land under it.
_TOILET_CANDIDATES_PER_DAY = 8
# Clear of the wake and of lights-out; the night has its own trip and its own model.
_TOILET_WAKE_MARGIN_MINUTES = 25
_TOILET_NIGHT_MARGIN_MINUTES = 45
# Everything already on the day's list that empties the bladder, and how far a seeded candidate
# keeps away from one. An outline may declare its own bathroom breaks — Miriam's declares one for
# every working day — and those are mandatory, so the drive cannot turn them down: seeding beside
# one produced two visits within a quarter of an hour, which reads as a symptom rather than a day.
_TOILET_RELIEVING_INTENTS = frozenset(
    {_TOILET_INTENT, "morning_toilet_and_shower", "morning_toilet_and_wash", _NIGHT_VISIT_INTENT}
)
_TOILET_SPACING_MINUTES = 75
_NIGHT_VISIT_LABEL = "night_visit"
_NIGHT_VISIT_SHAPE = (3, 6, 12, 0.35)
_NAP_INTENT = "rest_or_nap"
# An unscheduled reach-out when the need for company ran high. Its own label keeps it out of the
# activity ground truth: it happened, but nobody planned it.
_UNPLANNED_SOCIAL_INTENT = "phone_call"

# Everything the drive layer can put in a day without any outline declaring it: the wake and the
# night it always emits, plus the three it produces from state — a debt nap, a nocturnal bathroom
# trip, an unplanned reach-out when the need for company runs high. A process package has to
# implement all of them or the days will reference behaviour nobody wrote, which is why the
# authoring prompt renders this set rather than restating it.
RHYTHM_EMITTED_INTENTS: frozenset[str] = frozenset(
    {
        "wake_up",
        "sleep",
        _NAP_INTENT,
        _NIGHT_VISIT_INTENT,
        _UNPLANNED_SOCIAL_INTENT,
        _TOILET_INTENT,
    }
)
_UNPLANNED_SOCIAL_LABEL = "social_need_contact"
_UNPLANNED_SOCIAL_SHAPE = (8, 18, 35, 0.30)
# From when a habit counts as part of the evening, and so follows lights-out rather than the wake.
_EVENING_FROM_MINUTES = 16 * 60
# What share of tonight's deviation from the usual bedtime the evening takes with it.
_EVENING_FOLLOWS_THE_NIGHT = 0.6
# The last minutes before lights-out, left clear so a habit and the night do not start together.
EVENING_CLEARANCE_MINUTES = 20
# The first minutes after waking, left clear for the same reason at the other end of the day. The
# expander needs the number too: `_shift` applies it here, and `_wobble` has to apply it again
# after it has rebuilt the window from the author's declared band.
WAKE_CLEARANCE_MINUTES = 5

# Evening band a spontaneous call may occupy, in minutes after midnight (17:00-21:30).
_UNPLANNED_SOCIAL_WINDOW = (17 * 60, 21 * 60 + 30)
# A debt nap is its own thing, much shorter than the generic leisure band it would otherwise
# inherit. (minimumMinutes, medianMinutes, maximumMinutes, logSigma)
_NAP_SHAPE = (20, 40, 75, 0.30)
# Afternoon band a debt nap may occupy, in minutes after midnight (13:00-18:30).
_NAP_WINDOW = (13 * 60, 18 * 60 + 30)


def label_to_intent(label: str, kind: str | None = None) -> str:
    """Map a free-text activity label to a canonical intent (deterministic, longest keyword match).

    Ranking by keyword length makes the table order-independent: a specific phrase always beats a
    generic word contained in it, so adding a keyword can no longer shadow an existing intent.
    """
    lowered = label.lower()
    best_intent, best_length = DEFAULT_INTENT, 0
    for intent_id, keywords in _INTENT_KEYWORDS:
        for keyword in keywords:
            if keyword in lowered and len(keyword) > best_length:
                best_intent, best_length = intent_id, len(keyword)
    return best_intent


@dataclass(frozen=True)
class TimelineEntry:
    intent_id: str
    hhmm: str
    recurring_activity_id: str | None = None
    truncatable: bool = False
    # Nested inside another activity rather than competing with it for the resident. The compiler
    # keeps one actor in one place at a time, so without this a bathroom trip and the night that
    # contains it are two claims on the same hours and one of them has to go.
    nested: bool = False
    label: str | None = None
    # An exact (minimum, preferred, maximum) band, used where the value is already decided (the
    # night length comes from the sleep model).
    duration: tuple[int, int, int] | None = None
    # A (minimum, median, maximum, logSigma) shape to draw from, overriding the intent's category.
    duration_shape: tuple[int, int, int, float] | None = None
    # What has to be true at execution for this occurrence to happen at all. The compiler places it
    # either way; the engine reads these against live state and drops the ones the day did not turn
    # out to need.
    preconditions: tuple[Condition, ...] = ()
    # The room this occurrence happens in, when the outline said one. `None` means the catalog's.
    location: str | None = None


def plan_from_entries(
    day_date: date,
    day_type: str,
    entries: list[TimelineEntry],
    *,
    timezone: str,
    actor_id: str,
    seed: int | None = None,
) -> DayPlan:
    """Assemble a DayPlan from ordered intent entries (shared by deterministic and LLM sources).

    With ``seed`` set, each activity's preferred duration is drawn from its category's log-normal
    instead of being pinned to the category default.
    """
    tz = ZoneInfo(timezone)
    activities = [
        _activity(
            entry.intent_id,
            day_date,
            entry.hhmm,
            tz,
            actor_id,
            index=index,
            recurring_activity_id=entry.recurring_activity_id,
            truncatable=entry.truncatable,
            nested=entry.nested,
            label=entry.label,
            duration=entry.duration,
            duration_shape=entry.duration_shape,
            preconditions=entry.preconditions,
            seed=seed,
            location=entry.location,
        )
        for index, entry in enumerate(entries)
    ]
    return DayPlan(date=day_date, context=DayContext(day_type=day_type), activities=activities)


def build_day_plan(
    day: CalendarDay,
    *,
    timezone: str,
    actor_id: str,
    rhythm: DayRhythm | None = None,
    previous_rhythm: DayRhythm | None = None,
    seed: int | None = None,
    busy_minutes: Sequence[tuple[int, int]] = (),
    activity_locations: Mapping[str, str] = MappingProxyType({}),
) -> DayPlan:
    """Deterministic DayPlan: wake, the due recurring activities mapped to intents, then a terminal
    sleep.

    Without ``rhythm`` this is the frozen substrate: a fixed 06:00 wake and 22:30 lights-out on
    every single day of the horizon. With a rhythm, the day is shaped by the drive state it
    inherited — the night starts and ends where the sleep model put it, nocturnal bathroom trips
    are laid down before the wake, and a nap appears when sleep debt has built up.

    ``busy_minutes`` are the hours the day is already spoken for — its fixed commitments and its
    placed events — as (start, end) minutes after midnight. They are not part of this plan; the
    expander appends them afterwards. But the drive layer has to see them, or it fills an afternoon
    the resident spends at work.

    ``activity_locations`` maps a recurring activity to the room the outline said it happens in,
    where that is not the room the catalog gives its intent. Only the outline knows this: the
    catalog holds one room per intent, and a habit is free to differ from it.
    """
    entries: list[TimelineEntry] = []
    wake_time = WAKE_TIME
    sleep_time = SLEEP_TIME
    # The morning belongs to the night that is *ending*, which began yesterday evening. On the
    # first day of a horizon there is no yesterday, so the day borrows its own night's wake as the
    # initial condition — one morning out of a horizon, and the alternative is a day that starts
    # from nothing.
    morning = previous_rhythm if previous_rhythm is not None else rhythm
    if morning is not None:
        wake_time = morning.wake_hhmm
        # Lights-out after midnight happens on this day, so this is the list it belongs on, ahead
        # of the wake it leads to. `sleep_starts_next_day` is what routes it here.
        if morning.sleep_starts_next_day and morning is previous_rhythm:
            entries.append(
                TimelineEntry(
                    "sleep",
                    morning.sleep_hhmm,
                    truncatable=True,
                    duration=_sleep_duration(morning.sleep_minutes),
                )
            )
        # The trips belong to the same night, so they precede the wake and land in the small hours
        # the log was previously silent through.
        entries.extend(
            TimelineEntry(
                _NIGHT_VISIT_INTENT,
                visit,
                label=_NIGHT_VISIT_LABEL,
                duration_shape=_NIGHT_VISIT_SHAPE,
                nested=True,
            )
            for visit in morning.night_visits
            if visit < wake_time
        )
    if rhythm is not None:
        # The evening is this day's own. A night that runs past midnight leaves this timeline at
        # 23:59 as far as the daytime is concerned; it is emitted on tomorrow's list, above.
        sleep_time = "23:59" if rhythm.sleep_starts_next_day else rhythm.sleep_hhmm
    entries.append(TimelineEntry("wake_up", wake_time))
    for occurrence in day.occurrences:
        entries.append(
            TimelineEntry(
                occurrence.intent or label_to_intent(occurrence.label, occurrence.kind.value),
                _shift(occurrence.target_time, rhythm, morning, wake_time, sleep_time),
                recurring_activity_id=occurrence.recurring_activity_id,
                location=activity_locations.get(occurrence.recurring_activity_id),
            )
        )
    entries.sort(key=lambda item: item.hhmm)
    if rhythm is not None and rhythm.nap:
        slot = _free_slot(entries, _NAP_WINDOW, _NAP_SHAPE, busy_minutes)
        if slot is not None:
            entries.append(
                TimelineEntry(_NAP_INTENT, slot, label="sleep_debt_nap", duration_shape=_NAP_SHAPE)
            )
    if rhythm is not None and rhythm.unplanned_social_contact:
        slot = _free_slot(entries, _UNPLANNED_SOCIAL_WINDOW, _UNPLANNED_SOCIAL_SHAPE, busy_minutes)
        if slot is not None:
            entries.append(
                TimelineEntry(
                    _UNPLANNED_SOCIAL_INTENT,
                    slot,
                    label=_UNPLANNED_SOCIAL_LABEL,
                    duration_shape=_UNPLANNED_SOCIAL_SHAPE,
                )
            )
    entries.extend(
        _toilet_candidates(entries, wake_time, sleep_time, seed, date.fromisoformat(day.date))
    )
    if rhythm is None or not rhythm.sleep_starts_next_day:
        entries.append(
            TimelineEntry(
                "sleep",
                sleep_time,
                truncatable=True,
                duration=None if rhythm is None else _sleep_duration(rhythm.sleep_minutes),
            )
        )
    entries.sort(key=lambda item: item.hhmm)
    return plan_from_entries(
        date.fromisoformat(day.date),
        day.weekday.value,
        entries,
        timezone=timezone,
        actor_id=actor_id,
        seed=seed,
    )


def _toilet_candidates(
    entries: list[TimelineEntry],
    wake_time: str,
    sleep_time: str,
    seed: int | None,
    day_date: date,
) -> list[TimelineEntry]:
    """Chances for a bathroom trip, spread through the waking day.

    Placed rather than scheduled: the compiler will find room for the ones that fit and the engine
    will keep the ones the day turned out to need. Both halves are deliberate — a candidate the
    solver could not place and a candidate the drive turned down are the same thing, an occurrence
    that did not happen, and neither is an error.

    They are spread evenly with a jitter rather than dropped into the widest gaps, because a
    bladder does not wait for the diary to be free. Where one lands on top of something else the
    overlap pass moves it, and where it cannot be moved the compiler leaves it out.
    """
    opens = _to_minutes(wake_time) + _TOILET_WAKE_MARGIN_MINUTES
    closes = _to_minutes(sleep_time) - _TOILET_NIGHT_MARGIN_MINUTES
    if closes - opens < 60:
        return []
    step = (closes - opens) / _TOILET_CANDIDATES_PER_DAY
    precondition = (Condition(fact="bladder_is_full", operator=ConditionOperator.truthy),)
    declared = [
        _to_minutes(entry.hhmm) for entry in entries if entry.intent_id in _TOILET_RELIEVING_INTENTS
    ]
    candidates: list[TimelineEntry] = []
    for index in range(_TOILET_CANDIDATES_PER_DAY):
        centre = opens + step * (index + 0.5)
        if seed is not None:
            rng = _rng(seed, "bladder", day_date.isoformat(), index)
            centre += rng.uniform(-step / 3, step / 3)
        if any(abs(centre - moment) < _TOILET_SPACING_MINUTES for moment in declared):
            continue
        declared.append(centre)
        candidates.append(
            TimelineEntry(
                _TOILET_INTENT,
                _to_hhmm(int(round(max(opens, min(centre, closes))))),
                label=_TOILET_LABEL,
                truncatable=True,
                # Nested, for the same reason the nocturnal trip is: a bathroom break interrupts
                # the block it happens in rather than competing with it for the hour, and the
                # activity model has no way to say "interrupted" other than this. It is also what
                # makes the candidates cheap to place — eight optional intervals a day fighting
                # every other activity for the resident took the solver from fifty seconds to more
                # than twenty minutes on a single month.
                nested=True,
                preconditions=precondition,
            )
        )
    return candidates


def _free_slot(
    entries: list[TimelineEntry],
    window: tuple[int, int],
    shape: tuple[int, int, int, float],
    busy: Sequence[tuple[int, int]] = (),
) -> str | None:
    """Drop a drive-generated activity into the widest free gap of ``window``, or not at all.

    An activity pinned to a fixed clock time collides with whatever activity already sits there and
    makes the day unsolvable, so it has to be placed against the schedule that actually exists.

    ``busy`` is the part of the day the resident is not free to fill — the fixed commitments and
    the placed events, which the expander materialises after this plan and which therefore appear
    nowhere in ``entries``. Without them the afternoon looks empty on a working Monday and the debt
    nap lands in the middle of a nine-hour shift: two mandatory activities over the same hour, and
    no schedule exists.
    """
    occupied: list[tuple[int, int]] = list(busy)
    for entry in entries:
        start = _to_minutes(entry.hhmm)
        entry_shape = (
            entry.duration_shape or _CATEGORY_DURATION_SHAPE[intent_spec(entry.intent_id).category]
        )
        longest = entry.duration[2] if entry.duration is not None else entry_shape[2]
        occupied.append((start, start + longest))
    occupied.sort()

    needed = shape[2] + 2 * int(_WINDOW_FLEX.total_seconds() // 60)
    best: tuple[int, int] | None = None
    cursor = window[0]
    for start, end in [*occupied, (window[1], window[1])]:
        if start > cursor:
            gap = (cursor, min(start, window[1]))
            if gap[1] - gap[0] > (0 if best is None else best[1] - best[0]):
                best = gap
        cursor = max(cursor, end)
        if cursor >= window[1]:
            break
    if best is None or best[1] - best[0] < needed:
        return None
    return _to_hhmm((best[0] + best[1]) // 2 - shape[1] // 2)


def _sleep_duration(sleep_minutes: int) -> tuple[int, int, int]:
    """Centre the night on what the sleep model produced, keeping the solver a little slack."""
    low = max(1, int(round(sleep_minutes * 0.85)))
    high = max(low + 1, int(round(sleep_minutes * 1.15)))
    return low, max(low, min(sleep_minutes, high)), high


def _shift(
    hhmm: str,
    rhythm: DayRhythm | None,
    morning: DayRhythm | None,
    wake_time: str,
    sleep_time: str,
) -> str:
    """Slide an occurrence by the meal shift and by tonight's night, and keep it inside the day.

    Two anchors, one at each end, and they come from two different nights. The meal shift is the
    morning's — a hungry resident eats earlier, a late riser eats later — so it is read from the
    rhythm whose wake opened this day, which is yesterday's. The bedtime shift is the evening's and
    belongs to the night this day is heading into, which is today's. Taking both from one rhythm
    read the morning off a night that had not happened yet.

    The bedtime shift is the one the day used to be missing: every occurrence stayed where the band
    put it however early the night started, so a 22:01 lights-out was followed by the washing-up at
    22:32 and the hygiene after that. An evening that ends early started early.

    The share is a fraction rather than the whole shift because the evening compresses as well as
    moves: a resident going to bed two hours early does not also eat dinner two hours early, she
    spends less of the evening in front of the television.
    """
    if rhythm is None:
        return hhmm
    minutes = _to_minutes(hhmm)
    shifted = minutes + (0 if morning is None else morning.meal_shift_minutes)
    if minutes >= _EVENING_FROM_MINUTES:
        shifted += rhythm.bedtime_shift_minutes * _EVENING_FOLLOWS_THE_NIGHT
    floor = _to_minutes(wake_time) + WAKE_CLEARANCE_MINUTES
    # Lights-out is the end of the day, so nothing the resident does while awake may be placed after
    # it. `_wobble` applies the same bound again after it has moved the preferred moment.
    ceiling = max(floor, _to_minutes(sleep_time) - EVENING_CLEARANCE_MINUTES)
    return _to_hhmm(int(round(max(floor, min(shifted, ceiling)))))


def build_scenario_from_day_plan(world: PlanningWorld, day_plan: DayPlan) -> Scenario:
    """Wrap a single DayPlan in a one-day scenario."""
    tz = ZoneInfo(world.time_zone)
    start = datetime.combine(day_plan.date, time(0, 0), tzinfo=tz)
    end = datetime.combine(day_plan.date + timedelta(days=1), time(0, 0), tzinfo=tz)
    return assemble_scenario(world, days=[day_plan], window=SimulationWindow(start=start, end=end))


def build_day_scenario(
    world: PlanningWorld,
    day: CalendarDay,
    *,
    rhythm: DayRhythm | None = None,
    seed: int | None = None,
) -> Scenario:
    """Assemble a one-day scenario. Days are independent so the CP-SAT solver stays fast and the
    horizon scales; the dataset is the concatenation of per-day sensor logs (absolute timestamps).
    """
    actor_id = world.residents[0].resident_id
    return build_scenario_from_day_plan(
        world,
        build_day_plan(day, timezone=world.time_zone, actor_id=actor_id, rhythm=rhythm, seed=seed),
    )


def build_day_scenarios(
    world: PlanningWorld,
    calendar: CadenceCalendar,
    *,
    start_index: int = 0,
    days: int | None = None,
    rhythms: dict[str, DayRhythm] | None = None,
    seed: int | None = None,
) -> list[Scenario]:
    """Build one independent scenario per calendar day over the requested slice."""
    limit = len(calendar.days) if days is None else start_index + days
    chunk = calendar.days[start_index:limit]
    if not chunk:
        raise ValueError("requested calendar slice is empty")
    return [
        build_day_scenario(
            world,
            day,
            rhythm=None if rhythms is None else rhythms.get(day.date),
            seed=seed,
        )
        for day in chunk
    ]


def _activity(
    intent_id: str,
    day_date: date,
    hhmm: str,
    tz: ZoneInfo,
    actor_id: str,
    *,
    index: int,
    recurring_activity_id: str | None = None,
    truncatable: bool = False,
    nested: bool = False,
    label: str | None = None,
    duration: tuple[int, int, int] | None = None,
    duration_shape: tuple[int, int, int, float] | None = None,
    preconditions: tuple[Condition, ...] = (),
    seed: int | None = None,
    location: str | None = None,
) -> Activity:
    spec = intent_spec(intent_id)
    moment = _at(day_date, hhmm, tz)
    # An explicit shape from the caller still wins: the drive layer knows things about its own
    # activities — how long *this* nap should be — that no table can hold.
    shape = (
        duration_shape
        or _INTENT_DURATION_SHAPE.get(intent_id)
        or _CATEGORY_DURATION_SHAPE[spec.category]
    )
    if duration is not None:
        low, pref, high = duration
    elif intent_id == "sleep":
        # The night length is set by the sleep model, never by the category shape.
        low, pref, high = _SLEEP_DURATION
    elif seed is not None:
        low, pref, high = _sample_duration(shape, seed, day_date, index, intent_id)
    elif duration_shape is not None:
        low, pref, high = duration_shape[0], duration_shape[1], duration_shape[2]
    elif intent_id == "sleep":
        low, pref, high = _SLEEP_DURATION
    elif intent_id in _INTENT_DURATION_SHAPE:
        low, _, high, _ = _INTENT_DURATION_SHAPE[intent_id]
        pref = _INTENT_DURATION_SHAPE[intent_id][1]
    else:
        low, pref, high = _CATEGORY_DURATION_MINUTES[spec.category]
    labels = [f"activity:{recurring_activity_id}"] if recurring_activity_id else []
    if label:
        labels.append(label)
    # An intent that ends somewhere else declares both rooms, in the order its process model reads
    # them: `activity_location[0]` is where the activity happens, `[1]` where it leaves the
    # resident. Only the nocturnal toilet visit uses this, and it is why it can put her back to bed.
    #
    # `location` is the outline overriding the first of those: the room this *habit* uses, where
    # the catalog only knows the room the intent usually uses. The return room is not overridden —
    # it says where the body ends up, which is a property of the intent and not of the habit.
    location_ids = [location or spec.default_location]
    if spec.return_location is not None:
        location_ids.append(spec.return_location)
    return Activity(
        activity_id=f"{day_date.isoformat()}_{index:02d}_{intent_id}",
        actor_id=actor_id,
        intent=intent_id,
        location_ids=location_ids,
        start_window=window_around(moment, _WINDOW_FLEX),
        duration=DurationRange(minimum_minutes=low, preferred_minutes=pref, maximum_minutes=high),
        mandatory=not truncatable,
        allow_boundary_truncation=truncatable,
        can_overlap_for_actor=nested,
        preconditions=list(preconditions),
        labels=labels,
    )


def activity_from_intent(
    intent_id: str,
    day_date: date,
    moment: datetime,
    actor_id: str,
    *,
    index: int,
    label: str | None = None,
    nested: bool = False,
    duration_shape: tuple[int, int, int, float] | None = None,
    preconditions: tuple[Condition, ...] = (),
    seed: int | None = None,
) -> Activity:
    """One optional occurrence of an intent, at a moment already decided.

    The public door onto `_activity` for a caller that works in absolute times rather than in the
    day's HH:MM — the expander, placing an occurrence into a gap it can only see once the wobble
    and the bands are done. Optional and boundary-truncatable, because nothing that fills an empty
    afternoon should be able to make a day infeasible.
    """
    return _activity(
        intent_id,
        day_date,
        f"{moment.hour:02d}:{moment.minute:02d}",
        moment.tzinfo,  # type: ignore[arg-type]
        actor_id,
        index=index,
        truncatable=True,
        nested=nested,
        label=label,
        duration_shape=duration_shape,
        preconditions=preconditions,
        seed=seed,
    )


def _sample_duration(
    shape: tuple[int, int, int, float], seed: int, day_date: date, index: int, intent_id: str
) -> tuple[int, int, int]:
    """Draw this occurrence's preferred duration from its log-normal shape."""
    low, median, high, sigma = shape
    rng = _rng(seed, "duration", day_date.isoformat(), index, intent_id)
    preferred = median * math.exp(rng.gauss(0, sigma))
    return low, int(round(max(low, min(preferred, high)))), high


def _rng(seed: int, *parts: object) -> random.Random:
    key = "|".join(str(part) for part in (seed, *parts))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _to_minutes(hhmm: str) -> int:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return hours * 60 + minutes


def _to_hhmm(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def _at(day_date: date, hhmm: str, tz: ZoneInfo) -> datetime:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return datetime.combine(day_date, time(hours, minutes), tzinfo=tz)


def at_offset(day_date: date, minutes: int, tz: ZoneInfo) -> datetime:
    """``minutes`` of real elapsed time after local midnight.

    The counterpart of `window_around` for the sites that build a moment from a minute count: two
    offsets drawn from the same day stay in the order their numbers imply, which wall-clock addition
    does not guarantee across a spring-forward transition.
    """
    midnight = datetime.combine(day_date, time.min, tzinfo=tz)
    return (midnight.astimezone(UTC) + timedelta(minutes=minutes)).astimezone(tz)


def window_around(moment: datetime, flex: timedelta) -> DateTimeWindow:
    """A window of real elapsed time either side of ``moment``.

    Adding a timedelta to an aware datetime is wall-clock arithmetic: the naive fields move and the
    offset is re-derived afterwards. On the spring-forward day that produces edges naming local
    times that never happen — 02:46 in a zone whose clock jumps 02:00 to 03:00 — which ZoneInfo
    resolves with the *pre*-transition offset. The edge then sits after the moment it is supposed to
    precede, and the window is rejected downstream for `earliest <= preferred <= latest`. Shifting
    in UTC and converting back keeps the three edges ordered on every day of the year, and is what
    a fifteen-minute window means anyway.

    ``moment`` itself gets the same treatment, because it may already *be* one of those local times
    that never happen: `_at` builds it by attaching the zone to a wall-clock reading, so a night
    visit drawn at 02:24 on the day the clock jumps 02:00 to 03:00 is stored with the pre-transition
    offset. Python compares two aware datetimes sharing one tzinfo object by their naive fields
    alone, so the ordering guard above is defeated exactly there — the earliest edge reads 03:09 and
    is judged to fall *after* a preferred moment reading 02:24, and the window is rejected. Rounding
    the moment through UTC lands it on the local time the clock actually showed.
    """
    base = moment.astimezone(UTC)
    return DateTimeWindow(
        earliest=(base - flex).astimezone(moment.tzinfo),
        preferred=base.astimezone(moment.tzinfo),
        latest=(base + flex).astimezone(moment.tzinfo),
    )
