from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from smart_home_sim.domain.environment import Point2D
from smart_home_sim.domain.execution import (
    ActivityExecution,
    ExecutionTrace,
    MovementExecution,
    TrajectoryWaypoint,
)
from smart_home_sim.profiling import (
    build_profile,
    profile_from_trace,
    profile_from_trace_file,
    render_profile_html,
    slot_labels,
    write_heatmap_csv,
)
from smart_home_sim.profiling.builder import _circular_start, _clock_gap, spread

PROJECT_ROOT = Path(__file__).parents[1]
TRACE_PATH = PROJECT_ROOT / "examples/execution/mario_week.execution-trace.json"
DIGEST = "a" * 64
# The window of every synthetic fixture opens here, so day 0 is a Monday and days 5 and 6 are the
# weekend the day-type slices have to separate.
MONDAY = datetime(2026, 7, 6, tzinfo=UTC)


def _activity(
    intent: str,
    day: int,
    start_minute: int,
    length_minutes: int,
    *,
    actor_id: str = "resident_1",
    status: str = "completed",
) -> ActivityExecution:
    start = MONDAY + timedelta(days=day, minutes=start_minute)
    end = start + timedelta(minutes=length_minutes)
    return ActivityExecution(
        activity_execution_id=f"activity_{intent}_{day}_{start_minute}",
        source_activity_id="source",
        actor_id=actor_id,
        intent=intent,
        process_model_id="process",
        planned_start=start,
        planned_end=end,
        actual_start=start,
        actual_end=end,
        status=status,
    )


def _movement(
    day: int, minute: int, origin: str, destination: str, *, actor_id: str = "resident_1"
) -> MovementExecution:
    start = MONDAY + timedelta(days=day, minutes=minute)
    return MovementExecution(
        movement_id=f"movement_{day}_{minute}_{destination}",
        action_execution_id="action",
        actor_id=actor_id,
        started_at=start,
        ended_at=start + timedelta(minutes=1),
        origin_region_id=origin,
        destination_region_id=destination,
        distance_meters=3.0,
        duration_microseconds=60_000_000,
        waypoints=[
            TrajectoryWaypoint(
                at=start,
                region_id=destination,
                position=Point2D(x=1.0, y=1.0),
                traversal_mode="walking",
            )
        ],
    )


def _profile(**overrides: object):
    arguments: dict[str, object] = {
        "trace_id": "trace_1",
        "semantic_digest": DIGEST,
        "seed": 7,
        "started_at": MONDAY,
        "ended_at": MONDAY + timedelta(days=7),
        "activities": [],
        "movements": [],
    }
    arguments.update(overrides)
    return build_profile(**arguments)  # type: ignore[arg-type]


def test_spread_cuts_an_interval_at_slot_and_midnight_boundaries() -> None:
    start = datetime(2026, 7, 6, 23, 50, tzinfo=UTC)
    pieces = list(spread(start, start + timedelta(minutes=25), 15))

    assert pieces == [
        (start.date(), 95, 10.0),
        (start.date() + timedelta(days=1), 0, 15.0),
    ]
    assert list(spread(start, start, 15)) == []


def test_slot_labels_cover_the_whole_day() -> None:
    labels = slot_labels(15)

    assert len(labels) == 96
    assert labels[0] == "00:00-00:15"
    assert labels[-1] == "23:45-00:00"


def test_circular_start_averages_across_midnight_and_refuses_a_uniform_spread() -> None:
    centre, spread_minutes = _circular_start([23 * 60 + 50, 10])

    assert centre == "00:00"
    assert spread_minutes is not None and spread_minutes > 0
    assert _circular_start([]) == (None, None)
    # Two starts exactly twelve hours apart cancel out: there is no typical hour to report.
    assert _circular_start([0, 720]) == (None, None)
    # A single occurrence is its own centre, with no spread and no negative zero.
    assert _circular_start([450]) == ("07:30", 0.0)


def test_clock_gap_takes_the_shorter_way_round() -> None:
    assert _clock_gap("07:00", "09:00") == 120
    assert _clock_gap("09:00", "07:00") == -120
    assert _clock_gap("23:30", "00:30") == 60


