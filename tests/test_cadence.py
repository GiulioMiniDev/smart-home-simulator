from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.cadence import (
    CadenceError,
    CalendarDay,
    _add_months,
    _due_times,
    _target_time,
    build_cadence_calendar,
)
from smart_home_sim.hybrid_planning.habits import (
    BehavioralProfile,
    CadencePeriod,
    Habit,
    HabitCadence,
    HabitKind,
    Weekday,
)

runner = CliRunner()
_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
_START = date(2026, 8, 3)  # a Monday
_END = date(2026, 9, 3)


def _habit(
    habit_id: str,
    period: CadencePeriod,
    *,
    times: int = 1,
    every: int = 1,
    weekdays: tuple[Weekday, ...] = (),
    window: tuple[str, str] = ("08:00", "09:00"),
    kind: HabitKind = HabitKind.anchor,
) -> Habit:
    return Habit(
        habit_id=habit_id,
        label=habit_id,
        kind=kind,
        cadence=HabitCadence(
            period=period,
            times_per_period=times,
            every_n_periods=every,
            weekdays=list(weekdays),
            window_start=window[0],
            window_end=window[1],
        ),
    )


def _profile() -> BehavioralProfile:
    habits = [
        _habit("morning_walk", CadencePeriod.day, kind=HabitKind.anchor),
        _habit("coffee", CadencePeriod.day, kind=HabitKind.anchor),
        _habit("evening_tea", CadencePeriod.day, kind=HabitKind.anchor),
        _habit(
            "groceries",
            CadencePeriod.week,
            weekdays=(Weekday.tuesday, Weekday.friday),
            kind=HabitKind.contextual,
        ),
        _habit("laundry", CadencePeriod.week, times=2, kind=HabitKind.contextual),
        _habit("cinema", CadencePeriod.week, every=2, kind=HabitKind.optional),
        _habit("call_family", CadencePeriod.week, times=2, kind=HabitKind.optional),
        _habit("checkup", CadencePeriod.month, every=3, kind=HabitKind.rare),
    ]
    return BehavioralProfile(
        profile_id="luigi_profile",
        persona_id="luigi",
        habits=habits,
        provenance=Provenance(author_type=AuthorType.rule_generator, generated_at=_NOW),
    )


def test_daily_habit_due_every_day() -> None:
    due = _due_times(_habit("d", CadencePeriod.day), _START, _END, seed=0)
    assert len(due) == (_END - _START).days == 31
    assert _START in due


def test_every_other_day_habit() -> None:
    due = _due_times(_habit("d", CadencePeriod.day, every=2), _START, _END, seed=0)
    assert len(due) == 16
    assert _START in due
    assert date(2026, 8, 4) not in due
    assert date(2026, 8, 5) in due


def test_weekly_with_weekdays_only_on_those_days() -> None:
    habit = _habit("g", CadencePeriod.week, weekdays=(Weekday.tuesday, Weekday.friday))
    due = _due_times(habit, _START, _END, seed=0)
    assert due
    assert all(day.weekday() in {1, 4} for day in due)


def test_weekly_without_weekdays_picks_times_per_bucket() -> None:
    habit = _habit("l", CadencePeriod.week, times=2)
    due = _due_times(habit, _START, _END, seed=7)
    # five 7-day buckets over 31 days (last is a 3-day partial), 2 picks each.
    assert len(due) == 10


def test_biweekly_with_weekday_only_active_weeks() -> None:
    habit = _habit("c", CadencePeriod.week, every=2, weekdays=(Weekday.monday,))
    due = _due_times(habit, _START, _END, seed=0)
    assert set(due) == {date(2026, 8, 3), date(2026, 8, 17), date(2026, 8, 31)}


def test_monthly_every_three_only_first_month() -> None:
    habit = _habit("checkup", CadencePeriod.month, every=3)
    due = _due_times(habit, _START, _END, seed=0)
    assert len(due) == 1
    assert next(iter(due)).month == 8


