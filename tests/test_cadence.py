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
    _due_times,
    _target_time,
    add_months,
    build_cadence_calendar,
)
from smart_home_sim.hybrid_planning.recurring_activities import (
    ActivityCadence,
    BehavioralProfile,
    CadencePeriod,
    RecurringActivity,
    RecurringActivityKind,
    Weekday,
)

runner = CliRunner()
_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
_START = date(2026, 8, 3)  # a Monday
_END = date(2026, 9, 3)


def _recurring(
    recurring_activity_id: str,
    period: CadencePeriod,
    *,
    times: int = 1,
    every: int = 1,
    weekdays: tuple[Weekday, ...] = (),
    window: tuple[str, str] = ("08:00", "09:00"),
    kind: RecurringActivityKind = RecurringActivityKind.anchor,
) -> RecurringActivity:
    return RecurringActivity(
        recurring_activity_id=recurring_activity_id,
        label=recurring_activity_id,
        kind=kind,
        cadence=ActivityCadence(
            period=period,
            times_per_period=times,
            every_n_periods=every,
            weekdays=list(weekdays),
            window_start=window[0],
            window_end=window[1],
        ),
    )


def _profile() -> BehavioralProfile:
    recurring_activities = [
        _recurring("morning_walk", CadencePeriod.day, kind=RecurringActivityKind.anchor),
        _recurring("coffee", CadencePeriod.day, kind=RecurringActivityKind.anchor),
        _recurring("evening_tea", CadencePeriod.day, kind=RecurringActivityKind.anchor),
        _recurring(
            "groceries",
            CadencePeriod.week,
            weekdays=(Weekday.tuesday, Weekday.friday),
            kind=RecurringActivityKind.contextual,
        ),
        _recurring("laundry", CadencePeriod.week, times=2, kind=RecurringActivityKind.contextual),
        _recurring("cinema", CadencePeriod.week, every=2, kind=RecurringActivityKind.optional),
        _recurring("call_family", CadencePeriod.week, times=2, kind=RecurringActivityKind.optional),
        _recurring("checkup", CadencePeriod.month, every=3, kind=RecurringActivityKind.rare),
    ]
    return BehavioralProfile(
        profile_id="luigi_profile",
        persona_id="luigi",
        recurring_activities=recurring_activities,
        provenance=Provenance(author_type=AuthorType.rule_generator, generated_at=_NOW),
    )


def test_daily_habit_due_every_day() -> None:
    due = _due_times(_recurring("d", CadencePeriod.day), _START, _END, seed=0)
    assert len(due) == (_END - _START).days == 31
    assert _START in due


def test_every_other_day_habit() -> None:
    due = _due_times(_recurring("d", CadencePeriod.day, every=2), _START, _END, seed=0)
    assert len(due) == 16
    assert _START in due
    assert date(2026, 8, 4) not in due
    assert date(2026, 8, 5) in due


def test_daily_habit_with_several_occurrences_spreads_them_through_the_window() -> None:
    """A working day is blocks, and `timesPerPeriod` on a daily cadence is how many.

    It used to be discarded: the daily branch scheduled one occurrence whatever the field said, so
    an author writing four got one and no warning.
    """
    activity = _recurring("work", CadencePeriod.day, times=4, window=("09:00", "17:00"))

    due = _due_times(activity, _START, _END, seed=3)

    assert len(due) == 31
    for day, times in due.items():
        assert len(times) == 4, day
        # One per equal sub-band, so the blocks stay in order and cover the whole window.
        assert times == sorted(times)
        assert "09:00" <= times[0] < "11:00"
        assert "15:00" <= times[3] <= "17:00"


def test_daily_habit_honours_the_weekdays_it_declares() -> None:
    """The weekly and monthly branches always did; this one silently ignored them.

    An authored bundle declaring a 06:10 alarm on `period: day` with monday-to-friday got it on
    Saturday and Sunday as well, and nothing in the profile said so.
    """
    activity = _recurring(
        "work",
        CadencePeriod.day,
        times=3,
        weekdays=(
            Weekday.monday,
            Weekday.tuesday,
            Weekday.wednesday,
            Weekday.thursday,
            Weekday.friday,
        ),
        window=("09:00", "18:00"),
    )

    due = _due_times(activity, _START, _END, seed=3)

    assert due
    assert all(day.weekday() < 5 for day in due)
    assert all(len(times) == 3 for times in due.values())


def test_a_single_daily_occurrence_keeps_the_draw_it_always_had() -> None:
    """Honouring the count must not silently re-time every horizon already generated."""
    activity = _recurring("d", CadencePeriod.day, window=("06:00", "08:00"))

    due = _due_times(activity, _START, _END, seed=11)

    assert due[_START] == [_target_time(activity, _START, seed=11)]


def test_a_daily_cadence_cannot_ask_for_more_blocks_than_its_window_holds() -> None:
    with pytest.raises(ValueError, match="sub-bands"):
        ActivityCadence(
            period=CadencePeriod.day,
            times_per_period=4,
            window_start="09:00",
            window_end="10:00",
        )


def test_weekly_with_weekdays_only_on_those_days() -> None:
    activity = _recurring("g", CadencePeriod.week, weekdays=(Weekday.tuesday, Weekday.friday))
    due = _due_times(activity, _START, _END, seed=0)
    assert due
    assert all(day.weekday() in {1, 4} for day in due)


def test_weekly_without_weekdays_picks_times_per_bucket() -> None:
    activity = _recurring("l", CadencePeriod.week, times=2)
    due = _due_times(activity, _START, _END, seed=7)
    # five 7-day buckets over 31 days (last is a 3-day partial), 2 picks each.
    assert len(due) == 10


def test_biweekly_with_weekday_only_active_weeks() -> None:
    activity = _recurring("c", CadencePeriod.week, every=2, weekdays=(Weekday.monday,))
    due = _due_times(activity, _START, _END, seed=0)
    assert set(due) == {date(2026, 8, 3), date(2026, 8, 17), date(2026, 8, 31)}


def test_monthly_every_three_only_first_month() -> None:
    activity = _recurring("checkup", CadencePeriod.month, every=3)
    due = _due_times(activity, _START, _END, seed=0)
    assert len(due) == 1
    assert next(iter(due)).month == 8


def test_monthly_with_weekday_filters_candidates() -> None:
    activity = _recurring("m", CadencePeriod.month, weekdays=(Weekday.monday,))
    due = _due_times(activity, _START, _END, seed=3)
    assert due
    assert all(day.weekday() == 0 for day in due)


def test_target_time_falls_within_window() -> None:
    activity = _recurring("t", CadencePeriod.day, window=("06:00", "08:00"))
    target = _target_time(activity, _START, seed=1)
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
    # occurrences sorted by (target_time, recurring_activity_id) within each day
    for day in calendar.days:
        keys = [(item.target_time, item.recurring_activity_id) for item in day.occurrences]
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
            if item.recurring_activity_id == "morning_walk"
        }

    assert daily_dates(a) == daily_dates(b) == {day.date for day in a.days}


def test_build_calendar_rejects_zero_months() -> None:
    with pytest.raises(CadenceError):
        build_cadence_calendar(_profile(), start_date=_START, months=0, now=_NOW)


def test_add_months_clamps_end_of_month() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert add_months(date(2026, 3, 10), 6) == date(2026, 9, 10)


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
