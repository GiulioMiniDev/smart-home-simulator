"""Deterministically expand a frozen behavioural profile into a per-day cadence calendar.

This stage uses no LLM. It rolls each activity's cadence rule over a chosen horizon (in months) into
a concrete, seeded schedule of due recurring activities per day, each with a target time drawn
inside its window.
The calendar is the *planned* activity ground truth: it is known before any day is generated,
is
exactly what the program scheduled, and later tells the day generator which recurring activities
are due each day.
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
from smart_home_sim.hybrid_planning.recurring_activities import (
    BehavioralProfile,
    CadencePeriod,
    RecurringActivity,
    RecurringActivityKind,
    Weekday,
    weekday_of,
)

GENERATOR_NAME = "smart-home-sim.hybrid_planning.cadence"
GENERATOR_VERSION = "1.0.0"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CadenceError(ValueError):
    """The requested horizon or profile could not be turned into a calendar."""


class ActivityOccurrence(ContractModel):
    recurring_activity_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: RecurringActivityKind
    target_time: str
    window_start: str
    window_end: str
    # Carried through from the activity so the day builder need not re-infer it from prose.
    intent: str | None = None


class CalendarDay(ContractModel):
    date: str
    weekday: Weekday
    occurrences: list[ActivityOccurrence] = Field(default_factory=list)

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
    """Roll the profile's recurring activities over ``months`` from ``start_date`` into a seeded
    calendar."""
    if months < 1:
        raise CadenceError("horizon must be at least one month")
    end_date = add_months(start_date, months)

    per_activity_due = {
        activity.recurring_activity_id: _due_times(activity, start_date, end_date, seed)
        for activity in profile.recurring_activities
    }
    by_id = {activity.recurring_activity_id: activity for activity in profile.recurring_activities}

    days: list[CalendarDay] = []
    total = 0
    current = start_date
    while current < end_date:
        occurrences: list[ActivityOccurrence] = []
        for recurring_activity_id, schedule in per_activity_due.items():
            activity = by_id[recurring_activity_id]
            occurrences.extend(
                ActivityOccurrence(
                    recurring_activity_id=activity.recurring_activity_id,
                    label=activity.label,
                    kind=activity.kind,
                    intent=activity.intent,
                    target_time=target,
                    window_start=activity.cadence.window_start,
                    window_end=activity.cadence.window_end,
                )
                for target in schedule.get(current, ())
            )
        occurrences.sort(key=lambda item: (item.target_time, item.recurring_activity_id))
        total += len(occurrences)
        days.append(
            CalendarDay(
                date=current.isoformat(),
                weekday=weekday_of(current),
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


def _due_times(
    activity: RecurringActivity, start: date, end: date, seed: int
) -> dict[date, list[str]]:
    """The days this activity is due, and the target time(s) inside each of them.

    Several times on one day is only ever the daily period's business: over a week or a month
    `timesPerPeriod` counts the days, and each of those days holds one occurrence.
    """
    cadence = activity.cadence
    due: dict[date, list[str]] = {}
    if cadence.period is CadencePeriod.day:
        # `weekdays` restricts a daily activity to the days it actually happens on, which the
        # weekly and monthly branches have always honoured and this one silently ignored: an
        # authored bundle declaring a 06:10 alarm on `day` with monday-to-friday got it on
        # Saturday and Sunday too, and the profile said nothing was wrong. The stride counts
        # eligible days only, so "every second working day" means what it reads as; with no
        # weekdays declared every day is eligible and the schedule is unchanged.
        weekdays = set(cadence.weekdays)
        current = start
        index = 0
        while current < end:
            if not weekdays or weekday_of(current) in weekdays:
                if index % cadence.every_n_periods == 0:
                    due[current] = _daily_target_times(activity, current, seed)
                index += 1
            current += timedelta(days=1)
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
            for chosen in _select_week_dates(activity, week_index, dates, seed):
                due[chosen] = [_target_time(activity, chosen, seed)]
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
        for chosen in _select_month_dates(activity, year, month, dates, seed):
            due[chosen] = [_target_time(activity, chosen, seed)]
    return due


def _select_week_dates(
    activity: RecurringActivity, week_index: int, dates: list[date], seed: int
) -> list[date]:
    """Which days of this week the activity falls on: `weekdays` says where, `timesPerPeriod` how
    many.

    The two are a filter and a count, and this branch used to read the filter as the whole answer —
    a gym declared twice a week on monday-to-friday was scheduled on all five, and a weekly shop
    named on friday, saturday and sunday happened on each of the three. The monthly branch below
    has always composed them the right way round; this one now matches it, which is also what makes
    a weekday list usable as "these are the days it *could* fall on" rather than "these are the days
    it does".

    A week with no declared weekdays is unchanged down to the seeding key, so every horizon whose
    activities named none expands to exactly the calendar it did before.
    """
    weekdays = set(activity.cadence.weekdays)
    candidates = [day for day in dates if weekday_of(day) in weekdays] if weekdays else dates
    if not candidates:
        return []
    count = min(activity.cadence.times_per_period, len(candidates))
    rng = _rng(seed, activity.recurring_activity_id, "week", week_index)
    return sorted(rng.sample(candidates, count))


def _select_month_dates(
    activity: RecurringActivity, year: int, month: int, dates: list[date], seed: int
) -> list[date]:
    weekdays = set(activity.cadence.weekdays)
    candidates = [day for day in dates if weekday_of(day) in weekdays] if weekdays else dates
    if not candidates:
        return []
    count = min(activity.cadence.times_per_period, len(candidates))
    rng = _rng(seed, activity.recurring_activity_id, "month", year, month)
    return sorted(rng.sample(candidates, count))


def _daily_target_times(activity: RecurringActivity, day: date, seed: int) -> list[str]:
    """Spread a daily activity's occurrences across its window, one per equal sub-band.

    Drawing every occurrence from the whole window would let a working day's four blocks all land
    before eleven; splitting the window first is what makes "four times a day" mean four times
    *through* the day. The sub-bands are equal and contiguous, so the occurrences stay in a stable
    order and the ground truth reads morning-to-evening.

    Nothing here reaches the single-occurrence case, which keeps its original draw down to the
    seeding key: every horizon generated before daily counts were honoured still expands to exactly
    the same calendar.
    """
    cadence = activity.cadence
    if cadence.times_per_period == 1:
        return [_target_time(activity, day, seed)]
    low = _minutes(cadence.window_start)
    high = _minutes(cadence.window_end)
    width = (high - low) / cadence.times_per_period
    times: list[str] = []
    for index in range(cadence.times_per_period):
        first = int(low + index * width)
        last = max(first, int(low + (index + 1) * width) - 1)
        rng = _rng(seed, activity.recurring_activity_id, "time", day.isoformat(), index)
        times.append(_hhmm(rng.randint(first, last)))
    return times


def _target_time(activity: RecurringActivity, day: date, seed: int) -> str:
    low = _minutes(activity.cadence.window_start)
    high = _minutes(activity.cadence.window_end)
    rng = _rng(seed, activity.recurring_activity_id, "time", day.isoformat())
    return _hhmm(rng.randint(low, high))


def _rng(seed: int, *parts: object) -> random.Random:
    key = "|".join(str(part) for part in (seed, *parts))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _hhmm(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def add_months(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last_day = _calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))
