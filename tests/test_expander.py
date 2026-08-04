from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import (
    AuthorType,
    DayPlan,
    Location,
    LocationKind,
    Provenance,
    Resource,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.day_generation import RHYTHM_EMITTED_INTENTS
from smart_home_sim.hybrid_planning.expander import ExpansionError, expand_outline
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG
from smart_home_sim.hybrid_planning.outline import (
    ActivityDisplacement,
    ActivityOverride,
    Displacement,
    FixedCommitment,
    HorizonOutline,
    OutlineEvent,
    OutlinePhase,
    OutlineWorld,
)
from smart_home_sim.hybrid_planning.recurring_activities import (
    ActivityCadence,
    BehavioralProfile,
    CadencePeriod,
    RecurringActivity,
    RecurringActivityKind,
    Weekday,
)

_NOW = datetime(2026, 8, 2, 11, 54, tzinfo=UTC)
_START = date(2026, 8, 3)  # a Monday
# The activity catalog places every intent in one of these rooms.
_ROOMS = ("bedroom", "bathroom", "kitchen", "living_room", "balcony")


@pytest.fixture(scope="module")
def package() -> PersonalProcessPackage:
    minimal = json.loads(
        (Path(__file__).parents[1] / "examples/authoring/minimal.authoring-bundle.json").read_text(
            encoding="utf-8"
        )
    )
    payload = minimal["personalProcessPackage"]
    # The expander refuses a package that does not cover every intent the horizon will contain —
    # the declared activities plus the wake, night and state-driven extras the rhythm adds. The
    # minimal example binds two intents, so the rest are pointed at an existing model, which is
    # enough for tests that never run behaviour validation.
    template = payload["bindings"][0]
    bound = {binding["intent"] for binding in payload["bindings"]}
    needed = {spec.intent_id for spec in INTENT_CATALOG} | RHYTHM_EMITTED_INTENTS
    for intent in sorted(needed - bound):
        payload["bindings"].append(
            {**template, "bindingId": f"{template['residentId']}__{intent}", "intent": intent}
        )
    return PersonalProcessPackage.model_validate_json(json.dumps(payload))


def _recurring(
    recurring_activity_id: str,
    kind: RecurringActivityKind,
    band: tuple[str, str] = ("08:00", "10:00"),
    *,
    period: CadencePeriod = CadencePeriod.day,
    times: int = 1,
    jitter: int = 20,
    intent: str = "read_and_rest",
) -> RecurringActivity:
    return RecurringActivity(
        recurring_activity_id=recurring_activity_id,
        label=recurring_activity_id,
        kind=kind,
        intent=intent,
        cadence=ActivityCadence(
            period=period,
            times_per_period=times,
            window_start=band[0],
            window_end=band[1],
            jitter_minutes=jitter,
        ),
    )


def _profile() -> BehavioralProfile:
    recurring_activities = [
        _recurring(
            "morning_walk", RecurringActivityKind.anchor, ("07:00", "09:00"), intent="evening_walk"
        ),
        _recurring(
            "eat_breakfast",
            RecurringActivityKind.anchor,
            ("08:00", "10:00"),
            intent="eat_breakfast",
        ),
        _recurring(
            "eat_dinner", RecurringActivityKind.anchor, ("19:00", "21:00"), intent="eat_dinner"
        ),
        _recurring(
            "buy_groceries",
            RecurringActivityKind.contextual,
            ("17:00", "19:00"),
            intent="buy_groceries",
        ),
        _recurring(
            "start_laundry",
            RecurringActivityKind.contextual,
            ("15:00", "18:00"),
            intent="start_laundry",
        ),
        _recurring(
            "watch_television",
            RecurringActivityKind.optional,
            ("20:00", "22:30"),
            jitter=45,
            intent="watch_television",
        ),
        _recurring(
            "phone_a_friend",
            RecurringActivityKind.optional,
            ("18:00", "20:00"),
            intent="phone_call",
        ),
        _recurring(
            "weekly_meal_preparation",
            RecurringActivityKind.rare,
            ("11:00", "14:00"),
            period=CadencePeriod.week,
            intent="weekly_meal_preparation",
        ),
    ]
    return BehavioralProfile(
        profile_id="p1",
        persona_id="resident",
        recurring_activities=recurring_activities,
        provenance=Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    )


def _world(rooms: tuple[str, ...] = _ROOMS) -> OutlineWorld:
    return OutlineWorld(
        home_model=VersionedReference(reference_id="synthetic", version="1.0.0"),
        locations=[
            *(Location(location_id=room, kind=LocationKind.room) for room in rooms),
            Location(location_id="outdoors", kind=LocationKind.external),
        ],
        resources=[Resource(resource_id="stove", resource_type="appliance", location_id=rooms[0])],
        start_location_id=rooms[0],
    )


def _outline(**overrides: Any) -> HorizonOutline:
    fields: dict[str, Any] = {
        "outline_id": "o1",
        "title": "One month",
        "resident_id": "resident",
        "time_zone": "America/New_York",
        "start_date": _START,
        "months": 1,
        "world": _world(),
        "profile": _profile(),
        "provenance": Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    }
    fields.update(overrides)
    return HorizonOutline(**fields)


def _intents_on(day: DayPlan) -> list[str]:
    return [activity.intent for activity in day.activities]


def _habit_ids_on(day: DayPlan) -> set[str]:
    return {
        label.removeprefix("activity:")
        for activity in day.activities
        for label in activity.labels
        if label.startswith("activity:")
    }


def _signature(day: DayPlan) -> tuple[tuple[str, str, float], ...]:
    return tuple(
        (
            activity.intent,
            activity.start_window.preferred.strftime("%H:%M:%S"),
            activity.duration.preferred_minutes,
        )
        for activity in day.activities
        if activity.start_window is not None and activity.duration is not None
    )


def test_every_day_of_the_horizon_is_different(package: PersonalProcessPackage) -> None:
    """The property the whole decision exists for: 0.03 on the authored bundle, 1.00 here."""
    result = expand_outline(_outline(), package, seed=1)

    days = result.bundle.scenario.days
    assert len({_signature(day) for day in days}) == len(days)


def test_the_same_seed_reproduces_the_bundle(package: PersonalProcessPackage) -> None:
    outline = _outline()

    first = expand_outline(outline, package, seed=1).bundle.model_dump_json(by_alias=True)
    again = expand_outline(outline, package, seed=1).bundle.model_dump_json(by_alias=True)
    other = expand_outline(outline, package, seed=2).bundle.model_dump_json(by_alias=True)

    assert first == again
    assert first != other


def test_a_suspended_habit_disappears_only_inside_its_phase(
    package: PersonalProcessPackage,
) -> None:
    phase = OutlinePhase(
        phase_id="away",
        label="Away",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 16),
        activity_overrides=[ActivityOverride(recurring_activity_id="morning_walk", suspended=True)],
    )

    days = {
        day.date: day
        for day in expand_outline(_outline(phases=[phase]), package, seed=1).bundle.scenario.days
    }

    assert "morning_walk" not in _habit_ids_on(days[date(2026, 8, 12)])
    assert "morning_walk" in _habit_ids_on(days[date(2026, 8, 5)])
    assert "morning_walk" in _habit_ids_on(days[date(2026, 8, 20)])


