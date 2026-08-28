"""The behavioural reading of a finished run, and the three defects it exists to catch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.domain.execution import (
    ActivityExecution,
    ExecutionTrace,
    FinalWorldState,
    MovementExecution,
    Point2D,
    ResidentFinalState,
    StateTransition,
    TraceCausality,
    TrajectoryWaypoint,
)
from smart_home_sim.simulation.behaviour import behavioural_indicators
from smart_home_sim.simulation.service import simulate_bundle

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json"
ORIGIN = datetime(2026, 10, 12, 4, 0, tzinfo=UTC)


def _at(minutes: float) -> datetime:
    return ORIGIN + timedelta(minutes=minutes)


def _activity(index: int, intent: str, start: float, end: float) -> ActivityExecution:
    return ActivityExecution(
        activity_execution_id=f"activity_{index}",
        source_activity_id=f"source_{index}",
        actor_id="resident_1",
        intent=intent,
        process_model_id="pm",
        planned_start=_at(start),
        planned_end=_at(end),
        actual_start=_at(start),
        actual_end=_at(end),
        status="completed",
    )


def _movement(index: int, origin: str, destination: str, start: float) -> MovementExecution:
    return MovementExecution(
        movement_id=f"movement_{index}",
        action_execution_id=f"action_{index}",
        actor_id="resident_1",
        started_at=_at(start),
        ended_at=_at(start + 1),
        origin_region_id=origin,
        destination_region_id=destination,
        distance_meters=4.0,
        duration_microseconds=60_000_000,
        waypoints=[
            TrajectoryWaypoint(
                at=_at(start),
                region_id=origin,
                position=Point2D(x=0.0, y=0.0),
                traversal_mode="walking",
            ),
            TrajectoryWaypoint(
                at=_at(start + 1),
                region_id=destination,
                position=Point2D(x=1.0, y=1.0),
                traversal_mode="walking",
            ),
        ],
    )


def _posture(index: int, value: str, at: float) -> StateTransition:
    return StateTransition(
        transition_id=f"state_{index}",
        at=_at(at),
        subject_type="resident",
        subject_id="resident_1",
        fact="posture",
        previous_value=None,
        value=value,
        operation="set",
        causality=TraceCausality(cause_type="action_effect", cause_id=f"action_{index}"),
    )


def _trace(**overrides) -> ExecutionTrace:
    payload = {
        "trace_id": "trace_1",
        "source_bundle_id": "bundle_1",
        "source_bundle_sha256": "0" * 64,
        "seed": 1,
        "started_at": ORIGIN,
        "ended_at": _at(1440),
        "activity_executions": [],
        "action_executions": [],
        "movements": [],
        "state_transitions": [],
        "resource_events": [],
        "runtime_events": [],
        "plan_deviations": [],
        "daily_summaries": [],
        "final_state": FinalWorldState(
            at=_at(1440),
            residents=[
                ResidentFinalState(
                    resident_id="resident_1",
                    region_id="bedroom",
                    position=Point2D(x=0.0, y=0.0),
                    posture="lying",
                    execution_state="idle",
                )
            ],
        ),
        "semantic_digest": "0" * 64,
    }
    payload.update(overrides)
    return ExecutionTrace.model_validate(payload)


def test_the_gap_between_two_activities_is_charged_to_the_room_she_is_standing_in() -> None:
    """The shower that ended at 08:31 and the two hours of bathroom that followed it."""
    trace = _trace(
        activity_executions=[
            _activity(0, "wake_up", 120, 135),
            _activity(1, "morning_toilet_and_shower", 250, 270),
            _activity(2, "read_and_rest", 406, 430),
            _activity(3, "sleep", 1000, 1400),
        ],
        movements=[
            _movement(0, "bedroom", "bathroom", 250),
            _movement(1, "bathroom", "living_room", 406),
        ],
    )

    indicators = behavioural_indicators(trace)

    assert indicators.day_count == 1
    assert indicators.idle_episode_count == 3
    assert indicators.longest_idle_minutes == pytest.approx(570.0)
    assert indicators.long_idle_episode_count == 3
    # 250 -> 270 shower, then nothing until 406: the 136 minutes in between are the bathroom's.
    assert indicators.idle_minutes_per_day_by_region["bathroom"] == pytest.approx(136.0)
    # Nothing had moved her before the first gap, so it is charged nowhere rather than guessed at.
    assert indicators.idle_minutes_per_day_by_region["unknown"] == pytest.approx(115.0)


def test_a_move_begun_lying_down_is_counted() -> None:
    trace = _trace(
        activity_executions=[_activity(0, "read_and_rest", 0, 60)],
        movements=[
            _movement(0, "living_room", "kitchen", 30),
            _movement(1, "kitchen", "living_room", 50),
            _movement(2, "living_room", "living_room", 55),
        ],
        state_transitions=[_posture(0, "lying", 10), _posture(1, "standing", 40)],
    )

    indicators = behavioural_indicators(trace)

    # The third movement never leaves the room, so it is not a move.
    assert indicators.inter_region_move_count == 2
    assert indicators.moves_from_non_ambulatory_posture == 1
    assert indicators.non_ambulatory_move_share == pytest.approx(0.5)


def test_a_night_with_no_sleep_and_a_morning_before_the_wake_are_both_reported() -> None:
    trace = _trace(
        activity_executions=[
            _activity(0, "eat_breakfast", 200, 230),
            _activity(1, "wake_up", 260, 275),
            _activity(2, "read_and_rest", 400, 460),
        ]
    )

    indicators = behavioural_indicators(trace)

    assert indicators.nights_without_sleep == 1
    assert indicators.days_with_morning_before_wake == 1


def test_the_golden_week_now_stands_up_before_it_walks() -> None:
    """The end-to-end reading. `move_to` acquired a posture precondition; this is where it shows."""
    bundle = SimulationBundle.model_validate_json(BUNDLE_PATH.read_text(encoding="utf-8"))
    indicators = behavioural_indicators(simulate_bundle(bundle).trace)

    assert indicators.inter_region_move_count > 100
    assert indicators.moves_from_non_ambulatory_posture == 0
    assert indicators.nights_without_sleep == 0
