"""What the expanded plan says has to be something that can happen where and when it says.

Three defects of the Ferri month that were in the plan rather than in the run: television evenings
placed in a kitchen with no television, a morning band declared as waking time and slept through,
and a summary page about two people that spoke of one.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from smart_home_sim.authoring.preflight import validate_habit_bands_are_not_slept_through
from smart_home_sim.hybrid_planning.day_generation import activity_from_intent
from smart_home_sim.hybrid_planning.expander import (
    FILL_LABEL,
    _seed_filler_candidates,
    expand_outline,
)
from smart_home_sim.hybrid_planning.outline import HabitComposition, HabitGroundTruth
from smart_home_sim.summary.document import _who
from tests.test_household_simulation import _outline, _package

_DAY = date(2026, 9, 1)
_ZONE = ZoneInfo("Europe/Rome")


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(_DAY.year, _DAY.month, _DAY.day, hour, minute, tzinfo=_ZONE)


def _fillers_in_a_long_wait(
    available: tuple[str, ...], shared_in: str = "kitchen", away: frozenset[str] = frozenset()
) -> list[tuple[datetime, str]]:
    """A day whose last activity before a shared dinner ends three hours before it.

    Every filler seeded into those three hours falls inside the wait for the dinner, which is what
    used to send it to the kitchen whatever it was.
    """
    tea = activity_from_intent("read_and_rest", _DAY, _at(15), "luca", index=0)
    dinner = activity_from_intent("eat_dinner", _DAY, _at(19, 30), "luca", index=1)
    dinner = dinner.model_copy(update={"participant_ids": ["marco"], "location_ids": [shared_in]})
    planned = _seed_filler_candidates(
        [tea, dinner], available, _at(8), _at(23), _DAY, "luca", seed=1, away=away
    )
    assert tea.start_window is not None and tea.duration is not None
    wait_opens = tea.start_window.preferred + timedelta(minutes=tea.duration.preferred_minutes)
    return [
        (item.start_window.preferred, item.location_ids[0])
        for item in planned
        if FILL_LABEL in item.labels
        and item.start_window is not None
        and wait_opens <= item.start_window.preferred < _at(19, 30)
    ]


def test_a_television_filler_is_not_moved_into_a_kitchen_to_wait() -> None:
    placed = _fillers_in_a_long_wait(("watch_television",))

    assert placed, "no filler fell inside the wait"
    assert {room for _, room in placed} == {"living_room"}


def test_a_phone_call_still_waits_where_the_dinner_will_be() -> None:
    placed = _fillers_in_a_long_wait(("phone_call",))

    assert placed, "no filler fell inside the wait"
    assert {room for _, room in placed} == {"kitchen"}


def test_a_phone_call_does_not_wait_outdoors_for_a_shared_outing() -> None:
    """Nothing walks a filler through the front door, so it cannot be sent out to wait."""
    placed = _fillers_in_a_long_wait(
        ("phone_call",), shared_in="outdoors", away=frozenset({"outdoors"})
    )

    assert placed, "no filler fell inside the wait"
    assert {room for _, room in placed} == {"living_room"}


def _morning_slept(share: float) -> HabitGroundTruth:
    """The fixture's planned bands, with luca's morning made `share` sleep.

    Built rather than produced by a late chronotype: what the rhythm does with one is the drive
    model's business and has its own tests. This is about the finding once a band looks like
    Paolo's did — 82% sleep in a 07:00-09:00 band declared as the start of his day.
    """
    expansion = expand_outline(_outline(), _package(), seed=1)
    truth = next(item for item in expansion.planned_bands if item.resident_id == "luca")
    habits = []
    for habit in truth.habits:
        if habit.habit_id == "morning_luca":
            minutes = habit.total_minutes
            habit = habit.model_copy(
                update={
                    "composition": [
                        HabitComposition(
                            intent="sleep",
                            location="bedroom",
                            minutes=minutes * share,
                            share=share,
                        ),
                        HabitComposition(
                            intent="eat_breakfast",
                            location="kitchen",
                            minutes=minutes * (1 - share),
                            share=round(1 - share, 4),
                        ),
                    ]
                }
            )
        habits.append(habit)
    return truth.model_copy(update={"habits": habits})


def test_a_waking_band_that_is_mostly_sleep_is_reported() -> None:
    findings = validate_habit_bands_are_not_slept_through(_morning_slept(0.82))

    assert len(findings) == 1
    assert findings[0].details["habitId"] == "morning_luca"
    assert "chronotypeBedtime" in findings[0].message


def test_a_late_morning_is_not_a_band_slept_through() -> None:
    assert validate_habit_bands_are_not_slept_through(_morning_slept(0.3)) == []


def test_the_summary_speaks_of_the_household_it_describes() -> None:
    assert _who(2).startswith("2 synthetic residents, the flat they share")
    assert _who(1).startswith("One synthetic resident, the flat she lives in")
