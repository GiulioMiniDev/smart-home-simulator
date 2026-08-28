"""Behavioural indicators for a finished run — is this a person, or a plan being read out?

`validate_execution_trace` answers whether a trace is *well formed*: ids resolve, states close,
every action belongs to an activity. It says nothing about whether the day it describes is one a
person could have had, and four generated years went by before anyone asked. What that cost is on
record: a resident who showered and then stood in the bathroom for two hours and sixteen minutes
because nothing was scheduled next, 402 such minutes a day, and 22.7% of the sensor log emitted by
a body holding still.

Nothing here fails a run. These are readings, and a run is entitled to bad ones — a horizon of
anchors with no filler behaviour genuinely leaves the resident with nothing to do. The point is
that the reading exists, and that the next export can be compared with the last one instead of
being audited by hand.

Everything is computed from the execution trace alone: no sensor log, no bundle, no scenario.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from smart_home_sim.domain.execution import ExecutionTrace

# Postures a resident can cross a room in. The engine makes her stand up first; a move that still
# starts from `lying` means something bypassed that, and is worth seeing.
AMBULATORY_POSTURES = frozenset({"standing", "walking"})
# The waking day is taken to start here: a `sleep` that begins before it belongs to the night that
# is ending, not to the one this day is heading into. Same convention `_lights_out` uses upstream.
LOGICAL_DAY_START_HOUR = 4
# What counts as a long stretch of nothing. Not a threshold anything is judged against — just the
# bucket the report counts, chosen because an hour is longer than any single activity in the
# vocabulary.
LONG_IDLE_MINUTES = 60
# The intents that only make sense after the resident is awake. A day where one of these precedes
# `wake_up` is a day whose order broke.
MORNING_INTENTS = frozenset(
    {
        "eat_breakfast",
        "morning_toilet_and_shower",
        "morning_toilet_and_wash",
        "prepare_and_drink_hot_drink",
        "take_morning_medication",
        "work_from_home",
    }
)


@dataclass(frozen=True)
class BehaviouralIndicators:
    """One reading per defect the behavioural audit of August 2026 found."""

    day_count: int
    idle_minutes_per_day: float
    idle_episode_count: int
    longest_idle_minutes: float
    long_idle_episode_count: int
    idle_minutes_per_day_by_region: dict[str, float] = field(default_factory=dict)
    inter_region_move_count: int = 0
    moves_from_non_ambulatory_posture: int = 0
    nights_without_sleep: int = 0
    days_with_morning_before_wake: int = 0

    @property
    def non_ambulatory_move_share(self) -> float:
        if not self.inter_region_move_count:
            return 0.0
        return self.moves_from_non_ambulatory_posture / self.inter_region_move_count

    def as_lines(self) -> list[str]:
        """The report a person reads, one indicator per line."""
        regions = ", ".join(
            f"{region} {minutes:.0f}"
            for region, minutes in sorted(
                self.idle_minutes_per_day_by_region.items(), key=lambda item: -item[1]
            )
        )
        rows = [
            ("days", f"{self.day_count}"),
            ("idle minutes per day", f"{self.idle_minutes_per_day:.0f}"),
            ("idle episodes", f"{self.idle_episode_count}"),
            (
                f"idle episodes over {LONG_IDLE_MINUTES} minutes",
                f"{self.long_idle_episode_count}",
            ),
            ("longest idle episode (minutes)", f"{self.longest_idle_minutes:.0f}"),
            ("idle minutes per day, by region", regions or "-"),
            ("inter-region moves", f"{self.inter_region_move_count}"),
            (
                "moves begun sitting or lying",
                f"{self.moves_from_non_ambulatory_posture}"
                f" ({self.non_ambulatory_move_share:.1%})",
            ),
            ("nights with no sleep", f"{self.nights_without_sleep}"),
            ("days with a morning before the wake", f"{self.days_with_morning_before_wake}"),
        ]
        width = max(len(label) for label, _ in rows)
        return [f"{label.ljust(width)}  {value}" for label, value in rows]


def _logical_day(moment: datetime) -> object:
    return (moment - timedelta(hours=LOGICAL_DAY_START_HOUR)).date()


def _idle_spans(trace: ExecutionTrace) -> list[tuple[datetime, datetime]]:
    """The gaps between activities, with overlapping activities merged first.

    Merging matters: nested activities — the nocturnal bathroom trip runs inside the night — would
    otherwise open a gap that never existed.
    """
    intervals = sorted(
        (item.actual_start, item.actual_end)
        for item in trace.activity_executions
        if item.actual_end > item.actual_start
    )
    spans: list[tuple[datetime, datetime]] = []
    if not intervals:
        return spans
    frontier = intervals[0][1]
    for start, end in intervals[1:]:
        if start > frontier:
            spans.append((frontier, start))
        frontier = max(frontier, end)
    return spans


def _region_at(trace: ExecutionTrace) -> tuple[list[datetime], list[str]]:
    """Where the resident is over time, read off the movements she has finished."""
    arrivals = sorted(
        (item.ended_at, item.destination_region_id) for item in trace.movements
    )
    return [item[0] for item in arrivals], [item[1] for item in arrivals]


def behavioural_indicators(trace: ExecutionTrace) -> BehaviouralIndicators:
    """Read the six indicators off one finished run."""
    spans = _idle_spans(trace)
    idle_minutes = [(end - start).total_seconds() / 60 for start, end in spans]
    arrival_times, arrival_regions = _region_at(trace)
    by_region: dict[str, float] = defaultdict(float)
    for (start, _), minutes in zip(spans, idle_minutes, strict=True):
        index = bisect.bisect_right(arrival_times, start) - 1
        by_region[arrival_regions[index] if index >= 0 else "unknown"] += minutes

    postures = sorted(
        (item.at, str(item.value))
        for item in trace.state_transitions
        if item.subject_type == "resident" and item.fact == "posture"
    )
    posture_times = [item[0] for item in postures]
    moves = 0
    non_ambulatory = 0
    for movement in trace.movements:
        if movement.origin_region_id == movement.destination_region_id:
            continue
        moves += 1
        index = bisect.bisect_right(posture_times, movement.started_at) - 1
        if index >= 0 and postures[index][1] not in AMBULATORY_POSTURES:
            non_ambulatory += 1

    by_day: dict[object, list[tuple[datetime, str]]] = defaultdict(list)
    for activity in trace.activity_executions:
        by_day[_logical_day(activity.actual_start)].append((activity.actual_start, activity.intent))
    sleepless = 0
    out_of_order = 0
    for entries in by_day.values():
        intents = [intent for _, intent in sorted(entries)]
        if "sleep" not in intents:
            sleepless += 1
        if "wake_up" in intents:
            before = intents[: intents.index("wake_up")]
            if any(intent in MORNING_INTENTS for intent in before):
                out_of_order += 1

    days = max(1, len(by_day))
    return BehaviouralIndicators(
        day_count=len(by_day),
        idle_minutes_per_day=sum(idle_minutes) / days,
        idle_episode_count=len(idle_minutes),
        longest_idle_minutes=max(idle_minutes, default=0.0),
        long_idle_episode_count=sum(1 for value in idle_minutes if value > LONG_IDLE_MINUTES),
        idle_minutes_per_day_by_region={
            region: minutes / days for region, minutes in by_region.items()
        },
        inter_region_move_count=moves,
        moves_from_non_ambulatory_posture=non_ambulatory,
        nights_without_sleep=sleepless,
        days_with_morning_before_wake=out_of_order,
    )


__all__ = ["BehaviouralIndicators", "behavioural_indicators"]
