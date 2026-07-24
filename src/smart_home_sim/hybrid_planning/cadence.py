"""Deterministically expand a frozen behavioural profile into a per-day cadence calendar.

This stage uses no LLM. It rolls each habit's cadence rule over a chosen horizon (in months) into
a concrete, seeded schedule of due habits per day, each with a target time drawn inside its window.
The calendar is the *planned* habit-mining ground truth: it is known before any day is generated, is
exactly what the program scheduled, and later tells the day generator which habits are due each day.
Same profile + same seed + same horizon always yields an identical calendar.
"""

from __future__ import annotations

import calendar as _calendar
import hashlib
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.habits import (
    BehavioralProfile,
    CadencePeriod,
    Habit,
    HabitKind,
    Weekday,
)

GENERATOR_NAME = "smart-home-sim.hybrid_planning.cadence"
GENERATOR_VERSION = "1.0.0"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WEEKDAYS: list[Weekday] = list(Weekday)  # index matches date.weekday(): 0 = Monday


class CadenceError(ValueError):
    """The requested horizon or profile could not be turned into a calendar."""


class HabitOccurrence(ContractModel):
    habit_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: HabitKind
    target_time: str
    window_start: str
    window_end: str


class CalendarDay(ContractModel):
    date: str
    weekday: Weekday
    occurrences: list[HabitOccurrence] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_date(self) -> CalendarDay:
        if not _DATE_RE.match(self.date):
            raise ValueError(f"calendar date must be YYYY-MM-DD, got {self.date!r}")
        return self


class CadenceCalendar(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["cadence_calendar"] = "cadence_calendar"
    calendar_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    start_date: str
    end_date: str
    months: int = Field(ge=1)
    seed: int
    timezone: str = Field(min_length=1)
    days: list[CalendarDay] = Field(min_length=1)
    provenance: Provenance


@dataclass(frozen=True)
class CadenceCalendarResult:
    calendar: CadenceCalendar
    total_occurrences: int


def build_cadence_calendar(
    profile: BehavioralProfile,
    *,
    start_date: date,
    months: int,
    seed: int = 0,
    timezone: str = "Europe/Rome",
    now: datetime | None = None,
) -> CadenceCalendarResult:
    """Roll the profile's habits over ``months`` from ``start_date`` into a seeded calendar."""
    if months < 1:
        raise CadenceError("horizon must be at least one month")
    end_date = _add_months(start_date, months)

    per_habit_due = {
        habit.habit_id: _due_times(habit, start_date, end_date, seed) for habit in profile.habits
    }
    by_id = {habit.habit_id: habit for habit in profile.habits}

    days: list[CalendarDay] = []
    total = 0
    current = start_date
    while current < end_date:
        occurrences: list[HabitOccurrence] = []
        for habit_id, schedule in per_habit_due.items():
            target = schedule.get(current)
            if target is None:
                continue
            habit = by_id[habit_id]
            occurrences.append(
                HabitOccurrence(
                    habit_id=habit.habit_id,
                    label=habit.label,
                    kind=habit.kind,
                    target_time=target,
                    window_start=habit.cadence.window_start,
                    window_end=habit.cadence.window_end,
                )
            )
        occurrences.sort(key=lambda item: (item.target_time, item.habit_id))
        total += len(occurrences)
        days.append(
            CalendarDay(
                date=current.isoformat(),
                weekday=_weekday_of(current),
                occurrences=occurrences,
            )
        )
        current += timedelta(days=1)

    provenance = Provenance(
        author_type=AuthorType.rule_generator,
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        generated_at=now or datetime.now(UTC),
        parameters={"seed": seed, "months": months},
    )
    calendar = CadenceCalendar(
        calendar_id=f"{profile.persona_id}_calendar_{start_date.isoformat()}_{months}m",
        persona_id=profile.persona_id,
        profile_id=profile.profile_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        months=months,
        seed=seed,
        timezone=timezone,
        days=days,
        provenance=provenance,
    )
    return CadenceCalendarResult(calendar=calendar, total_occurrences=total)


def _due_times(habit: Habit, start: date, end: date, seed: int) -> dict[date, str]:
    cadence = habit.cadence
    due: dict[date, str] = {}
    if cadence.period is CadencePeriod.day:
        current = start
        index = 0
        while current < end:
            if index % cadence.every_n_periods == 0:
                due[current] = _target_time(habit, current, seed)
            current += timedelta(days=1)
            index += 1
        return due

    if cadence.period is CadencePeriod.week:
        buckets: dict[int, list[date]] = defaultdict(list)
        current = start
        while current < end:
            buckets[(current - start).days // 7].append(current)
            current += timedelta(days=1)
        for week_index, dates in buckets.items():
            if week_index % cadence.every_n_periods != 0:
                continue
            for chosen in _select_week_dates(habit, week_index, dates, seed):
                due[chosen] = _target_time(habit, chosen, seed)
        return due

    month_buckets: dict[tuple[int, int], list[date]] = defaultdict(list)
    current = start
    while current < end:
        month_buckets[(current.year, current.month)].append(current)
        current += timedelta(days=1)
    for (year, month), dates in month_buckets.items():
        ordinal = (year - start.year) * 12 + (month - start.month)
        if ordinal % cadence.every_n_periods != 0:
            continue
        for chosen in _select_month_dates(habit, year, month, dates, seed):
            due[chosen] = _target_time(habit, chosen, seed)
    return due


def _select_week_dates(habit: Habit, week_index: int, dates: list[date], seed: int) -> list[date]:
    weekdays = set(habit.cadence.weekdays)
    if weekdays:
        return [day for day in dates if _weekday_of(day) in weekdays]
    count = min(habit.cadence.times_per_period, len(dates))
    rng = _rng(seed, habit.habit_id, "week", week_index)
    return sorted(rng.sample(dates, count))


def _select_month_dates(
    habit: Habit, year: int, month: int, dates: list[date], seed: int
) -> list[date]:
    weekdays = set(habit.cadence.weekdays)
    candidates = [day for day in dates if _weekday_of(day) in weekdays] if weekdays else dates
    if not candidates:
        return []
    count = min(habit.cadence.times_per_period, len(candidates))
    rng = _rng(seed, habit.habit_id, "month", year, month)
    return sorted(rng.sample(candidates, count))


def _target_time(habit: Habit, day: date, seed: int) -> str:
    low = _minutes(habit.cadence.window_start)
    high = _minutes(habit.cadence.window_end)
    rng = _rng(seed, habit.habit_id, "time", day.isoformat())
    return _hhmm(rng.randint(low, high))


def _rng(seed: int, *parts: object) -> random.Random:
    key = "|".join(str(part) for part in (seed, *parts))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _weekday_of(day: date) -> Weekday:
    return _WEEKDAYS[day.weekday()]


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _hhmm(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def _add_months(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last_day = _calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))