def test_a_replaced_cadence_thins_the_habit_inside_its_phase(
    package: PersonalProcessPackage,
) -> None:
    """A daily activity dropped to twice a week must occur less often, and only in the phase."""
    phase = OutlinePhase(
        phase_id="winter",
        label="Winter",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 23),
        activity_overrides=[
            ActivityOverride(
                recurring_activity_id="morning_walk",
                cadence=ActivityCadence(
                    period=CadencePeriod.week,
                    times_per_period=2,
                    window_start="07:00",
                    window_end="09:00",
                ),
            )
        ],
    )
    days = {
        day.date: day
        for day in expand_outline(_outline(phases=[phase]), package, seed=1).bundle.scenario.days
    }

    inside = sum("morning_walk" in _habit_ids_on(days[date(2026, 8, day)]) for day in range(10, 24))
    outside = sum("morning_walk" in _habit_ids_on(days[date(2026, 8, day)]) for day in range(3, 10))

    assert inside < 14
    assert outside == 7


def test_a_skipped_habit_is_gone_from_the_event_day(package: PersonalProcessPackage) -> None:
    event = OutlineEvent(
        event_id="trip",
        label="Weekly meal preparation",
        earliest_date=date(2026, 8, 12),
        latest_date=date(2026, 8, 12),
        window_start="09:00",
        window_end="18:00",
        minimum_minutes=120,
        maximum_minutes=240,
        displaces=[ActivityDisplacement(recurring_activity_id="eat_dinner")],
    )
    result = expand_outline(_outline(events=[event]), package, seed=1)
    days = {day.date: day for day in result.bundle.scenario.days}

    assert "eat_dinner" not in _habit_ids_on(days[date(2026, 8, 12)])
    assert result.skipped_occurrences == 1
    assert result.rescheduled_occurrences == 0