def test_monthly_with_weekday_filters_candidates() -> None:
    habit = _habit("m", CadencePeriod.month, weekdays=(Weekday.monday,))
    due = _due_times(habit, _START, _END, seed=3)
    assert due
    assert all(day.weekday() == 0 for day in due)


def test_target_time_falls_within_window() -> None:
    habit = _habit("t", CadencePeriod.day, window=("06:00", "08:00"))
    target = _target_time(habit, _START, seed=1)
    assert "06:00" <= target <= "08:00"


def test_build_calendar_shape_and_reproducibility() -> None:
    first = build_cadence_calendar(_profile(), start_date=_START, months=1, seed=5, now=_NOW)
    second = build_cadence_calendar(_profile(), start_date=_START, months=1, seed=5, now=_NOW)
    calendar = first.calendar
    assert len(calendar.days) == 31
    assert calendar.start_date == "2026-08-03"
    assert calendar.end_date == "2026-09-03"
    assert calendar.days[0].weekday is Weekday.monday
    assert first.total_occurrences == sum(len(day.occurrences) for day in calendar.days)
    # occurrences sorted by (target_time, habit_id) within each day
    for day in calendar.days:
        keys = [(item.target_time, item.habit_id) for item in day.occurrences]
        assert keys == sorted(keys)
    assert first.calendar.model_dump_json() == second.calendar.model_dump_json()


def test_seed_changes_times_but_not_daily_due_dates() -> None:
    profile = _profile()
    a = build_cadence_calendar(profile, start_date=_START, months=1, seed=1, now=_NOW).calendar
    b = build_cadence_calendar(profile, start_date=_START, months=1, seed=2, now=_NOW).calendar

    def daily_dates(cal) -> set[str]:
        return {
            day.date
            for day in cal.days
            for item in day.occurrences
            if item.habit_id == "morning_walk"
        }

    assert daily_dates(a) == daily_dates(b) == {day.date for day in a.days}


def test_build_calendar_rejects_zero_months() -> None:
    with pytest.raises(CadenceError):
        build_cadence_calendar(_profile(), start_date=_START, months=0, now=_NOW)


def test_add_months_clamps_end_of_month() -> None:
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert _add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert _add_months(date(2026, 3, 10), 6) == date(2026, 9, 10)


def test_calendar_day_rejects_bad_date() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        CalendarDay(date="2026/08/03", weekday=Weekday.monday)


def test_cli_build_calendar_writes_file(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(_profile().model_dump_json(by_alias=True), encoding="utf-8")
    output = tmp_path / "calendar.json"
    result = runner.invoke(
        cli.app,
        ["build-cadence-calendar", str(profile_path), "-o", str(output), "--start", "2026-08-03"],
    )
    assert result.exit_code == 0, result.output
    calendar = json.loads(output.read_text(encoding="utf-8"))
    assert calendar["documentType"] == "cadence_calendar"
    assert len(calendar["days"]) == 31


def test_cli_build_calendar_rejects_bad_start(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(_profile().model_dump_json(by_alias=True), encoding="utf-8")
    result = runner.invoke(
        cli.app,
        [
            "build-cadence-calendar",
            str(profile_path),
            "-o",
            str(tmp_path / "c.json"),
            "--start",
            "not-a-date",
        ],
    )
    assert result.exit_code != 0


def test_cli_build_calendar_rejects_bad_profile(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{broken}", encoding="utf-8")
    result = runner.invoke(
        cli.app,
        [
            "build-cadence-calendar",
            str(profile_path),
            "-o",
            str(tmp_path / "c.json"),
            "--start",
            "2026-08-03",
        ],
    )
    assert result.exit_code == 2
    assert "Cannot load behavioural profile" in result.output


def test_cli_build_calendar_rejects_overwriting_profile(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(_profile().model_dump_json(by_alias=True), encoding="utf-8")
    result = runner.invoke(
        cli.app,
        [
            "build-cadence-calendar",
            str(profile_path),
            "-o",
            str(profile_path),
            "--start",
            "2026-08-03",
        ],
    )
    assert result.exit_code != 0
