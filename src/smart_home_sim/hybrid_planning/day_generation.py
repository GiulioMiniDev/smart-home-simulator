"""Stage C (deterministic substrate): turn a cadence calendar into simulatable scenario days.

Every activity in a day must use one of the shared canonical intents (the only ones the process
package can execute), so each due habit is mapped to an intent and each day gets a minimal scaffold
(wake at the start, sleep at the end). The result is a scenario chunk (world + days) that compiles
and simulates. The LLM day layer will later enrich and vary these days; this substrate guarantees a
valid, simulatable day always exists and is the fallback.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from smart_home_sim.domain.models import (
    Activity,
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

# Substring keywords mapping a free-text habit label to a canonical intent. The *longest* matching
# keyword wins, not the first one listed: with first-match-wins the generic "wash" swallowed "wash
# up the dishes", and "hygiene" made `evening_hygiene` unreachable outright, so habits were silently
# recorded in the ground truth as the wrong activity.
_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("take_morning_medication", ("medication", "medicine", "pill", "tablet", "insulin")),
    ("morning_toilet_and_shower", ("shower",)),
    ("morning_toilet_and_wash", ("wash", "toilet", "hygiene", "brush")),
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
}
# A nocturnal bathroom trip is short and reuses the only executable toilet intent; the label keeps
# it distinguishable from the morning routine in the ground truth.
_NIGHT_VISIT_INTENT = "morning_toilet_and_wash"
_NIGHT_VISIT_LABEL = "night_visit"
_NIGHT_VISIT_SHAPE = (3, 6, 12, 0.35)
_NAP_INTENT = "rest_or_nap"
# An unscheduled reach-out when the need for company ran high. Its own label keeps it out of the
# habit ground truth: it happened, but nobody planned it.
_UNPLANNED_SOCIAL_INTENT = "phone_call"
_UNPLANNED_SOCIAL_LABEL = "social_need_contact"
_UNPLANNED_SOCIAL_SHAPE = (8, 18, 35, 0.30)
# Evening band a spontaneous call may occupy, in minutes after midnight (17:00-21:30).
_UNPLANNED_SOCIAL_WINDOW = (17 * 60, 21 * 60 + 30)
# A debt nap is its own thing, much shorter than the generic leisure band it would otherwise
# inherit. (minimumMinutes, medianMinutes, maximumMinutes, logSigma)
_NAP_SHAPE = (20, 40, 75, 0.30)
# Afternoon band a debt nap may occupy, in minutes after midnight (13:00-18:30).
_NAP_WINDOW = (13 * 60, 18 * 60 + 30)


def habit_to_intent(label: str, kind: str | None = None) -> str:
    """Map a free-text habit label to a canonical intent (deterministic, longest keyword match).

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
    habit_id: str | None = None
    truncatable: bool = False
    label: str | None = None
    # An exact (minimum, preferred, maximum) band, used where the value is already decided (the
    # night length comes from the sleep model).
    duration: tuple[int, int, int] | None = None
    # A (minimum, median, maximum, logSigma) shape to draw from, overriding the intent's category.
    duration_shape: tuple[int, int, int, float] | None = None


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
            habit_id=entry.habit_id,
            truncatable=entry.truncatable,
            label=entry.label,
            duration=entry.duration,
            duration_shape=entry.duration_shape,
            seed=seed,
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
    seed: int | None = None,
) -> DayPlan:
    """Deterministic DayPlan: wake, the due habits mapped to intents, then a terminal sleep.

    Without ``rhythm`` this is the frozen substrate: a fixed 06:00 wake and 22:30 lights-out on
    every single day of the horizon. With a rhythm, the day is shaped by the drive state it
    inherited — the night starts and ends where the sleep model put it, nocturnal bathroom trips
    are laid down before the wake, and a nap appears when sleep debt has built up.
    """
    entries: list[TimelineEntry] = []
    wake_time = WAKE_TIME
    sleep_time = SLEEP_TIME
    if rhythm is not None:
        wake_time = rhythm.wake_hhmm
        sleep_time = rhythm.sleep_hhmm
        # The trips belong to the night that is *ending*, so they precede the wake and land in the
        # small hours the log was previously silent through.
        entries.extend(
            TimelineEntry(
                _NIGHT_VISIT_INTENT,
                visit,
                label=_NIGHT_VISIT_LABEL,
                duration_shape=_NIGHT_VISIT_SHAPE,
            )
            for visit in rhythm.night_visits
            if visit < wake_time
        )
    entries.append(TimelineEntry("wake_up", wake_time))
    for occurrence in day.occurrences:
        entries.append(
            TimelineEntry(
                habit_to_intent(occurrence.label, occurrence.kind.value),
                _shift(occurrence.target_time, rhythm, wake_time),
                habit_id=occurrence.habit_id,
            )
        )
    entries.sort(key=lambda item: item.hhmm)
    if rhythm is not None and rhythm.nap:
        slot = _free_slot(entries, _NAP_WINDOW, _NAP_SHAPE)
        if slot is not None:
            entries.append(
                TimelineEntry(_NAP_INTENT, slot, label="sleep_debt_nap", duration_shape=_NAP_SHAPE)
            )
    if rhythm is not None and rhythm.unplanned_social_contact:
        slot = _free_slot(entries, _UNPLANNED_SOCIAL_WINDOW, _UNPLANNED_SOCIAL_SHAPE)
        if slot is not None:
            entries.append(
                TimelineEntry(
                    _UNPLANNED_SOCIAL_INTENT,
                    slot,
                    label=_UNPLANNED_SOCIAL_LABEL,
                    duration_shape=_UNPLANNED_SOCIAL_SHAPE,
                )
            )
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