def test_a_rescheduled_habit_moves_to_a_later_day(package: PersonalProcessPackage) -> None:
    event = OutlineEvent(
        event_id="trip",
        label="Weekly meal preparation",
        earliest_date=date(2026, 8, 12),
        latest_date=date(2026, 8, 12),
        window_start="09:00",
        window_end="18:00",
        minimum_minutes=120,
        maximum_minutes=240,
        displaces=[
            ActivityDisplacement(
                recurring_activity_id="buy_groceries", policy=Displacement.reschedule
            )
        ],
    )
    result = expand_outline(_outline(events=[event]), package, seed=1)

    assert result.rescheduled_occurrences + result.dropped_occurrences >= 1
    assert result.skipped_occurrences == 0


def test_an_event_lands_inside_its_declared_window(package: PersonalProcessPackage) -> None:
    event = OutlineEvent(
        event_id="checkup",
        label="Weekly meal preparation",
        earliest_date=date(2026, 8, 10),
        latest_date=date(2026, 8, 14),
        window_start="10:00",
        window_end="16:00",
        minimum_minutes=60,
        maximum_minutes=90,
    )
    result = expand_outline(_outline(events=[event]), package, seed=1)

    placed = [
        (day.date, activity)
        for day in result.bundle.scenario.days
        for activity in day.activities
        if "event:checkup" in activity.labels
    ]

    assert len(placed) == 1
    day_date, activity = placed[0]
    assert date(2026, 8, 10) <= day_date <= date(2026, 8, 14)
    assert 10 <= activity.start_window.preferred.hour < 16  # type: ignore[union-attr]


def test_windows_come_from_the_declared_band_not_one_constant(
    package: PersonalProcessPackage,
) -> None:
    """The authored bundle gave all 3 870 activities 12 minutes.

    A declared band is the author's statement that anywhere inside it is acceptable, which is
    exactly the room the placement engine needs.
    """
    result = expand_outline(_outline(), package, seed=1)

    widths = {
        int((activity.start_window.latest - activity.start_window.earliest).total_seconds() // 60)
        for day in result.bundle.scenario.days
        for activity in day.activities
        if activity.start_window is not None
    }

    assert len(widths) > 1
    assert max(widths) >= 120


def test_the_waking_day_never_asks_to_be_in_two_places_at_once(
    package: PersonalProcessPackage,
) -> None:
    """Coherent preferred times are what keep the compiler confirming instead of repairing.

    Scoped to the waking day. The terminal sleep is anchored by the drive model, not by a band,
    so an evening habit whose own band runs up to bedtime can still collide with it — and that
    collision is genuine work for the compiler, which can shorten either within its declared
    duration range. What the expander owes is a day that does not manufacture conflicts of its
    own; resolving the real ones is the placement engine's job.
    """
    result = expand_outline(_outline(), package, seed=1)

    pairs = 0
    overlapping = 0
    for day in result.bundle.scenario.days:
        timed = sorted(
            (
                item
                for item in day.activities
                if item.start_window and item.duration and item.intent != "sleep"
            ),
            key=lambda item: item.start_window.preferred,  # type: ignore[union-attr]
        )
        for earlier, later in zip(timed, timed[1:], strict=False):
            ends = earlier.start_window.preferred + timedelta(  # type: ignore[union-attr]
                minutes=earlier.duration.preferred_minutes  # type: ignore[union-attr]
            )
            pairs += 1
            overlapping += ends > later.start_window.preferred  # type: ignore[union-attr]

    # Without the pass the rate sits around a fifth of all pairs, which is what made the compiler
    # reject and re-place 18% of every preferred value on the reference horizon.
    assert overlapping / pairs < 0.05


def test_a_world_missing_a_catalog_room_fails_once_and_clearly(
    package: PersonalProcessPackage,
) -> None:
    """Without this the mismatch surfaces as one error per activity — 1 784 on the reference."""
    outline = _outline(world=_world(("bedroom", "kitchen", "living_room", "balcony", "hallway")))

    with pytest.raises(ExpansionError, match="bathroom"):
        expand_outline(outline, package, seed=1)


def test_the_horizon_covers_every_day_exactly_once(package: PersonalProcessPackage) -> None:
    outline = _outline()

    result = expand_outline(outline, package, seed=1)

    dates = [day.date for day in result.bundle.scenario.days]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)
    assert dates[0] == outline.start_date
    assert result.day_count == (outline.end_date - outline.start_date).days


