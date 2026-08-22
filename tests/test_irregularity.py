from __future__ import annotations

import random
import statistics
from datetime import date, timedelta

from smart_home_sim.hybrid_planning.drives import RhythmProfile, plan_rhythms
from smart_home_sim.hybrid_planning.irregularity import (
    EXCEPTION_PROBABILITY,
    EXCEPTION_WIDTH_MULTIPLE,
    fold_into,
    stray_minutes,
)

HORIZON = [date(2026, 7, 24) + timedelta(days=index) for index in range(365)]


def _draws(typical: float, count: int = 20_000) -> list[float]:
    rng = random.Random(11)
    return [stray_minutes(rng, typical) for _ in range(count)]


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def test_a_declared_width_of_zero_never_strays() -> None:
    rng = random.Random(1)
    assert all(stray_minutes(rng, width) == 0.0 for width in (0.0, -5.0))


def test_the_body_keeps_the_declared_width_and_the_tail_reaches_past_it() -> None:
    """The point of the mixture: ordinary days unchanged, and a few days nothing like them.

    A uniform inside ±jitter cannot do the second half at all, which is why widening the declared
    `jitter_minutes` was not the fix. Here the common component still describes the ordinary
    occurrence, and the rare one reaches several times further.
    """
    draws = _draws(30.0)
    body = [value for value in draws if abs(value) <= 3 * 30.0]
    assert 25 < statistics.pstdev(body) < 40
    # The mixture's standard deviation is sqrt(1 - p + p * k**2) times the body's.
    spread = 1 - EXCEPTION_PROBABILITY + EXCEPTION_PROBABILITY * EXCEPTION_WIDTH_MULTIPLE**2
    expected = 30.0 * spread**0.5
    assert abs(statistics.pstdev(draws) - expected) < 4
    assert max(abs(value) for value in draws) > 6 * 30.0


def test_the_draw_is_centred_so_a_habit_is_not_walked_off_its_hour() -> None:
    assert abs(statistics.mean(_draws(45.0))) < 4


def test_folding_reflects_instead_of_piling_up_on_an_edge() -> None:
    assert fold_into(10.0, 0.0, 100.0) == 10.0
    assert fold_into(120.0, 0.0, 100.0) == 80.0
    assert fold_into(-30.0, 0.0, 100.0) == 30.0
    # Repeated reflection: a tail several times wider than the interval still lands inside it.
    assert all(0.0 <= fold_into(float(value), 0.0, 100.0) <= 100.0 for value in range(-900, 900))
    # A degenerate interval has one answer, and it is not a crash.
    assert fold_into(50.0, 20.0, 20.0) == 20.0


def test_folding_leaves_no_single_minute_carrying_the_whole_edge() -> None:
    """Clamping put 109 of Giulia's 365 nights on 23:50 exactly. That number, generalised."""
    rng = random.Random(5)
    values = [fold_into(rng.gauss(80, 40), 0.0, 100.0) for _ in range(4000)]
    buckets: dict[int, int] = {}
    for value in values:
        buckets[int(value)] = buckets.get(int(value), 0) + 1
    assert max(buckets.values()) / len(values) < 0.05


def test_lights_out_no_longer_repeats_one_minute_for_a_late_chronotype() -> None:
    """Clamping a late chronotype against the old 23:50 ceiling made a spike out of it.

    Giulia's outline declares 23:30, which left twenty minutes of room: 109 of 365 nights landed on
    the same minute. Both halves of the repair show up here — the draw is a mixture rather than a
    clamped uniform, and a night that reaches past midnight now belongs to the day it happens on
    instead of being pushed back under a ceiling.
    """
    profile = RhythmProfile(persona_id="giulia_ferri", chronotype_bedtime_minutes=_minutes("23:30"))
    rhythms = plan_rhythms(profile, HORIZON, seed=1)
    # Measured on a line that keeps running past midnight, so 00:20 reads as later than 23:40
    # rather than as the earliest night of the year.
    bedtimes = [
        _minutes(item.sleep_hhmm) + (24 * 60 if item.sleep_starts_next_day else 0)
        for item in rhythms.values()
    ]

    busiest = max(bedtimes.count(value) for value in set(bedtimes))
    assert busiest / len(bedtimes) < 0.05
    # And it is a spread, not just a scatter of ties: the old distribution spanned 82 minutes.
    assert max(bedtimes) - min(bedtimes) > 150
    # The spread is no longer bought entirely on the early side, which is what the ceiling forced.
    assert max(bedtimes) > 24 * 60
