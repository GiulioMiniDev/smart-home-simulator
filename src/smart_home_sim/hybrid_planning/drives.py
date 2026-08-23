"""Homeostatic drive state carried across the days of a horizon.

The cadence calendar decides *which* recurring activities are due on a day; nothing until now
decided how the
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
from datetime import date, timedelta

from smart_home_sim.hybrid_planning.irregularity import fold_into, stray_minutes

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

# Lights-out is measured from the midnight the evening started after, and it may pass 24:00: a
# bedtime of 1590 is 02:30 of the following morning. `DayRhythm` describes one *night*, and a night
# that begins on Monday evening belongs to Monday however far past midnight it starts.
#
# This used to be capped at 23:50 so that `_hhmm` would never wrap. The cap was guarding the wrong
# thing. Wrapping is correct — 02:30 really is the small hours — and the defect it was hiding was
# that the wrapped entry stayed on the *same* day's timeline, where it sorted ahead of that day's
# own wake and left the evening with no night at all. `build_day_plan` now hands a night that
# passes midnight to the following day, which is the day it happens on, so nothing wraps into the
# wrong list and this bound goes back to meaning what it says.
#
# What it says is a plausibility bound, not an encoding one, and the real log sets it: Aruba's
# bedtimes reach 03:34 at the 98th percentile and 04:08 at the 99th, so 04:00 is about where a late
# night stops being a late night. It matters more than it looks, because the tail is *reflected*
# into this interval rather than clamped to it — a bound set too low does not shorten the tail, it
# folds it back inside and turns it into noise. At the 03:00 this started as, widening the
# exception component moved the dispersion by less than a minute; at 04:00 the same widening is
# worth thirteen minutes of p95.
_LATEST_LIGHTS_OUT_MINUTES = 28 * 60
# The other edge. An early night is real behaviour and the wide component of the bedtime mixture
# produces them, but the fold can reflect a draw arbitrarily far down, and a resident who goes to
# bed at 18:40 has not had an early night, she has lost her evening. Late enough to leave dinner
# and the wind-down their hours.
_EARLIEST_LIGHTS_OUT_MINUTES = 20 * 60 + 30
# How long before a fixed commitment the resident is up: the wake itself, washing, breakfast and
# getting out of the door. An alarm shortens the night rather than moving lights-out, which is what
# builds weekday sleep debt and repays it at the weekend — the social-jetlag pattern.
_ALARM_LEAD_MINUTES = 90
# An alarm may cut the night, but not past the point where the resident would simply have gone to
# bed earlier instead.
_ALARM_MINIMUM_SLEEP_FRACTION = 0.45

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
# contact is behaviour, not a planned occurrence, and the day generator labels it as such.
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
    # The width of an ordinary evening, not of the whole year: `stray_minutes` adds the rare wide
    # night on top. 22 minutes was a guess and far too tidy — it kept 96% of Giulia's nights within
    # an hour of her usual bedtime where Aruba's resident keeps 60%.
    #
    # Measured on her horizon once the night was free to pass midnight, plan-level, against the
    # 85 minutes and 60% the real log shows:
    #
    # | sigma | dispersion | within an hour | p95 |
    # |------:|-----------:|---------------:|----:|
    # |    50 |     72 min |            65% | +118 |
    # |    55 |     75 min |            61% | +130 |
    # |    60 |     79 min |            57% | +143 |
    # |    65 |     83 min |            53% | +156 |
    #
    # No row reaches 85 minutes *and* 60% together, and no setting of the mixture does: the real
    # distribution has a narrower peak with heavier extremes than two folded gaussians make.
    # Matching the dispersion costs seven points of the within-an-hour share, and matching that
    # share costs ten minutes of dispersion. 60 sits between them and puts all three residents
    # inside both acceptance bands — dispersion 74-79, within an hour 57-65%.
    #
    # Widening past this stops paying: the tail is reflected back into
    # [`_EARLIEST_LIGHTS_OUT_MINUTES`, `_LATEST_LIGHTS_OUT_MINUTES`], so a draw wider than that
    # interval becomes noise inside it rather than a longer tail. Raising the exception's width
    # multiple from 3.5 to 9 moves the dispersion by less than a minute for the same reason.
    bedtime_sigma_minutes: float = 60.0
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
    # Whether lights-out falls after midnight, and so on the following day's timeline. `sleep_hhmm`
    # is already wrapped — 02:30, not 26:30 — because that is the wall-clock time it happens at;
    # this says which day's list it happens on. The wake and the night trips are always on that
    # same following day, since they come after lights-out by construction.
    sleep_starts_next_day: bool = False
    # How far tonight's lights-out sits from the one this kind of day usually gets. The evening
    # reads it the way the morning reads the wake: an early night is an early evening, not an
    # ordinary evening the night overtakes. Without it the wide component of the bedtime mixture
    # put the resident in bed at 22:01 and had her doing the washing-up at 22:32.
    bedtime_shift_minutes: int = 0
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
    first_commitment_by_day: Mapping[date, int] | None = None,
) -> dict[str, DayRhythm]:
    """Walk the horizon in order, carrying drive state, and shape every day.

    Days must be consecutive and ordered: the whole point is that day N reads the state day N-1
    left behind. ``meals_by_day`` and ``social_by_day`` carry what the calendar scheduled, so the
    corresponding drives are spent as well as accumulated; omitting them leaves both climbing.
    ``first_commitment_by_day`` carries the start of the earliest fixed commitment, in minutes after
    midnight, so the day the resident is expected somewhere gets an alarm.

    Both that map and ``rest_days`` are keyed by calendar day, which is how a caller thinks about
    them, and both are read here for the day **after** the one being shaped. A `DayRhythm` is a
    night, and a night runs from one evening into the next morning: it is tomorrow's alarm that
    cuts it short, and tomorrow's day off that lets it start late. Reading them for the same day
    put the whole effect a day early — the horizon had the resident up late on Sunday night before
    a working Monday, and in bed early on Friday.
    """
    state = initial_state(profile, seed)
    rhythms: dict[str, DayRhythm] = {}
    for day in days:
        rhythm, state = advance(
            profile,
            day,
            state,
            seed=seed,
            rest_day=day + timedelta(days=1) in rest_days,
            meals=0 if meals_by_day is None else meals_by_day.get(day, 0),
            social_contacts=0 if social_by_day is None else social_by_day.get(day, 0),
            first_commitment_minutes=(
                None
                if first_commitment_by_day is None
                else first_commitment_by_day.get(day + timedelta(days=1))
            ),
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
    first_commitment_minutes: int | None = None,
) -> tuple[DayRhythm, DriveState]:
    """Turn today's incoming drive state into a day shape and tomorrow's state.

    ``meals`` and ``social_contacts`` are what the calendar actually scheduled for this day. They
    are what closes the loop: without them hunger and social need only accumulate.

    ``first_commitment_minutes`` is when the earliest fixed commitment starts on the morning this
    night ends — tomorrow, not today. It is the one thing the resident does not choose, so it sets
    an alarm: without it the night runs to its own length and a 23:45 chronotype puts the wake at
    09:38 on a day whose shift began at 08:30, which is not a late morning but an unschedulable
    day. ``rest_day`` is read the same way, for the same reason: what makes an evening a late one
    is having nowhere to be the morning after.
    """
    key = day.isoformat()
    rng = _rng(seed, profile.persona_id, "rhythm", key)
    # `day` is the evening this night starts on, so the free day that lets it run late is the next
    # one. Callers pass `rest_day` already resolved for that day; the weekday test has to make the
    # same step itself, or Friday evening reads as a work night and Sunday evening as a free one.
    relaxed = rest_day or (day + timedelta(days=1)).weekday() >= 5

    need = profile.sleep_need_minutes
    debt_pressure = state.sleep_debt_minutes / _MAX_SLEEP_DEBT_MINUTES

    # Lights out: chronotype anchor, later on a free day, earlier when sleep pressure is high.
    bedtime = (
        profile.chronotype_bedtime_minutes
        + stray_minutes(rng, profile.bedtime_sigma_minutes)
        + (profile.weekend_shift_minutes if relaxed else 0.0)
        - 45.0 * debt_pressure
    )
    # Folded rather than clamped: see `irregularity.fold_into`.
    bedtime = fold_into(
        bedtime, float(_EARLIEST_LIGHTS_OUT_MINUTES), float(_LATEST_LIGHTS_OUT_MINUTES)
    )
    usual_bedtime = profile.chronotype_bedtime_minutes + (
        profile.weekend_shift_minutes if relaxed else 0.0
    )

    # Night length: log-normal so it keeps a right tail, lengthened by part of the standing debt.
    target = need + _DEBT_RECOVERY_FRACTION * state.sleep_debt_minutes
    sleep_minutes = target * math.exp(rng.gauss(0, 0.09))
    sleep_minutes = _clip(sleep_minutes, need * 0.55, need * 1.45)

    wake = bedtime + sleep_minutes + rng.gauss(0, profile.wake_sigma_minutes * 0.35)

    # The alarm cuts the night short rather than moving lights-out, so the minutes it takes are the
    # minutes that become tomorrow's debt.
    if first_commitment_minutes is not None:
        alarm = first_commitment_minutes - _ALARM_LEAD_MINUTES
        overshoot = min(
            wake % (24 * 60) - alarm,
            sleep_minutes - need * _ALARM_MINIMUM_SLEEP_FRACTION,
        )
        if overshoot > 0:
            wake -= overshoot
            sleep_minutes -= overshoot

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

    # Rounded once, so the string and the flag cannot disagree. Read straight off `bedtime`, a
    # draw of 1439.6 is "before midnight" while `_hhmm` rounds it to 1440 and prints 00:00 — a
    # night marked as belonging to today, timed at a moment that is tomorrow.
    lights_out = int(round(bedtime))
    rhythm = DayRhythm(
        date=key,
        wake_hhmm=_hhmm(wake),
        sleep_hhmm=_hhmm(lights_out),
        sleep_minutes=int(round(sleep_minutes)),
        sleep_starts_next_day=lights_out >= 24 * 60,
        nap=nap,
        night_visits=visits,
        state_at_start=state,
        meal_shift_minutes=meal_shift,
        bedtime_shift_minutes=int(round(bedtime - usual_bedtime)),
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