def test_a_package_missing_the_rhythm_intents_is_refused_once(
    package: PersonalProcessPackage,
) -> None:
    """The days contain more than the outline declares, and the package has to cover the rest.

    The rhythm always adds a wake and a night, and adds a nap, a nocturnal trip or an unplanned
    call when the drive state calls for one. A package written only against the declared
    activities leaves those pointing at behaviour nobody authored — ingestion reports that once
    per activity, which on the first real eight-month case was 628 errors for five missing models.
    """
    stripped = package.model_copy(
        update={
            "bindings": [
                binding
                for binding in package.bindings
                if binding.intent not in RHYTHM_EMITTED_INTENTS
            ]
        }
    )

    with pytest.raises(ExpansionError, match="the rhythm emits these intents on its own"):
        expand_outline(_outline(), stripped, seed=1)


def test_windows_stay_ordered_across_a_spring_forward_transition(
    package: PersonalProcessPackage,
) -> None:
    """A window built by wall-clock arithmetic inverts itself on the day the clocks jump.

    Europe/Rome moves 02:00 to 03:00 on 2027-03-28, so a nocturnal trip at 03:01 gets an earliest
    edge of 02:46 — a local time that never happens, which ZoneInfo resolves with the offset from
    *before* the jump. The edge then sits 45 minutes after the moment it is supposed to precede,
    and the whole eight-month bundle is rejected for one day of it.
    """
    # 02:50 is inside the hour Europe/Rome skips, which is what makes the edges disagree: the
    # earliest lands in the gap too and keeps the old offset, the latest clears it and takes the
    # new one, so the window closes 45 minutes before it opens.
    commitment = FixedCommitment(
        commitment_id="night_shift",
        label="Night shift",
        weekdays=[Weekday.sunday],
        start_time="02:50",
        end_time="06:00",
        intent="work_shift",
    )
    # An absence needs an away intent, and the shared fixture only binds the home catalog.
    template = package.bindings[0]
    covering = package.model_copy(
        update={
            "bindings": [
                *package.bindings,
                template.model_copy(
                    update={"binding_id": "away__work_shift", "intent": "work_shift"}
                ),
            ]
        }
    )
    result = expand_outline(
        _outline(
            time_zone="Europe/Rome",
            start_date=date(2027, 3, 1),
            months=1,
            fixed_commitments=[commitment],
        ),
        covering,
        seed=1,
    )

    transition = [day for day in result.bundle.scenario.days if day.date == date(2027, 3, 28)]
    assert transition, "the horizon must cover the transition day"

    # Compared as instants, deliberately. Two aware datetimes that share a tzinfo object are
    # compared on their naive fields with the offset ignored, so an inverted window looks ordered
    # in memory and `DateTimeWindow` accepts it; the contradiction only surfaces once the bundle
    # has been through JSON and the edges carry fixed offsets instead. Asserting on the local
    # values here would reproduce the same blind spot that let this reach an eight-month import.
    inverted = [
        activity.activity_id
        for day in result.bundle.scenario.days
        for activity in day.activities
        if activity.start_window is not None
        and not (
            activity.start_window.earliest.astimezone(UTC)
            <= activity.start_window.preferred.astimezone(UTC)
            <= activity.start_window.latest.astimezone(UTC)
        )
    ]

    assert inverted == []
