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
# Saturation only shows over a long run: hunger took about seventeen days to pin, social need six.
LONG_HORIZON = [date(2026, 7, 24) + timedelta(days=index) for index in range(365)]


def _routine(
    days: list[date], *, meals: int, social_weekdays: tuple[int, ...]
) -> tuple[dict[date, int], dict[date, int]]:
    """What the cadence calendar would have scheduled: meals a day, contacts on some weekdays."""
    return (
        {day: meals for day in days},
        {day: (1 if day.weekday() in social_weekdays else 0) for day in days},
    )


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


def test_hunger_and_social_need_stay_inside_their_band_over_a_year() -> None:
    """Both drives used to only accumulate, so they pinned at 1.0 and stopped being variables.

    A fixed per-meal subtraction merely moves the failure to the other end, which is why relief is
    proportional: the equilibrium has to sit strictly inside the band, not on either bound.
    """
    meals, social = _routine(LONG_HORIZON, meals=3, social_weekdays=(2, 6))
    rhythms = plan_rhythms(
        _profile(), LONG_HORIZON, seed=7, meals_by_day=meals, social_by_day=social
    )
    hunger = [item.state_at_start.hunger for item in rhythms.values()]
    need = [item.state_at_start.social_need for item in rhythms.values()]

    assert min(hunger) > 0.0 and max(hunger) < 1.0
    assert min(need) > 0.0 and max(need) < 1.0
    # A constant would also satisfy the bounds above; the point is that they keep moving.
    assert statistics.pstdev(hunger) > 0.005
    assert statistics.pstdev(need) > 0.05


def test_the_meal_shift_keeps_varying_instead_of_flattening() -> None:
    """Hunger drives the meal shift, so a saturated hunger silently froze the shift with it."""
    meals, social = _routine(LONG_HORIZON, meals=3, social_weekdays=(2, 6))
    rhythms = plan_rhythms(
        _profile(), LONG_HORIZON, seed=7, meals_by_day=meals, social_by_day=social
    )
    shifts = [item.meal_shift_minutes for item in rhythms.values()]
    assert len(set(shifts)) > 30


def test_eating_less_leaves_the_resident_hungrier() -> None:
    profile = _profile()
    fed_meals, social = _routine(HORIZON, meals=3, social_weekdays=(2,))
    lean_meals, _ = _routine(HORIZON, meals=2, social_weekdays=(2,))

    def mean_hunger(meals: dict[date, int]) -> float:
        rhythms = plan_rhythms(profile, HORIZON, seed=3, meals_by_day=meals, social_by_day=social)
        return statistics.mean(item.state_at_start.hunger for item in rhythms.values())

    assert mean_hunger(lean_meals) > mean_hunger(fed_meals) + 0.05


def test_a_scheduled_contact_relieves_the_need_for_company() -> None:
    profile = _profile()
    day = date(2026, 8, 3)
    settled = DriveState(social_need=0.2)
    _, after_none = advance(profile, day, settled, seed=1, social_contacts=0)
    _, after_one = advance(profile, day, settled, seed=1, social_contacts=1)
    assert after_one.social_need < after_none.social_need


def test_a_lonely_day_is_relieved_whether_or_not_the_calendar_planned_it() -> None:
    """Above the threshold the resident reaches out on their own, so the outcome converges.

    This is the intended behaviour rather than a coincidence: an unmet need is what triggers the
    unplanned contact, and an unplanned contact relieves exactly as much as a scheduled one.
    """
    profile = _profile()
    day = date(2026, 8, 3)
    lonely = DriveState(social_need=0.6)
    empty_day, after_none = advance(profile, day, lonely, seed=1, social_contacts=0)
    planned_day, after_one = advance(profile, day, lonely, seed=1, social_contacts=1)
    assert empty_day.unplanned_social_contact
    assert not planned_day.unplanned_social_contact
    assert after_none.social_need == after_one.social_need


def test_an_empty_calendar_makes_the_resident_reach_out_unprompted() -> None:
    """The unplanned contact is the social counterpart of the debt nap: a need with no outlet."""
    profile = _profile()
    meals, busy_social = _routine(LONG_HORIZON, meals=3, social_weekdays=(0, 2, 4, 6))
    _, empty_social = _routine(LONG_HORIZON, meals=3, social_weekdays=())

    def unplanned(social: dict[date, int]) -> int:
        rhythms = plan_rhythms(
            profile, LONG_HORIZON, seed=5, meals_by_day=meals, social_by_day=social
        )
        return sum(1 for item in rhythms.values() if item.unplanned_social_contact)

    assert unplanned(empty_social) > unplanned(busy_social)
    # A scheduled contact is a contact: it must never also trigger the unprompted one that day.
    rhythms = plan_rhythms(
        profile, LONG_HORIZON, seed=5, meals_by_day=meals, social_by_day=busy_social
    )
    for day, rhythm in rhythms.items():
        if busy_social[date.fromisoformat(day)]:
            assert not rhythm.unplanned_social_contact


def test_the_scheduled_load_does_not_break_determinism() -> None:
    profile = _profile()
    meals, social = _routine(HORIZON, meals=3, social_weekdays=(2, 6))
    first = plan_rhythms(profile, HORIZON, seed=7, meals_by_day=meals, social_by_day=social)
    second = plan_rhythms(profile, HORIZON, seed=7, meals_by_day=meals, social_by_day=social)
    assert first == second


def test_drive_state_is_clamped_to_its_bands() -> None:
    clamped = DriveState(
        sleep_debt_minutes=-50, hunger=4.0, social_need=-1.0, fatigue=9.0
    ).clamped()
    assert clamped.sleep_debt_minutes == 0
    assert clamped.hunger == 1.0
    assert clamped.social_need == 0.0
    assert clamped.fatigue == 1.0


def test_lights_out_never_crosses_midnight() -> None:
    """A late chronotype must not wrap the night into the small hours of its own day.

    Past midnight the block is emitted as the day's *first* activity, duplicating the night already
    in progress and leaving the night that day was meant to start with none at all.
    """
    profile = _profile(chronotype_bedtime_minutes=_minutes("23:45"))
    rhythms = plan_rhythms(profile, LONG_HORIZON, seed=3)
    assert rhythms
    assert max(_minutes(item.sleep_hhmm) for item in rhythms.values()) <= _minutes("23:50")


def test_a_fixed_commitment_sets_an_alarm() -> None:
    profile = _profile(chronotype_bedtime_minutes=_minutes("23:45"))
    work = _minutes("08:30")
    free = plan_rhythms(profile, HORIZON, seed=4)
    alarmed = plan_rhythms(
        profile, HORIZON, seed=4, first_commitment_by_day={day: work for day in HORIZON}
    )
    assert max(_minutes(item.wake_hhmm) for item in free.values()) > work
    assert max(_minutes(item.wake_hhmm) for item in alarmed.values()) <= work


def test_the_alarm_shortens_the_night_rather_than_moving_lights_out() -> None:
    """Cutting the night is what builds weekday debt; moving bedtime would hide the cost."""
    profile = _profile(chronotype_bedtime_minutes=_minutes("23:45"))
    day = date(2026, 8, 3)
    state = DriveState(sleep_debt_minutes=30.0)
    free, _ = advance(profile, day, state, seed=6)
    alarmed, after = advance(
        profile, day, state, seed=6, first_commitment_minutes=_minutes("08:30")
    )
    assert alarmed.sleep_hhmm == free.sleep_hhmm
    assert alarmed.sleep_minutes < free.sleep_minutes
    assert after.sleep_debt_minutes > 0