def test_profile_measures_occupancy_typical_hours_and_day_types() -> None:
    activities = [_activity("sleep", day, 0, 420) for day in range(7)]
    activities += [_activity("work", day, 9 * 60, 480) for day in range(5)]
    profile = _profile(activities=activities)
    resident = profile.residents[0]
    whole, weekday, weekend = resident.slices

    assert profile.day_count == 7
    assert resident.resident_id == "resident_1"
    assert resident.activity_count == 12
    assert [item.day_type for item in resident.slices] == ["all", "weekday", "weekend"]
    sleep = next(item for item in whole.intents if item.intent == "sleep")
    assert sleep.occurrences == 7
    assert sleep.typical_start == "00:00"
    assert sleep.mean_duration_minutes == 420.0
    # Every observed day opens asleep and none is awake at half past eight in the morning.
    assert sleep.occupancy_share[0] == pytest.approx(1.0)
    assert sleep.occupancy_share[32] == 0.0
    # Work never happens on a weekend, so the weekend slice knows nothing about it.
    assert {item.intent for item in weekday.intents} == {"sleep", "work"}
    assert {item.intent for item in weekend.intents} == {"sleep"}
    assert weekday.day_count == 5
    assert weekend.day_count == 2
    morning = whole.slots[4]
    assert morning.dominant_intent == "sleep"
    assert morning.entropy_bits == 0.0
    # Ten in the morning: work on the five weekdays of the seven observed, and nothing at all on
    # the two weekend days, which is exactly five sevenths of the slot.
    workday = whole.slots[40]
    assert workday.dominant_intent == "work"
    assert workday.dominant_share == pytest.approx(5 / 7)


def test_dropped_activities_are_counted_but_never_occupy_the_clock() -> None:
    profile = _profile(
        activities=[
            _activity("sleep", 0, 0, 60),
            _activity("leave_home", 0, 600, 60, status="dropped"),
        ]
    )
    resident = profile.residents[0]

    assert resident.dropped_activity_count == 1
    assert resident.activity_count == 1
    assert {item.intent for item in resident.slices[0].intents} == {"sleep"}


def test_presence_runs_from_arrival_to_the_next_departure() -> None:
    profile = _profile(
        ended_at=MONDAY + timedelta(days=1),
        movements=[_movement(0, 60, "bedroom", "kitchen"), _movement(0, 180, "kitchen", "bedroom")],
    )
    regions = {item.region_id: item for item in profile.residents[0].slices[0].regions}

    # An hour in the bedroom before the first departure, two in the kitchen, then the rest of the
    # day back in the bedroom.
    assert regions["kitchen"].total_minutes == pytest.approx(119.0)
    assert regions["bedroom"].total_minutes == pytest.approx(1319.0)
    assert regions["bedroom"].occupancy_share[0] == pytest.approx(1.0)


def test_a_run_without_movements_still_profiles_its_activities() -> None:
    profile = _profile(activities=[_activity("sleep", 0, 0, 60)])

    assert profile.residents[0].slices[0].regions == []


def test_each_resident_is_profiled_separately() -> None:
    profile = _profile(
        activities=[
            _activity("sleep", 0, 0, 60),
            _activity("cook", 0, 600, 60, actor_id="resident_2"),
        ]
    )

    assert [item.resident_id for item in profile.residents] == ["resident_1", "resident_2"]
    assert {item.intent for item in profile.residents[1].slices[0].intents} == {"cook"}


def test_narrative_describes_the_routine_and_its_weekend() -> None:
    activities = [_activity("wake_up", day, 7 * 60, 30) for day in range(5)]
    activities += [_activity("wake_up", day, 10 * 60, 30) for day in (5, 6)]
    activities += [_activity("sleep", day, 0, 400) for day in range(7)]
    narrative = _profile(activities=activities).residents[0].narrative

    assert narrative[0].startswith("14 activities over 7 observed day(s)")
    assert any("sleep: 7 of 7 day(s), around 00:00 (spread 0 min)" in line for line in narrative)
    # Averaged over both classes of day the wake-up sits between the two hours it really takes,
    # with a spread that says as much — which is why the weekend is reported separately.
    assert any("wake up: 7 of 7 day(s), around 07:50 (spread 82 min)" in line for line in narrative)
    assert any(
        "weekend moves the routine" in line and "wake up 180 min later" in line
        for line in narrative
    )
    assert any("habit bands of the day sit" in line for line in narrative)


def test_a_trace_with_no_activity_says_so_rather_than_drawing_nothing() -> None:
    profile = _profile(movements=[_movement(0, 60, "bedroom", "kitchen")])

    assert profile.residents[0].narrative == ["The trace records no activity for this resident."]
    assert profile.residents[0].slices[0].intents == []


