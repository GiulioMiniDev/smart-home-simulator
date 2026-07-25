from __future__ import annotations

import statistics
from datetime import date, timedelta

from smart_home_sim.hybrid_planning.drives import (
    DriveState,
    RhythmProfile,
    advance,
    initial_state,
    plan_rhythms,
)

HORIZON = [date(2026, 7, 24) + timedelta(days=index) for index in range(91)]


def _profile(**overrides: object) -> RhythmProfile:
    return RhythmProfile(persona_id="francesca_verdi", **overrides)  # type: ignore[arg-type]


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _lag_one_autocorrelation(series: list[float]) -> float:
    mean = statistics.mean(series)
    numerator = sum((series[i] - mean) * (series[i + 1] - mean) for i in range(len(series) - 1))
    denominator = sum((value - mean) ** 2 for value in series)
    return numerator / denominator


def test_rhythms_are_deterministic_for_a_seed() -> None:
    profile = _profile()
    assert plan_rhythms(profile, HORIZON, seed=7) == plan_rhythms(profile, HORIZON, seed=7)
    assert plan_rhythms(profile, HORIZON, seed=7) != plan_rhythms(profile, HORIZON, seed=8)


def test_wake_time_varies_instead_of_repeating_one_minute() -> None:
    """The frozen substrate woke the resident at 06:00 on all 91 days (sd = 0)."""
    rhythms = plan_rhythms(_profile(), HORIZON, seed=1)
    wake = [_minutes(item.wake_hhmm) for item in rhythms.values()]
    assert len(set(wake)) > 40
    # Broad enough to look human, tight enough to still be a routine.
    assert 15 < statistics.pstdev(wake) < 75


def test_night_length_is_right_skewed_rather_than_a_constant() -> None:
    rhythms = plan_rhythms(_profile(), HORIZON, seed=1)
    nights = [item.sleep_minutes for item in rhythms.values()]
    assert statistics.pstdev(nights) > 15
    # A log-normal night keeps a longer upper reach than lower: the mean sits above the median.
    assert statistics.mean(nights) > statistics.median(nights)


def test_sleep_debt_carries_across_days_instead_of_resetting() -> None:
    """This is the property plain per-day jitter cannot produce: yesterday still matters."""
    rhythms = plan_rhythms(_profile(), HORIZON, seed=1)
    debt = [item.state_at_start.sleep_debt_minutes for item in rhythms.values()]
    assert max(debt) > 0
    assert _lag_one_autocorrelation(debt) > 0.25


def test_a_short_night_leaves_more_debt_than_a_long_one() -> None:
    profile = _profile()
    day = date(2026, 8, 3)
    rested = DriveState(sleep_debt_minutes=0.0)
    tired = DriveState(sleep_debt_minutes=300.0)
    _, after_rested = advance(profile, day, rested, seed=1)
    _, after_tired = advance(profile, day, tired, seed=1)
    assert after_tired.sleep_debt_minutes > after_rested.sleep_debt_minutes
    # Debt is repaid only partly, so a heavy deficit survives one good night.
    assert after_tired.sleep_debt_minutes < tired.sleep_debt_minutes


def test_debt_pressure_raises_the_chance_of_a_nap() -> None:
    profile = _profile()

    def nap_rate(debt: float) -> float:
        naps = 0
        for offset, day in enumerate(HORIZON):
            rhythm, _ = advance(profile, day, DriveState(sleep_debt_minutes=debt), seed=offset)
            naps += rhythm.nap
        return naps / len(HORIZON)

    assert nap_rate(400.0) > nap_rate(0.0) + 0.15


def test_nights_produce_bathroom_trips_inside_the_sleep_block() -> None:
    """The observable log had zero events between 23:00 and 05:00: nobody got up, ever."""
    profile = _profile(age=78, nocturia_base_probability=0.6)
    rhythms = plan_rhythms(profile, HORIZON, seed=1)
    with_visits = [item for item in rhythms.values() if item.night_visits]
    assert len(with_visits) > 20
    for rhythm in with_visits:
        assert len(rhythm.night_visits) <= 3
        assert list(rhythm.night_visits) == sorted(rhythm.night_visits)
        for visit in rhythm.night_visits:
            # Trips land in the small hours, not against either edge of the night.
            assert _minutes(visit) < _minutes(rhythm.wake_hhmm)


def test_health_and_age_shift_nocturia_and_naps() -> None:
    young = RhythmProfile.from_persona("a", age=40)
    old = RhythmProfile.from_persona("b", age=80)
    diabetic = RhythmProfile.from_persona("c", age=80, health=["type 2 diabetes"])
    assert young.nocturia_base_probability < old.nocturia_base_probability
    assert old.nocturia_base_probability < diabetic.nocturia_base_probability
    assert young.nap_base_probability < old.nap_base_probability
    assert young.sleep_need_minutes > old.sleep_need_minutes


def test_initial_state_is_seeded_and_bounded() -> None:
    profile = _profile()
    assert initial_state(profile, 3) == initial_state(profile, 3)
    assert initial_state(profile, 3) != initial_state(profile, 4)
    state = initial_state(profile, 3)
    assert 0 <= state.hunger <= 1
    assert 0 <= state.fatigue <= 1
    assert state.sleep_debt_minutes >= 0


def test_drive_state_is_clamped_to_its_bands() -> None:
    clamped = DriveState(
        sleep_debt_minutes=-50, hunger=4.0, social_need=-1.0, fatigue=9.0
    ).clamped()
    assert clamped.sleep_debt_minutes == 0
    assert clamped.hunger == 1.0
    assert clamped.social_need == 0.0
    assert clamped.fatigue == 1.0