def _free_slot(
    entries: list[TimelineEntry],
    window: tuple[int, int],
    shape: tuple[int, int, int, float],
) -> str | None:
    """Drop a drive-generated activity into the widest free gap of ``window``, or not at all.

    An activity pinned to a fixed clock time collides with whatever habit already sits there and
    makes the day unsolvable, so it has to be placed against the schedule that actually exists.
    """
    occupied: list[tuple[int, int]] = []
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


def _shift(hhmm: str, rhythm: DayRhythm | None, wake_time: str) -> str:
    """Slide a habit's target time by the day's meal shift, never before the resident is up."""
    if rhythm is None or rhythm.meal_shift_minutes == 0:
        return hhmm
    shifted = _to_minutes(hhmm) + rhythm.meal_shift_minutes
    floor = _to_minutes(wake_time) + 5
    return _to_hhmm(max(floor, min(shifted, 23 * 60 + 30)))


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
    habit_id: str | None = None,
    truncatable: bool = False,
    label: str | None = None,
    duration: tuple[int, int, int] | None = None,
    duration_shape: tuple[int, int, int, float] | None = None,
    seed: int | None = None,
) -> Activity:
    spec = intent_spec(intent_id)
    moment = _at(day_date, hhmm, tz)
    shape = duration_shape or _CATEGORY_DURATION_SHAPE[spec.category]
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
    else:
        low, pref, high = _CATEGORY_DURATION_MINUTES[spec.category]
    labels = [f"habit:{habit_id}"] if habit_id else []
    if label:
        labels.append(label)
    return Activity(
        activity_id=f"{day_date.isoformat()}_{index:02d}_{intent_id}",
        actor_id=actor_id,
        intent=intent_id,
        location_ids=[spec.default_location],
        start_window=DateTimeWindow(
            earliest=moment - _WINDOW_FLEX, preferred=moment, latest=moment + _WINDOW_FLEX
        ),
        duration=DurationRange(minimum_minutes=low, preferred_minutes=pref, maximum_minutes=high),
        mandatory=not truncatable,
        allow_boundary_truncation=truncatable,
        labels=labels,
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