def test_a_window_shorter_than_a_day_reports_only_the_hours_it_observed() -> None:
    profile = _profile(
        started_at=MONDAY + timedelta(hours=8),
        ended_at=MONDAY + timedelta(hours=10),
        activities=[_activity("cook", 0, 8 * 60 + 30, 30)],
    )
    whole = profile.residents[0].slices[0]

    assert whole.observed_minutes == 120.0
    assert whole.slots[0].observed_minutes == 0.0
    assert whole.slots[0].labelled_share == 0.0
    cook = whole.intents[0]
    # Half of the 08:30 slot's two observed quarter hours, not a fortieth of a whole day.
    assert cook.occupancy_share[34] == pytest.approx(1.0)


def test_build_profile_rejects_a_slot_that_does_not_divide_the_day_or_a_reversed_window() -> None:
    with pytest.raises(ValueError, match="divide the day evenly"):
        _profile(slot_minutes=7)
    with pytest.raises(ValueError, match="ends before it starts"):
        _profile(ended_at=MONDAY - timedelta(days=1))


def test_profiling_the_example_trace_keeps_shares_within_the_observed_time() -> None:
    profile = profile_from_trace_file(TRACE_PATH, run_id="run_1")
    resident = profile.residents[0]

    assert profile.run_id == "run_1"
    assert profile.slot_minutes == 15
    assert resident.resident_id == "resident_mario_rossi"
    for behaviour in resident.slices:
        for item in behaviour.intents:
            assert all(0.0 <= share <= 1.0 for share in item.occupancy_share)
        for slot in behaviour.slots:
            assert 0.0 <= slot.labelled_share <= 1.0
            assert slot.dominant_share <= slot.labelled_share + 1e-9


def test_a_window_keeps_only_the_part_of_the_trace_inside_it() -> None:
    trace = ExecutionTrace.model_validate_json(TRACE_PATH.read_text(encoding="utf-8"))
    whole = profile_from_trace(trace)
    first_day = profile_from_trace(
        trace, start=trace.started_at, end=trace.started_at + timedelta(days=1)
    )

    assert first_day.day_count < whole.day_count
    assert first_day.residents[0].activity_count < whole.residents[0].activity_count
    # A window that begins after the trace ends observes nothing, and says nothing.
    empty = profile_from_trace(trace, start=trace.ended_at + timedelta(days=1))
    assert empty.residents == []


def test_the_page_carries_the_figures_and_survives_an_empty_profile(tmp_path: Path) -> None:
    profile = profile_from_trace_file(TRACE_PATH)
    page = render_profile_html(profile)

    assert page.startswith("<!doctype html>")
    assert "http://" not in page and "<script" not in page
    assert "Resident profile" in page
    assert page.count("<svg") >= 6
    assert "resident mario rossi" in page
    assert "Weekends" in page

    empty = render_profile_html(_profile())
    assert "no resident behaviour" in empty
    single_day = render_profile_html(
        _profile(ended_at=MONDAY + timedelta(days=1), activities=[_activity("sleep", 0, 0, 60)])
    )
    assert "no day of this kind" in single_day


def test_the_matrix_is_one_row_per_series_and_one_column_per_slot(tmp_path: Path) -> None:
    profile = profile_from_trace_file(TRACE_PATH)
    path = tmp_path / "heatmap.csv"
    series = write_heatmap_csv(path, profile)

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    assert header[:4] == ["residentId", "dayType", "measure", "series"]
    assert header[4] == "00:00-00:15"
    assert len(header) == 100
    assert len(rows) - 1 == series
    assert all(len(row) == len(header) for row in rows)
    measures = {row[2] for row in rows[1:]}
    assert measures == {
        "activity_share",
        "activity_minutes",
        "activity_starts",
        "region_share",
        "slot_entropy_bits",
        "slot_labelled_share",
    }


def test_the_same_trace_profiles_to_the_same_bytes() -> None:
    """An export promises byte-identical rebuilds, and the profile is inside one.

    The document therefore carries no generation timestamp: a clock reading in the only computed
    role would make every rebuild of the same request differ from the last.
    """
    first = profile_from_trace_file(TRACE_PATH)
    second = profile_from_trace_file(TRACE_PATH)

    assert first.provenance.generated_at is None
    assert first.model_dump_json(by_alias=True) == second.model_dump_json(by_alias=True)
    assert render_profile_html(first) == render_profile_html(second)
