"""Stage C (deterministic substrate): turn a cadence calendar into simulatable scenario days.

Every activity in a day must use one of the shared canonical intents (the only ones the process
package can execute), so each due habit is mapped to an intent and each day gets a minimal scaffold
(wake at the start, sleep at the end). The result is a scenario chunk (world + days) that compiles
and simulates. The LLM day layer will later enrich and vary these days; this substrate guarantees a
valid, simulatable day always exists and is the fallback.
"""

from __future__ import annotations

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
from smart_home_sim.hybrid_planning.intents import IntentCategory, intent_spec
from smart_home_sim.hybrid_planning.world import PlanningWorld, assemble_scenario

WAKE_TIME = "06:00"
SLEEP_TIME = "22:30"
_WINDOW_FLEX = timedelta(minutes=15)
DEFAULT_INTENT = "read_and_rest"

# Substring keywords mapping a free-text habit label to a canonical intent (first match wins).
_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("take_morning_medication", ("medication", "medicine", "pill", "tablet", "insulin")),
    ("morning_toilet_and_shower", ("shower",)),
    ("morning_toilet_and_wash", ("wash", "toilet", "hygiene", "brush")),
    ("evening_hygiene", ("evening hygiene", "bedtime wash")),
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
    ("hang_laundry", ("hang laundry", "dry clothes")),
    ("indoor_light_exercise", ("exercise", "stretch", "workout", "yoga", "gym")),
    ("evening_walk", ("walk", "stroll", "outdoors", "outside", "garden")),
    ("watch_television", ("tv", "television", "watch", "documentary", "news")),
    ("call_mother", ("call", "phone", "video call", "visit", "chat")),
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


def habit_to_intent(label: str, kind: str | None = None) -> str:
    """Map a free-text habit label to a canonical intent (deterministic, first keyword match)."""
    lowered = label.lower()
    for intent_id, keywords in _INTENT_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return intent_id
    return DEFAULT_INTENT


def build_day_plan(day: CalendarDay, *, timezone: str, actor_id: str) -> DayPlan:
    """Build a simulatable DayPlan: wake, the due habits mapped to intents, then sleep."""
    tz = ZoneInfo(timezone)
    day_date = date.fromisoformat(day.date)
    activities: list[Activity] = [
        _activity("wake_up", day_date, WAKE_TIME, tz, actor_id, index=0)
    ]
    for position, occurrence in enumerate(day.occurrences, start=1):
        intent_id = habit_to_intent(occurrence.label, occurrence.kind.value)
        activities.append(
            _activity(
                intent_id,
                day_date,
                occurrence.target_time,
                tz,
                actor_id,
                index=position,
                habit_id=occurrence.habit_id,
            )
        )
    activities.append(
        _activity(
            "sleep",
            day_date,
            SLEEP_TIME,
            tz,
            actor_id,
            index=len(activities),
            truncatable=True,
        )
    )
    return DayPlan(
        date=day_date,
        context=DayContext(day_type=day.weekday.value),
        activities=activities,
    )


def build_day_scenario(world: PlanningWorld, day: CalendarDay) -> Scenario:
    """Assemble a one-day scenario. Days are independent so the CP-SAT solver stays fast and the
    horizon scales; the dataset is the concatenation of per-day sensor logs (absolute timestamps).
    """
    actor_id = world.residents[0].resident_id
    day_plan = build_day_plan(day, timezone=world.time_zone, actor_id=actor_id)
    tz = ZoneInfo(world.time_zone)
    day_date = date.fromisoformat(day.date)
    start = datetime.combine(day_date, time(0, 0), tzinfo=tz)
    end = datetime.combine(day_date + timedelta(days=1), time(0, 0), tzinfo=tz)
    return assemble_scenario(world, days=[day_plan], window=SimulationWindow(start=start, end=end))


def build_day_scenarios(
    world: PlanningWorld,
    calendar: CadenceCalendar,
    *,
    start_index: int = 0,
    days: int | None = None,
) -> list[Scenario]:
    """Build one independent scenario per calendar day over the requested slice."""
    limit = len(calendar.days) if days is None else start_index + days
    chunk = calendar.days[start_index:limit]
    if not chunk:
        raise ValueError("requested calendar slice is empty")
    return [build_day_scenario(world, day) for day in chunk]


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
) -> Activity:
    spec = intent_spec(intent_id)
    moment = _at(day_date, hhmm, tz)
    low, pref, high = (
        _SLEEP_DURATION if intent_id == "sleep" else _CATEGORY_DURATION_MINUTES[spec.category]
    )
    return Activity(
        activity_id=f"{day_date.isoformat()}_{index:02d}_{intent_id}",
        actor_id=actor_id,
        intent=intent_id,
        location_ids=[spec.default_location],
        start_window=DateTimeWindow(
            earliest=moment - _WINDOW_FLEX, preferred=moment, latest=moment + _WINDOW_FLEX
        ),
        duration=DurationRange(
            minimum_minutes=low, preferred_minutes=pref, maximum_minutes=high
        ),
        mandatory=not truncatable,
        allow_boundary_truncation=truncatable,
        labels=[f"habit:{habit_id}"] if habit_id else [],
    )


def _at(day_date: date, hhmm: str, tz: ZoneInfo) -> datetime:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return datetime.combine(day_date, time(hours, minutes), tzinfo=tz)
