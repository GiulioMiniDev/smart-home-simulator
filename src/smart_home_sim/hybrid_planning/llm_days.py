"""Stage C LLM layer: arrange varied, coherent days around the calendar's due habits.

One LLM call per week returns a light per-day timeline of intents (from the shared vocabulary),
arranged around that week's due habits plus everyday filler. Deterministic code validates the
intents, frames each day with a wake and a terminal sleep, and **compile-gates** every candidate:
a day is accepted only if it compiles, otherwise the deterministic substrate day is used. Generation
never simulates (that is the researcher's separate step); compilation is the deterministic gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from smart_home_sim.compiler import compile_scenario
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar, CalendarDay
from smart_home_sim.hybrid_planning.day_generation import (
    SLEEP_TIME,
    WAKE_TIME,
    TimelineEntry,
    build_day_plan,
    build_scenario_from_day_plan,
    plan_from_entries,
)
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG, intent_ids
from smart_home_sim.hybrid_planning.lmstudio import (
    ChatMessage,
    LMStudioClient,
    LMStudioContentError,
)
from smart_home_sim.hybrid_planning.world import PlanningWorld

WEEK = 7
DAYS_MAX_TOKENS = 12288
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class LlmDaysResult:
    day_plans: dict[str, Any]  # date -> DayPlan
    llm_authored_count: int
    fallback_count: int


def generate_llm_day_plans(
    world: PlanningWorld,
    calendar: CadenceCalendar,
    client: LMStudioClient,
    *,
    start_index: int = 0,
    days: int | None = None,
    seed: int | None = None,
    max_repairs: int = 1,
) -> LlmDaysResult:
    """Author days via weekly LLM calls, compile-gating candidates with deterministic fallback."""
    limit = len(calendar.days) if days is None else start_index + days
    day_slice = calendar.days[start_index:limit]
    if not day_slice:
        raise ValueError("requested calendar slice is empty")
    actor_id = world.residents[0].resident_id
    vocabulary = set(intent_ids())
    plans: dict[str, Any] = {}
    llm_count = 0

    for offset in range(0, len(day_slice), WEEK):
        week = day_slice[offset : offset + WEEK]
        timelines = _author_week(
            client, world, week, vocabulary, seed=seed, max_repairs=max_repairs
        )
        for day in week:
            entries = timelines.get(day.date) if timelines else None
            candidate = None
            if entries:
                candidate = plan_from_entries(
                    date.fromisoformat(day.date),
                    day.weekday.value,
                    entries,
                    timezone=world.time_zone,
                    actor_id=actor_id,
                )
                if compile_scenario(build_scenario_from_day_plan(world, candidate)).plan is None:
                    candidate = None
            if candidate is None:
                plans[day.date] = build_day_plan(day, timezone=world.time_zone, actor_id=actor_id)
            else:
                plans[day.date] = candidate
                llm_count += 1

    return LlmDaysResult(
        day_plans=plans, llm_authored_count=llm_count, fallback_count=len(day_slice) - llm_count
    )


def _author_week(
    client: LMStudioClient,
    world: PlanningWorld,
    week: list[CalendarDay],
    vocabulary: set[str],
    *,
    seed: int | None,
    max_repairs: int,
) -> dict[str, list[TimelineEntry]] | None:
    """Return per-date entry lists from one weekly LLM call, or None if it could not be parsed."""
    messages = _week_messages(world, week)
    for _ in range(max_repairs + 1):
        try:
            completion = client.complete_json(messages, seed=seed, max_tokens=DAYS_MAX_TOKENS)
            return _parse_week(completion.data, week, vocabulary)
        except (LMStudioContentError, _WeekParseError):
            messages = _week_messages(world, week, retry=True)
    return None


class _WeekParseError(ValueError):
    """The weekly plan could not be turned into per-day timelines."""


def _parse_week(
    data: Any, week: list[CalendarDay], vocabulary: set[str]
) -> dict[str, list[TimelineEntry]]:
    if isinstance(data, dict):
        raw_days = data.get("days", data.get("plan", []))
    elif isinstance(data, list):
        raw_days = data
    else:
        raise _WeekParseError("weekly plan must be a JSON object or array")
    if not isinstance(raw_days, list):
        raise _WeekParseError("weekly plan must contain a 'days' array")

    valid_dates = {day.date for day in week}
    by_date: dict[str, list[TimelineEntry]] = {}
    for raw in raw_days:
        if not isinstance(raw, dict):
            continue
        day_date = raw.get("date")
        if day_date not in valid_dates:
            continue
        entries = _entries_from_timeline(raw.get("timeline", []), vocabulary)
        if entries:
            by_date[day_date] = entries
    if not by_date:
        raise _WeekParseError("no usable day timelines")
    return by_date


def _entries_from_timeline(items: Any, vocabulary: set[str]) -> list[TimelineEntry]:
    if not isinstance(items, list):
        return []
    middle: list[TimelineEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        intent = item.get("intent")
        around = item.get("around", item.get("time"))
        if intent in {"wake_up", "sleep"} or intent not in vocabulary:
            continue
        if not isinstance(around, str) or not _HHMM_RE.match(around):
            continue
        habit = item.get("habit") if isinstance(item.get("habit"), str) else None
        middle.append(TimelineEntry(intent, around, habit_id=habit))
    middle.sort(key=lambda entry: entry.hhmm)
    return [
        TimelineEntry("wake_up", WAKE_TIME),
        *middle,
        TimelineEntry("sleep", SLEEP_TIME, truncatable=True),
    ]


def _week_messages(
    world: PlanningWorld, week: list[CalendarDay], *, retry: bool = False
) -> list[ChatMessage]:
    resident = world.residents[0]
    profile = resident.profile
    summary = (
        f"{resident.display_name}, age {profile.get('age')}, {profile.get('occupation')}, "
        f"{profile.get('household')}, in {profile.get('city')}. "
        f"Health: {', '.join(profile.get('health') or []) or 'none noted'}."
    )
    due_lines = []
    for day in week:
        habits = ", ".join(
            f"{occ.label} ~{occ.target_time} [{occ.habit_id}]" for occ in day.occurrences
        )
        due_lines.append(f"{day.date} ({day.weekday.value}): {habits or 'no fixed habits'}")
    labels = ", ".join(f"{spec.intent_id}={spec.label}" for spec in INTENT_CATALOG)
    system = (
        "You plan realistic daily routines for a smart-home behavioural dataset. "
        "Reply with a single JSON object and no prose."
    )
    user = (
        f"Person: {summary}\n\n"
        "Plan each of these days. For each date the fixed due habits are listed with a rough time "
        "and id; arrange a plausible, varied day that naturally includes them plus everyday "
        "activities (meals, hygiene, leisure). Vary weekdays vs weekend; do not repeat identical "
        "days.\n\n" + "\n".join(due_lines) + "\n\n"
        f"Use ONLY these activity intents (id=meaning): {labels}.\n"
        'Return JSON {"days": [{"date": "YYYY-MM-DD", "timeline": [{"intent": "<id>", '
        '"around": "HH:MM", "habit": "<habit id or null>"}]}]}. Order each timeline by time. '
        "You do not need to include wake_up or sleep; they are added automatically."
    )
    if retry:
        user += "\n\nThe previous reply was unusable. Return exactly the JSON structure requested."
    return [ChatMessage("system", system), ChatMessage("user", user)]
