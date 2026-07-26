"""Homeostatic drive state carried across the days of a horizon.

The cadence calendar decides *which* habits are due on a day; nothing until now decided how the
resident actually *felt* when the day started. Every day was generated in isolation from a fixed
scaffold, so the substrate woke the resident at the same minute for the whole horizon, gave the
same night length every night, and never produced a nocturnal event. A recogniser trained on that
log learns a clock, not a person.

This module adds the missing carrier. It walks the calendar in order and threads four slow
variables — sleep debt, hunger, social need and fatigue — from one day to the next, turning them
into the concrete shape of each day (bedtime, night length, wake time, naps, nocturnal bathroom
trips). Because the variables persist, the resulting variability is *autocorrelated*: a short
night makes the next morning later and a nap more likely, the way a real routine drifts and
recovers, rather than the independent per-day noise a plain random jitter would give.

The catalog already declared `resident.fatigue`, `resident.hunger`, `resident.stress` and
`resident.social_need`, but only with `scope: initial_state` — they were persona colour passed to
the LLM and validated for referential integrity, never state that evolved. This module is what
makes them dynamic.

Everything is deterministic: the same persona, seed and calendar always yield the same rhythms,
so the reproducibility contract of the generator is preserved.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

# National Sleep Foundation consensus bands, collapsed to a single nightly target per age group.
_SLEEP_NEED_BY_AGE: tuple[tuple[int, int], ...] = (
    (25, 480),
    (64, 465),
    (200, 435),
)
# Debt is capped: beyond roughly one lost night the behavioural effect saturates.
_MAX_SLEEP_DEBT_MINUTES = 480.0
# A long night pays back only part of the accumulated debt, which is what keeps it autocorrelated.
_DEBT_RECOVERY_FRACTION = 0.55
_MAX_NIGHT_VISITS = 3
# Keeps a trip clear of midnight and of the morning wake, and keeps two trips from colliding.
_NIGHT_VISIT_MARGIN_MINUTES = 25.0

# Appetite and the wish for company both build daily and are spent by doing the thing. Without a
# consumption term they only ever climb: hunger saturated in about seventeen days and social need
# in about six, after which a variable meant to shape the day became a constant.
#
# Relief is a *proportion* of what is standing, not a fixed subtraction. A fixed one only moves the
# saturation to the other end — three meals a day would drive appetite to zero and pin it there —
# whereas taking a share leaves a stable interior equilibrium that still responds to a skipped meal.
_HUNGER_SATIATION_PER_MEAL = 0.25
_SOCIAL_SATIATION_PER_CONTACT = 0.5
# Above this, the resident reaches out even though nothing was on the calendar. The unplanned
# contact is behaviour, not a habit occurrence, and the day generator labels it as such.
_UNPLANNED_SOCIAL_THRESHOLD = 0.55


@dataclass(frozen=True)
class DriveState:
    """The slow variables that survive from one day to the next."""

    sleep_debt_minutes: float = 0.0
    hunger: float = 0.0
    social_need: float = 0.0
    fatigue: float = 0.0

    def clamped(self) -> DriveState:
        return DriveState(
            sleep_debt_minutes=_clip(self.sleep_debt_minutes, 0.0, _MAX_SLEEP_DEBT_MINUTES),
            hunger=_clip(self.hunger, 0.0, 1.0),
            social_need=_clip(self.social_need, 0.0, 1.0),
            fatigue=_clip(self.fatigue, 0.0, 1.0),
        )


@dataclass(frozen=True)
class RhythmProfile:
    """Persona-level constants the drive dynamics run on."""

    persona_id: str
    age: int = 70
    # Preferred lights-out and the spread the resident actually keeps around it, in minutes.
    chronotype_bedtime_minutes: int = 22 * 60 + 30
    bedtime_sigma_minutes: float = 22.0
    wake_sigma_minutes: float = 24.0
    # Weekends and holidays drift later; social jetlag is one of the most robust routine effects.
    weekend_shift_minutes: float = 35.0
    nocturia_base_probability: float = 0.25
    nap_base_probability: float = 0.10

    @property
    def sleep_need_minutes(self) -> int:
        for ceiling, minutes in _SLEEP_NEED_BY_AGE:
            if self.age <= ceiling:
                return minutes
        return _SLEEP_NEED_BY_AGE[-1][1]

    @classmethod
    def from_persona(
        cls, persona_id: str, age: int, health: list[str] | None = None
    ) -> RhythmProfile:
        """Derive the dynamics constants from the frozen persona.

        Age drives sleep need and nocturia; the conditions the persona already carries shift the
        same two dials rather than introducing a separate disease model.
        """
        conditions = " ".join(health or []).lower()
        nocturia = 0.18 + max(0.0, (age - 55)) * 0.011
        if any(word in conditions for word in ("diabet", "prostat", "bladder", "incontinen")):
            nocturia += 0.35
        if any(word in conditions for word in ("insomni", "sleep apnoea", "sleep apnea")):
            nocturia += 0.25
        naps = 0.06 + max(0.0, (age - 60)) * 0.008
        return cls(
            persona_id=persona_id,
            age=age,
            nocturia_base_probability=_clip(nocturia, 0.0, 0.95),
            nap_base_probability=_clip(naps, 0.0, 0.6),
        )


@dataclass(frozen=True)
class DayRhythm:
    """The shape of one concrete day, derived from the drive state it started with."""

    date: str
    wake_hhmm: str
    sleep_hhmm: str
    sleep_minutes: int
    nap: bool
    # Bathroom trips inside the sleep block, as HH:MM; empty on an undisturbed night.
    night_visits: tuple[str, ...]
    state_at_start: DriveState
    meal_shift_minutes: int
    # An unscheduled reach-out, emitted when the need for company ran high and the calendar was
    # empty. Like the debt nap it is behaviour, not a habit occurrence.
    unplanned_social_contact: bool = False


def initial_state(profile: RhythmProfile, seed: int) -> DriveState:
    """Start the horizon somewhere plausible rather than at a pristine zero."""
    rng = _rng(seed, profile.persona_id, "initial-drives")
    return DriveState(
        sleep_debt_minutes=rng.uniform(0, 90),
        hunger=rng.uniform(0.1, 0.4),
        social_need=rng.uniform(0.1, 0.5),
        fatigue=rng.uniform(0.1, 0.4),
    ).clamped()


def plan_rhythms(
    profile: RhythmProfile,
    days: list[date],
    *,
    seed: int,
    rest_days: frozenset[date] = frozenset(),
    meals_by_day: Mapping[date, int] | None = None,
    social_by_day: Mapping[date, int] | None = None,
) -> dict[str, DayRhythm]:
    """Walk the horizon in order, carrying drive state, and shape every day.

    Days must be consecutive and ordered: the whole point is that day N reads the state day N-1
    left behind. ``meals_by_day`` and ``social_by_day`` carry what the calendar scheduled, so the
    corresponding drives are spent as well as accumulated; omitting them leaves both climbing.
    """
    state = initial_state(profile, seed)
    rhythms: dict[str, DayRhythm] = {}
    for day in days:
        rhythm, state = advance(
            profile,
            day,
            state,
            seed=seed,
            rest_day=day in rest_days,
            meals=0 if meals_by_day is None else meals_by_day.get(day, 0),
            social_contacts=0 if social_by_day is None else social_by_day.get(day, 0),
        )
        rhythms[day.isoformat()] = rhythm
    return rhythms


def advance(
    profile: RhythmProfile,
    day: date,
    state: DriveState,
    *,
    seed: int,
    rest_day: bool = False,
    meals: int = 0,
    social_contacts: int = 0,
) -> tuple[DayRhythm, DriveState]:
    """Turn today's incoming drive state into a day shape and tomorrow's state.

    ``meals`` and ``social_contacts`` are what the calendar actually scheduled for this day. They
    are what closes the loop: without them hunger and social need only accumulate.
    """
    key = day.isoformat()
    rng = _rng(seed, profile.persona_id, "rhythm", key)
    relaxed = rest_day or day.weekday() >= 5

    need = profile.sleep_need_minutes
    debt_pressure = state.sleep_debt_minutes / _MAX_SLEEP_DEBT_MINUTES

    # Lights out: chronotype anchor, later on a free day, earlier when sleep pressure is high.
    bedtime = (
        profile.chronotype_bedtime_minutes
        + rng.gauss(0, profile.bedtime_sigma_minutes)
        + (profile.weekend_shift_minutes if relaxed else 0.0)
        - 45.0 * debt_pressure
    )

    # Night length: log-normal so it keeps a right tail, lengthened by part of the standing debt.
    target = need + _DEBT_RECOVERY_FRACTION * state.sleep_debt_minutes
    sleep_minutes = target * math.exp(rng.gauss(0, 0.09))
    sleep_minutes = _clip(sleep_minutes, need * 0.55, need * 1.45)

    wake = bedtime + sleep_minutes + rng.gauss(0, profile.wake_sigma_minutes * 0.35)

    visits = _night_visits(profile, state, rng, wake % (24 * 60))
    # Each awakening costs some restorative sleep even when total time in bed is unchanged.
    effective_sleep = sleep_minutes - 12.0 * len(visits)

    debt = state.sleep_debt_minutes + (need - effective_sleep)
    fatigue = state.fatigue * 0.55 + 0.45 * _clip(debt / _MAX_SLEEP_DEBT_MINUTES, 0.0, 1.0)
    nap_probability = profile.nap_base_probability + 0.45 * _clip(
        debt / _MAX_SLEEP_DEBT_MINUTES, 0.0, 1.0
    )
    nap = rng.random() < nap_probability
    if nap:
        # A nap repays real debt, which is why it damps the following days rather than free noise.
        debt -= rng.uniform(20, 55)

    # Appetite builds every day and is spent at the table: a day with the usual three meals ends
    # about where it started, a day that skips one ends hungrier and shifts tomorrow's meals
    # earlier.
    hunger = (state.hunger + rng.uniform(0.20, 0.32)) * (1 - _HUNGER_SATIATION_PER_MEAL) ** meals
    hunger = _clip(hunger, 0.0, 1.0)

    # The same shape for company. A contact the calendar scheduled relieves the need; when the need
    # runs high and the calendar offers nothing, the resident reaches out anyway.
    social = (state.social_need + rng.uniform(0.05, 0.18)) * (
        1 - _SOCIAL_SATIATION_PER_CONTACT
    ) ** social_contacts
    unplanned_social = social_contacts == 0 and social >= _UNPLANNED_SOCIAL_THRESHOLD
    if unplanned_social:
        # Mirrors the debt nap: the relief is real, so it damps the following days instead of
        # letting the need sit pinned at its ceiling forever.
        social *= 1 - _SOCIAL_SATIATION_PER_CONTACT
    # Meals follow the morning: a hungry resident eats earlier, a late riser eats later. Both
    # bounded, so the day never reorders itself.
    baseline_wake = profile.chronotype_bedtime_minutes + need
    meal_shift = int(_clip(round(-28.0 * (hunger - 0.5) + 0.25 * (wake - baseline_wake)), -45, 60))

    rhythm = DayRhythm(
        date=key,
        wake_hhmm=_hhmm(wake),
        sleep_hhmm=_hhmm(bedtime),
        sleep_minutes=int(round(sleep_minutes)),
        nap=nap,
        night_visits=visits,
        state_at_start=state,
        meal_shift_minutes=meal_shift,
        unplanned_social_contact=unplanned_social,
    )
    following = DriveState(
        sleep_debt_minutes=debt,
        hunger=hunger,
        social_need=social,
        fatigue=fatigue,
    ).clamped()
    return rhythm, following


def _night_visits(
    profile: RhythmProfile,
    state: DriveState,
    rng: random.Random,
    wake_minutes_of_day: float,
) -> tuple[str, ...]:
    """Nocturnal bathroom trips: the signal missing entirely from the zone log overnight.

    Probability rises with age and health via the profile, and with accumulated fatigue: a
    fragmented sleeper stays fragmented for a run of days rather than at random.

    Times are minutes after midnight of the day that is *waking up*, because a one-day scenario
    runs [00:00, 24:00) and the resident starts it asleep in the bedroom. That also aims the
    trips squarely at the window the observable log was silent through.
    """
    latest = wake_minutes_of_day - _NIGHT_VISIT_MARGIN_MINUTES
    if latest <= _NIGHT_VISIT_MARGIN_MINUTES:
        return ()
    probability = _clip(profile.nocturia_base_probability + 0.2 * state.fatigue, 0.0, 0.98)
    if rng.random() >= probability:
        return ()
    count = 1
    while count < _MAX_NIGHT_VISITS and rng.random() < probability * 0.45:
        count += 1
    offsets = sorted(rng.uniform(_NIGHT_VISIT_MARGIN_MINUTES, latest) for _ in range(count))
    # Two trips in the same minute would collide once they become scheduled activities.
    spaced: list[float] = []
    for offset in offsets:
        floor = spaced[-1] + _NIGHT_VISIT_MARGIN_MINUTES if spaced else offset
        if floor > latest:
            break
        spaced.append(max(offset, floor))
    return tuple(_hhmm(offset) for offset in spaced)


def _rng(seed: int, *parts: object) -> random.Random:
    key = "|".join(str(part) for part in (seed, *parts))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _hhmm(total_minutes: float) -> str:
    minutes = int(round(total_minutes)) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


__all__ = [
    "DayRhythm",
    "DriveState",
    "RhythmProfile",
    "advance",
    "initial_state",
    "plan_rhythms",
]
