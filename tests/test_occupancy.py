from __future__ import annotations

from datetime import UTC, datetime, timedelta

from smart_home_sim.domain.environment import Point2D, Polygon2D
from smart_home_sim.environment.occupancy import berth_for, berths
from smart_home_sim.sensors.service import _resting_at


def rectangle(min_x: float, min_y: float, max_x: float, max_y: float) -> Polygon2D:
    return Polygon2D(
        vertices=[
            Point2D(x=min_x, y=min_y),
            Point2D(x=max_x, y=min_y),
            Point2D(x=max_x, y=max_y),
            Point2D(x=min_x, y=max_y),
        ]
    )


def test_a_double_bed_sleeps_two_and_says_which_side_each_of_them_is_on() -> None:
    """The question a home with more than one resident is for.

    A body lies along the length of a bed, so two of them lie side by side across its width: it is
    the short side that is divided. One berth would put both of them on the same coordinate, which
    is not an answer to `who is where`.
    """
    double = rectangle(0, 0, 2.0, 1.6)
    places = berths(double, lying=True)

    assert len(places) == 2
    # Across the 1.6 m width, not along the 2 m length, and symmetric about the middle.
    assert [item.x for item in places] == [1.0, 1.0]
    assert [item.y for item in places] == [0.4, 1.2]
    assert berth_for(double, lying=True, occupant=0) == places[0]
    assert berth_for(double, lying=True, occupant=1) == places[1]
    # A fourth body on a three-seat sofa is a crowded sofa, not a simulation that stops.
    assert berth_for(double, lying=True, occupant=2) == places[0]


def test_a_single_sleeper_and_a_chair_get_the_middle_of_the_thing() -> None:
    single = rectangle(0, 0, 2.0, 0.9)
    assert berths(single, lying=True) == [Point2D(x=1.0, y=0.45)]
    # Small enough that the arithmetic would allow two and reality would not.
    chair = rectangle(0, 0, 0.45, 0.45)
    assert berths(chair, lying=False) == [Point2D(x=0.225, y=0.225)]


def test_seats_are_ranged_along_the_piece_and_beds_across_it() -> None:
    """The same footprint divides differently depending on what the bodies are doing on it.

    Sitting takes almost no depth, so people sit shoulder to shoulder along the long side. Lying
    takes the whole length, so they lie side by side across the short one. A sofa is both.
    """
    sofa = rectangle(0, 0, 2.0, 0.85)

    seated = berths(sofa, lying=False)
    assert len(seated) == 3
    assert [item.y for item in seated] == [0.425, 0.425, 0.425]
    assert [item.x for item in seated] == [0.3333, 1.0, 1.6667]

    # Nobody lies across a sofa: at 0.85 m the short side holds one body.
    assert berths(sofa, lying=True) == [Point2D(x=1.0, y=0.425)]


def test_every_berth_is_inside_the_piece_it_belongs_to() -> None:
    for box in (rectangle(3, 1, 5.4, 3.1), rectangle(-2, -2, -0.5, 0), rectangle(0, 0, 4, 4)):
        for lying in (True, False):
            xs = [vertex.x for vertex in box.vertices]
            ys = [vertex.y for vertex in box.vertices]
            for place in berths(box, lying=lying):
                assert min(xs) <= place.x <= max(xs)
                assert min(ys) <= place.y <= max(ys)


def test_a_berth_only_speaks_for_the_room_it_is_in() -> None:
    """The guard that caught the bug this pair of functions was written with.

    Only standing up clears a berth, and standing up does not happen on every path a body can take
    out of a room. A stale one projected a resident in the bathroom from the sofa she had been
    sitting on — a point the bathroom's own detector cannot see — and observations went missing
    from a room with no seat in it. The room is checked rather than assumed.
    """
    start = datetime(2026, 10, 30, 7, 0, tzinfo=UTC)
    sofa = Point2D(x=1.1, y=6.6)
    floor = Point2D(x=19.0, y=5.0)
    series = [
        (start, (sofa, "living_room")),
        (start + timedelta(hours=2), None),
    ]

    # On the sofa, in the living room: the berth is the answer.
    assert _resting_at(series, start + timedelta(minutes=30), floor, "living_room") == sofa
    # The same berth still in force, but the pulse is in the bathroom: it says nothing about there.
    assert _resting_at(series, start + timedelta(minutes=30), floor, "bathroom") == floor
    # Before anything was recorded, and after she got up.
    assert _resting_at(series, start - timedelta(minutes=1), floor, "living_room") == floor
    assert _resting_at(series, start + timedelta(hours=3), floor, "living_room") == floor
    assert _resting_at([], start, floor, "living_room") == floor


def test_a_berth_is_let_go_the_moment_the_posture_that_held_it_ends() -> None:
    """The rule, stated where the engine states it.

    `_stand_up` used to be the only thing that cleared a berth, and it does not run on every way a
    body can end up upright: a plan ending in `change_posture{standing}` sets the posture through
    the catalogue effect, and the resident then carried the sofa into the next room with her. A
    berth belongs to the posture that holds it, so it goes when the posture goes.
    """
    from smart_home_sim.simulation.service import (
        _RECLINING_POSTURE,
        _SITTING_POSTURE,
        _STANDING_POSTURE,
        ResidentRuntime,
        SimulationEngine,
    )

    recorded: list[Point2D | None] = []
    actor = ResidentRuntime(
        resident_id="resident_mario_rossi",
        region_id="living_room",
        position=Point2D(x=0.4, y=6.0),
        posture=_SITTING_POSTURE,
        resting_at=Point2D(x=1.1, y=6.6),
    )
    engine = object.__new__(SimulationEngine)
    engine._record_berth = lambda runtime, target, action_id: recorded.append(target)  # type: ignore[method-assign]

    # Still sitting: she is still on it.
    SimulationEngine._release_berth(engine, actor, "action")
    assert recorded == []

    # Lying is a resting posture too — moving between the two does not put her on the floor.
    actor.posture = _RECLINING_POSTURE
    SimulationEngine._release_berth(engine, actor, "action")
    assert recorded == []

    # Upright: the berth goes, whichever route the posture took to get here.
    actor.posture = _STANDING_POSTURE
    SimulationEngine._release_berth(engine, actor, "action")
    assert recorded == [None]
