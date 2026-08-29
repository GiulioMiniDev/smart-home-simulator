from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import (
    Activity,
    AuthorType,
    DateTimeWindow,
    DayContext,
    DayPlan,
    DurationRange,
    Location,
    LocationKind,
    Provenance,
    Resource,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.day_generation import (
    EVENING_CLEARANCE_MINUTES,
    RHYTHM_EMITTED_INTENTS,
    WAKE_CLEARANCE_MINUTES,
)
from smart_home_sim.hybrid_planning.expander import (
    MINIMUM_FLEX_MINUTES,
    ExpansionError,
    _measure_habits,
    expand_outline,
)
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG
from smart_home_sim.hybrid_planning.outline import (
    ActivityDisplacement,
    ActivityOverride,
    Displacement,
    FixedCommitment,
    HabitGroundTruth,
    HabitSegment,
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


def test_a_working_day_at_home_expands_into_blocks_on_working_days_only(
    package: PersonalProcessPackage,
) -> None:
    """The case the whole `work_from_home` intent exists for.

    Declared as one daily activity with four occurrences on monday-to-friday, the working day
    arrives as four separate blocks in the living room, and the weekend has none of them. Before
    this, the same declaration produced one block a day, seven days a week, or — as every authored
    horizon actually did — nothing at all, because the only work intent available sent the resident
    out of the front door.
    """
    profile = _profile()
    working = _recurring(
        "freelance_work",
        RecurringActivityKind.anchor,
        ("09:00", "18:00"),
        times=4,
        jitter=20,
        intent="work_from_home",
    )
    working = working.model_copy(
        update={
            "cadence": working.cadence.model_copy(
                update={
                    "weekdays": [
                        Weekday.monday,
                        Weekday.tuesday,
                        Weekday.wednesday,
                        Weekday.thursday,
                        Weekday.friday,
                    ]
                }
            )
        }
    )
    outline = _outline(
        profile=profile.model_copy(
            update={"recurring_activities": [*profile.recurring_activities, working]}
        )
    )

    days = {day.date: day for day in expand_outline(outline, package, seed=1).bundle.scenario.days}

    def blocks(day: DayPlan) -> list[Activity]:
        return [item for item in day.activities if item.intent == "work_from_home"]

    weekday_blocks = blocks(days[date(2026, 8, 5)])  # a Wednesday
    assert len(weekday_blocks) == 4
    assert all(item.location_ids == ["living_room"] for item in weekday_blocks)
    starts = sorted(item.start_window.preferred for item in weekday_blocks if item.start_window)
    # Spread through the day rather than stacked: the first and last block are hours apart.
    assert (starts[-1] - starts[0]) > timedelta(hours=4)
    assert blocks(days[date(2026, 8, 8)]) == []  # the Saturday


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


def test_each_block_is_given_its_own_slice_of_the_band_not_the_whole_of_it(
    package: PersonalProcessPackage,
) -> None:
    """The window handed to the compiler has to say what the placement already said.

    Given the whole nine-hour band, four blocks are each free to sit anywhere among the others and
    CP-SAT is asked to choose an ordering rather than confirm one: on a real horizon that exhausted
    its budget on the feasibility probes and the year was rejected with `SOLVER_NOT_OPTIMAL`,
    naming no day.
    """
    profile = _profile()
    working = _recurring(
        "freelance_work",
        RecurringActivityKind.anchor,
        ("09:00", "18:00"),
        times=4,
        jitter=15,
        intent="work_from_home",
    )
    outline = _outline(
        profile=profile.model_copy(
            update={"recurring_activities": [*profile.recurring_activities, working]}
        )
    )

    day = expand_outline(outline, package, seed=1).bundle.scenario.days[0]
    blocks = sorted(
        (item for item in day.activities if item.intent == "work_from_home"),
        key=lambda item: item.start_window.preferred,  # type: ignore[union-attr]
    )

    assert len(blocks) == 4
    for block in blocks:
        window = block.start_window
        assert window is not None
        # Its own sub-band is two and a quarter hours; the whole band is nine.
        assert window.latest - window.earliest <= timedelta(hours=2, minutes=45)
    assert blocks[0].start_window.latest < blocks[-1].start_window.earliest


def test_a_phase_moves_the_window_it_placed_the_habit_in(
    package: PersonalProcessPackage,
) -> None:
    """Everything that reads a cadence must read the one the phase put in force.

    The occurrences were already placed from the variant cadence; the window came from the
    baseline, so a habit a phase moved to a later band was handed the earlier band's hours.
    """
    phase = OutlinePhase(
        phase_id="late",
        label="Late television",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 23),
        activity_overrides=[
            ActivityOverride(
                recurring_activity_id="watch_television",
                cadence=ActivityCadence(
                    period=CadencePeriod.day,
                    times_per_period=1,
                    window_start="21:30",
                    window_end="22:45",
                    jitter_minutes=10,
                ),
            )
        ],
    )
    days = {
        day.date: day
        for day in expand_outline(_outline(phases=[phase]), package, seed=1).bundle.scenario.days
    }

    # The declared occurrence, not one the filler seeded: an unclaimed stretch of the same day may
    # be offered the same intent, and it answers to no band.
    inside = next(
        item
        for item in days[date(2026, 8, 12)].activities
        if item.intent == "watch_television"
        and item.start_window is not None
        and "unclaimed_hours" not in item.labels
    )

    assert inside.start_window is not None
    assert inside.start_window.earliest.strftime("%H:%M") >= "21:15"


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
                # Nested occurrences are exempt by construction: `can_overlap_for_actor` is how
                # the model says "this interrupts whatever is running", and a bathroom break the
                # bladder drive seeded is meant to land inside a block, not beside it.
                if item.start_window
                and item.duration
                and item.intent != "sleep"
                and not item.can_overlap_for_actor
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
    # reject and re-place 18% of every preferred value on the reference horizon. The bound used to
    # be 5%, measured when every occurrence was drawn from a uniform inside ±jitter; a day whose
    # habits keep a rare wide occurrence collides with itself more often, and the pass can no longer
    # clear the last of them by pushing an activity past lights-out. Fifteen pairs of 236, of which
    # two come from that refusal — still a quarter of the rate the pass exists to prevent.
    assert overlapping / pairs < 0.08


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


def test_the_declared_kind_decides_what_a_crowded_day_may_drop(
    package: PersonalProcessPackage,
) -> None:
    """`kind` used to reach nothing: every expanded activity came out mandatory.

    An author marking the television optional was declaring it to no one, and a day holding a long
    evening event had no give at all — a six-hour visit plus a mandatory television, reading and
    hygiene is a contradiction, and the compiler rejected the whole horizon with
    `MAIN_PLAN_INFEASIBLE` for one day of it.
    """
    result = expand_outline(_outline(), package, seed=1)

    by_activity = {
        activity.recurring_activity_id: activity.kind
        for activity in _outline().profile.recurring_activities
    }
    mandatory_by_kind: dict[RecurringActivityKind, set[bool]] = defaultdict(set)
    for day in result.bundle.scenario.days:
        for activity in day.activities:
            identifier = next(
                (
                    label.removeprefix("activity:")
                    for label in activity.labels
                    if label.startswith("activity:")
                ),
                None,
            )
            if identifier in by_activity:
                mandatory_by_kind[by_activity[identifier]].add(activity.mandatory)

    assert mandatory_by_kind[RecurringActivityKind.anchor] == {True}
    assert mandatory_by_kind[RecurringActivityKind.optional] == {False}


def test_the_night_is_never_pushed_into_the_following_day(
    package: PersonalProcessPackage,
) -> None:
    """An activity belongs to the day whose date its preferred start names.

    The overlap pass slides a preferred moment forward to clear the activity before it, and the
    terminal night is the one it can slide across midnight: a late film running to 00:04 against a
    23:54 lights-out whose window still reaches 00:09 moved the sleep to a day that does not list
    it, and the whole 365-day scenario was rejected for that one night.
    """
    misplaced = [
        (day.date, activity.activity_id)
        for seed in range(6)
        for day in expand_outline(_outline(months=6), package, seed=seed).bundle.scenario.days
        for activity in day.activities
        if activity.start_window is not None and activity.start_window.preferred.date() != day.date
    ]

    assert misplaced == []


def test_every_window_edge_lands_on_a_whole_minute(package: PersonalProcessPackage) -> None:
    """`TimeAxis` takes its resolution from the finest unit the scenario uses, so this is a budget.

    The wobble is drawn from a continuous distribution, and handing the raw draw to `timedelta`
    put seconds on 67% of a year's activities. Nothing downstream complains — the plan is still
    valid, and the compiler simply moves to microsecond ticks, where every window of the solve
    exhausts its deterministic budget and reports UNKNOWN. The whole horizon fails to compile, and
    the message says nothing about seconds.
    """
    ragged = [
        (activity.activity_id, edge, moment.isoformat())
        for day in expand_outline(_outline(), package, seed=1).bundle.scenario.days
        for activity in day.activities
        if activity.start_window is not None
        for edge, moment in (
            ("earliest", activity.start_window.earliest),
            ("preferred", activity.start_window.preferred),
            ("latest", activity.start_window.latest),
        )
        if moment.second or moment.microsecond
    ]

    assert ragged == []


def test_the_wobble_never_carries_an_occurrence_out_of_its_day(
    package: PersonalProcessPackage,
) -> None:
    """The mixture's tail reaches outside the author's band, and the band is not the day.

    `test_the_night_is_never_pushed_into_the_following_day` covers the overlap pass; this covers
    the draw itself, and it fails at the other end too. A wide jitter on an early habit reaches
    back past midnight and a late one reaches forward past it, and either lands the occurrence on a
    date its own day plan does not list. Bounding only the evening left 110 of those over a year of
    Giulia's outline, every one an `ACTIVITY_ASSIGNED_TO_WRONG_DAY` error, and the horizon was
    rejected whole.
    """
    outline = _outline(months=2)
    for activity in outline.profile.recurring_activities:
        # Far wider than any author would write, so the tail certainly reaches for both edges.
        activity.cadence.jitter_minutes = 120
    outline.profile.recurring_activities[0].cadence.window_start = "00:30"
    outline.profile.recurring_activities[0].cadence.window_end = "02:00"

    stray = [
        (day.date, item.activity_id, item.start_window.preferred.isoformat())
        for seed in range(4)
        for day in expand_outline(outline, package, seed=seed).bundle.scenario.days
        for item in day.activities
        if item.start_window is not None and item.start_window.preferred.date() != day.date
    ]

    assert stray == []


def test_the_morning_never_starts_before_the_wake(package: PersonalProcessPackage) -> None:
    """Nothing the resident does awake may be scheduled before she is awake.

    The mirror of `test_the_evening_ends_when_the_night_starts`, and it was missing for as long as
    that one existed. `_shift` floors every occurrence at the wake and `_wobble` then rebuilt the
    window from the author's declared band, which knows nothing about the night that just ended: on
    Miriam's twelve-month outline, 99 days of 365 had breakfast, the shower or the morning run
    before the wake, and on the worst of them she woke at 09:36 having already eaten, washed and
    been out running.

    The bound is checked on the *edges*, not on the preferred moments, because the compiler treats
    the window as a hard constraint and will use every minute of it.
    """
    early = []
    for seed in range(4):
        for day in expand_outline(_outline(), package, seed=seed).bundle.scenario.days:
            wake = next(
                (
                    item.start_window.latest
                    for item in day.activities
                    if item.intent == "wake_up" and item.start_window is not None
                ),
                None,
            )
            if wake is None:
                continue
            floor = wake + timedelta(minutes=WAKE_CLEARANCE_MINUTES)
            early.extend(
                (day.date, item.activity_id, item.start_window.earliest.isoformat())
                for item in day.activities
                if item.start_window is not None
                and item.intent not in RHYTHM_EMITTED_INTENTS
                and item.start_window.earliest < floor
            )

    assert early == []


def test_a_late_wake_moves_the_morning_rather_than_squeezing_it(
    package: PersonalProcessPackage,
) -> None:
    """The bound above must translate the band, not clamp its early edge against it.

    Clamping alone left a 70-minute breakfast band with fifteen minutes of window on the morning
    the wake landed late — and the jog, the shower and the medication with fifteen minutes each,
    all over the same quarter of an hour. Three mandatory occurrences and one window is not a
    schedule, and the compiler said so: MAIN_PLAN_INFEASIBLE, on the very day the bound existed
    for. A late wake moves the room the author gave, it does not take it away.
    """
    narrowed = []
    for seed in range(4):
        for day in expand_outline(_outline(), package, seed=seed).bundle.scenario.days:
            for item in day.activities:
                window = item.start_window
                if window is None or item.intent in RHYTHM_EMITTED_INTENTS:
                    continue
                width = (window.latest - window.earliest).total_seconds() / 60
                if width < 2 * MINIMUM_FLEX_MINUTES:
                    narrowed.append((day.date, item.activity_id, width))

    assert narrowed == []


def test_the_evening_ends_when_the_night_starts(package: PersonalProcessPackage) -> None:
    """Nothing the resident does awake may be scheduled after lights-out.

    This is the bill for a bedtime that is allowed to be irregular. The night used to sit in a
    82-minute band, so an evening habit could not be overtaken by it; drawing the night from a
    mixture puts it as early as 20:30, and the evening band an author wrote for an ordinary Tuesday
    then ran straight past it. Measured before `_shift` and `_wobble` learned about lights-out: 115
    of Giulia's 365 days had the resident in bed at 22:01 and doing the washing-up at 22:32.
    """
    late = []
    for seed in range(4):
        for day in expand_outline(_outline(), package, seed=seed).bundle.scenario.days:
            # This day's own night, which is the one its evening runs into. A sleep block in the
            # small hours came from yesterday evening and is the night the day woke up from, so it
            # says nothing about when this evening has to end. When the day's own lights-out fell
            # after midnight the block is on tomorrow's list, and the bound is the day itself.
            own_night = next(
                (
                    item.start_window.preferred
                    for item in reversed(day.activities)
                    if item.intent == "sleep"
                    and item.start_window is not None
                    and item.start_window.preferred.hour >= 12
                ),
                None,
            )
            reference = next(item for item in day.activities if item.start_window is not None)
            midnight = datetime.combine(
                day.date + timedelta(days=1),
                time.min.replace(tzinfo=reference.start_window.preferred.tzinfo),
            )
            lights_out = midnight if own_night is None else own_night
            late += [
                (day.date, item.intent)
                for item in day.activities
                if item.start_window is not None
                and item.intent not in RHYTHM_EMITTED_INTENTS
                and item.start_window.preferred
                > lights_out - timedelta(minutes=EVENING_CLEARANCE_MINUTES)
            ]

    assert late == []


def test_a_debt_nap_is_not_dropped_inside_a_shift(package: PersonalProcessPackage) -> None:
    """The drive layer fills the widest free gap, and a commitment is not a gap.

    Commitments are materialised after the day plan, so without being told about them the drive
    layer reads a working Monday as an empty afternoon and lands the nap in the middle of the
    shift. Two mandatory activities over the same hour, and the day has no schedule at all.
    """
    commitment = FixedCommitment(
        commitment_id="office",
        label="Office",
        weekdays=[Weekday.monday, Weekday.tuesday, Weekday.wednesday],
        start_time="08:30",
        end_time="17:30",
        intent="work_shift",
    )
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
    result = expand_outline(_outline(months=3, fixed_commitments=[commitment]), covering, seed=2)

    clashes = []
    for day in result.bundle.scenario.days:
        shift = next(
            (
                item
                for item in day.activities
                if any(label.startswith("commitment:") for label in item.labels)
            ),
            None,
        )
        if shift is None or shift.start_window is None or shift.duration is None:
            continue
        begins = shift.start_window.preferred
        ends = begins + timedelta(minutes=shift.duration.preferred_minutes)
        # Scoped to what the drive layer placed itself. A declared recurring activity whose band
        # the author ran through the shift is an authoring error the outline owns; the nap and the
        # unplanned call have no band at all, so where they land is the expander's answer.
        clashes.extend(
            item.activity_id
            for item in day.activities
            if item.start_window is not None
            and {"sleep_debt_nap", "social_need_contact"} & set(item.labels)
            and begins <= item.start_window.preferred < ends
        )

    assert clashes == []


# --------------------------------------------------------------------------------------
# What the habit ground truth measures


def _planned_day(day: date, *entries: tuple[str, str, int]) -> DayPlan:
    """A day built by hand from `(intent, HH:MM, minutes)`, so the arithmetic is checkable."""
    activities = []
    for index, (intent, start, minutes) in enumerate(entries):
        hour, minute = (int(part) for part in start.split(":"))
        begin = datetime.combine(day, time(hour, minute), tzinfo=UTC)
        activities.append(
            Activity(
                activity_id=f"{day.isoformat()}_{index}",
                actor_id="resident",
                intent=intent,
                location_ids=["bedroom"],
                start_window=DateTimeWindow(earliest=begin, preferred=begin, latest=begin),
                duration=DurationRange(
                    minimum_minutes=minutes,
                    preferred_minutes=minutes,
                    maximum_minutes=minutes,
                ),
            )
        )
    return DayPlan(date=day, context=DayContext(day_type="weekday"), activities=activities)


def _fortnight(band: HabitSegment, weekday_entries, weekend_entries) -> HabitGroundTruth:
    days = [
        _planned_day(
            _START + timedelta(days=offset),
            *(
                weekend_entries
                if (_START + timedelta(days=offset)).weekday() >= 5
                else weekday_entries
            ),
        )
        for offset in range(14)
    ]
    return _measure_habits(_outline(habits=[band]), days, seed=1)


def test_a_weekday_scoped_band_is_measured_only_on_its_own_days() -> None:
    """The reason the field exists: a band covering both kinds of day averages them together."""
    band = HabitSegment(
        habit_id="daytime",
        label="Working day",
        window_start="09:00",
        window_end="17:00",
        weekdays=[
            Weekday.monday,
            Weekday.tuesday,
            Weekday.wednesday,
            Weekday.thursday,
            Weekday.friday,
        ],
    )
    truth = _fortnight(band, [("perform_work", "09:00", 480)], [("read_and_rest", "09:00", 480)])

    (observation,) = truth.habits
    # Ten weekdays in a fortnight, and not one of the four weekend days.
    assert observation.day_count == 10
    assert [item.intent for item in observation.composition] == ["perform_work"]
    assert observation.composition[0].share == 1.0
    assert observation.day_types == []


def test_an_unscoped_band_publishes_the_split_it_is_hiding() -> None:
    """Same hours, two behaviours. Without the split the band reads as a 5:2 blend of both."""
    band = HabitSegment(
        habit_id="daytime", label="Daytime", window_start="09:00", window_end="17:00"
    )
    truth = _fortnight(band, [("perform_work", "09:00", 480)], [("read_and_rest", "09:00", 480)])

    (observation,) = truth.habits
    assert observation.day_count == 14
    assert {item.intent for item in observation.composition} == {"perform_work", "read_and_rest"}

    split = {item.day_type: item for item in observation.day_types}
    assert split["weekday"].day_count == 10
    assert split["weekend"].day_count == 4
    assert [item.intent for item in split["weekday"].composition] == ["perform_work"]
    assert [item.intent for item in split["weekend"].composition] == ["read_and_rest"]


def test_the_effective_window_is_where_the_dominant_activity_actually_runs() -> None:
    """A window is where the planner may put the band; this is where the behaviour landed."""
    band = HabitSegment(habit_id="night", label="Night", window_start="21:00", window_end="07:00")
    # Declared from 21:00, but the resident watches television until 23:00 and sleeps from there.
    truth = _fortnight(
        band,
        [("watch_television", "21:00", 120), ("sleep", "23:00", 420)],
        [("watch_television", "21:00", 120), ("sleep", "23:00", 420)],
    )

    (observation,) = truth.habits
    assert observation.dominant_intent == "sleep"
    assert (observation.effective_start, observation.effective_end) == ("23:00", "06:00")
    # Seven hours of the ten-hour band, and the declared window is left untouched.
    assert observation.effective_minutes == 420.0
    assert (observation.window_start, observation.window_end) == ("21:00", "07:00")


def test_no_effective_window_is_published_when_nothing_holds_the_band() -> None:
    """A band with no dominant behaviour reports none, rather than inventing a boundary."""
    band = HabitSegment(
        habit_id="evening", label="Evening", window_start="17:00", window_end="21:00"
    )
    # Four activities of an hour each, none of them on more than a quarter of the days.
    days = [
        _planned_day(
            _START + timedelta(days=offset),
            (
                ("read_and_rest", "eat_dinner", "watch_television", "phone_call")[offset % 4],
                "17:00",
                240,
            ),
        )
        for offset in range(12)
    ]
    truth = _measure_habits(_outline(habits=[band]), days, seed=1)

    (observation,) = truth.habits
    assert observation.effective_start is None
    assert observation.effective_end is None
    assert observation.effective_share == 0.0
