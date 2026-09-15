from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.compiler.service import compile_scenario
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import (
    BRANCH_EXTENSION,
    PRIVACY_EXTENSION,
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
    SimulationWindow,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.day_generation import (
    EVENING_CLEARANCE_MINUTES,
    RHYTHM_EMITTED_INTENTS,
    WAKE_CLEARANCE_MINUTES,
)
from smart_home_sim.hybrid_planning.dwelling import CORE_RESOURCES
from smart_home_sim.hybrid_planning.expander import (
    _MEAL_AFTER_PREPARATION,
    FILL_INTENTS,
    FILL_LABEL,
    JOINT_BRANCH_PRIORITY,
    MINIMUM_FLEX_MINUTES,
    SEPARATE_BRANCH_PRIORITY,
    SHARED_ARRIVAL_MAXIMUM_LAG_MINUTES,
    ExpansionError,
    _cook_before_eating,
    _separate_priority,
    _waiting_rooms,
    expand_outline,
)
from smart_home_sim.hybrid_planning.habits import (
    DECLARED_HABITS_EXTENSION,
    evidence_from_plan,
    measure_habits,
    measure_household,
)
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG, IntentCategory
from smart_home_sim.hybrid_planning.outline import (
    ActivityDisplacement,
    ActivityOverride,
    ActivityProposal,
    DeclaredHabits,
    DeclaredResidentHabits,
    Displacement,
    FixedCommitment,
    HabitGroundTruth,
    HabitSegment,
    HorizonOutline,
    Household,
    HouseholdRelation,
    JointActivity,
    LocationPrivacy,
    OutlineEvent,
    OutlinePhase,
    OutlineResident,
    OutlineWorld,
    RelationKind,
    SharingMode,
    SharingPolicy,
    SharingPropensity,
    VocabularyProposals,
)
from smart_home_sim.hybrid_planning.package_authoring import _retarget_reference
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
# Everybody a test in this module names as a resident.
_TEST_RESIDENTS = ("resident", "r1", "r2", "r3")


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
    #
    # A binding belongs to a resident, and the expander checks coverage per resident, so every
    # identifier these tests give a resident is bound — the minimal example's own `resident_1` is
    # nobody the outlines here name.
    template = payload["bindings"][0]
    by_model = {binding["intent"]: binding["processModelId"] for binding in payload["bindings"]}
    needed = {spec.intent_id for spec in INTENT_CATALOG} | RHYTHM_EMITTED_INTENTS
    payload["bindings"] = [
        {
            **template,
            "bindingId": f"{resident}__{intent}",
            "residentId": resident,
            "intent": intent,
            "processModelId": by_model.get(intent, template["processModelId"]),
        }
        for resident in _TEST_RESIDENTS
        for intent in sorted(needed)
    ]
    return PersonalProcessPackage.model_validate_json(json.dumps(payload))


def _with_away_intent(package: PersonalProcessPackage, intent: str) -> PersonalProcessPackage:
    """The package, also able to be somewhere else: an absence needs an away intent."""
    template = package.bindings[0]
    return package.model_copy(
        update={
            "bindings": [
                *package.bindings,
                *(
                    template.model_copy(
                        update={
                            "binding_id": f"{resident}__away__{intent}",
                            "resident_id": resident,
                            "intent": intent,
                        }
                    )
                    for resident in _TEST_RESIDENTS
                ),
            ]
        }
    )


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


def _resident(**overrides: Any) -> OutlineResident:
    fields: dict[str, Any] = {"resident_id": "resident", "profile": _profile()}
    fields.update(overrides)
    return OutlineResident(**fields)


# Routed down to the single resident by `_outline`, so a test about phases, events or bands reads
# the way it did before the household existed.
_PERSONAL_FIELDS = frozenset(
    {"resident_id", "display_name", "profile", "rhythm", "habits", "fixed_commitments"}
    | {"phases", "events", "start_location_id"}
)


def _outline(**overrides: Any) -> HorizonOutline:
    """A household of one unless the test passes `residents=` or `household=`."""
    personal = {key: value for key, value in overrides.items() if key in _PERSONAL_FIELDS}
    fields: dict[str, Any] = {
        "outline_id": "o1",
        "title": "One month",
        "time_zone": "America/New_York",
        "start_date": _START,
        "months": 1,
        "world": _world(),
        "residents": [_resident(**personal)],
        "provenance": Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    }
    fields.update({key: value for key, value in overrides.items() if key not in _PERSONAL_FIELDS})
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


def _world_with_study(furniture: str | None) -> OutlineWorld:
    """The catalog rooms plus a study, furnished with one piece or left empty."""
    world = _world()
    resources = list(world.resources)
    if furniture is not None:
        resources.append(
            Resource(resource_id="study_piece", resource_type=furniture, location_id="study")
        )
    return world.model_copy(
        update={
            "locations": [
                *world.locations,
                Location(location_id="study", kind=LocationKind.room),
            ],
            "resources": resources,
        }
    )


def _override(profile: BehavioralProfile, activity_id: str, room: str) -> BehavioralProfile:
    return profile.model_copy(
        update={
            "recurring_activities": [
                item.model_copy(update={"location": room})
                if item.recurring_activity_id == activity_id
                else item
                for item in profile.recurring_activities
            ]
        }
    )


def test_a_habit_can_declare_the_room_it_happens_in(package: PersonalProcessPackage) -> None:
    """The catalog holds one room per intent; a habit is allowed to differ from it.

    Reading in a study and watching television on the sofa are the same activity performed in two
    places, which the label space cannot express and should not have to: `watch_television` stays
    one intent, and the room moves with the habit. The rooms of the habits that said nothing are
    untouched, so an outline written before this field means exactly what it meant.
    """
    outline = _outline(
        world=_world_with_study("sofa"),
        profile=_override(_profile(), "watch_television", "study"),
    )

    result = expand_outline(outline, package, seed=1)

    declared: dict[str, set[str]] = {}
    undeclared: dict[str, set[str]] = {}
    for day in result.bundle.scenario.days:
        for activity in day.activities:
            # An occurrence of a declared habit carries its id; everything else on the day — the
            # rhythm's wake and night, the filler layer's offers — carries no `activity:` label.
            habit = next((item for item in activity.labels if item.startswith("activity:")), None)
            target = declared if habit is not None else undeclared
            target.setdefault(activity.intent, set()).add(activity.location_ids[0])
    assert declared["watch_television"] == {"study"}
    # Everything else stays where the catalog puts it, the sleeping the rhythm adds included.
    assert declared["eat_breakfast"] == {"kitchen"}
    assert undeclared["sleep"] == {"bedroom"}
    # The filler layer offers the same intent as behaviour nobody declared, and that is not this
    # habit: it keeps the catalog's room, which is what makes the override a property of the habit.
    assert undeclared["watch_television"] == {"living_room"}


def test_a_proposed_activity_is_refused_until_it_is_in_the_vocabulary(
    package: PersonalProcessPackage,
) -> None:
    """Refused like any unknown intent, but the refusal says the fix is in the vocabulary."""
    profile = _profile()
    guest = _recurring(
        "dinner_guest", RecurringActivityKind.rare, ("19:00", "22:00"), intent="host_guest"
    )
    outline = _outline(
        profile=profile.model_copy(
            update={"recurring_activities": [*profile.recurring_activities, guest]}
        ),
        vocabulary_proposals=VocabularyProposals(
            activities=[
                ActivityProposal(
                    intent_id="host_guest",
                    label="Host a guest",
                    category=IntentCategory.social,
                    default_location="kitchen",
                    rationale="A dinner guest is not a phone call.",
                )
            ]
        ),
    )

    with pytest.raises(
        ExpansionError, match="proposed and not yet in the vocabulary: 'host_guest'"
    ):
        expand_outline(outline, package, seed=1)


def test_a_habit_sent_to_a_room_that_is_not_there_is_refused(
    package: PersonalProcessPackage,
) -> None:
    outline = _outline(profile=_override(_profile(), "watch_television", "library"))

    with pytest.raises(ExpansionError, match="does not declare as a room"):
        expand_outline(outline, package, seed=1)


def test_a_habit_sent_to_a_room_that_cannot_perform_it_is_refused(
    package: PersonalProcessPackage,
) -> None:
    """A study with only a bookshelf in it cannot hold a meal, and saying so is the whole point.

    Unrefused, the binder falls back to the room's service anchor — no footprint, no contact
    sensor, no position — and the activity runs in the middle of an empty room, producing a month
    of behaviour the sensor log does not record. The failure has to happen here, where an author
    can still fix it, rather than as an absence nobody can see.
    """
    outline = _outline(
        world=_world_with_study("bookshelf"),
        profile=_override(_profile(), "watch_television", "study"),
    )

    with pytest.raises(ExpansionError, match="holds nothing offering consumable"):
        expand_outline(outline, package, seed=1)


def test_a_room_furnished_with_a_type_the_vocabulary_does_not_know_is_accepted(
    package: PersonalProcessPackage,
) -> None:
    """Unknown furniture offers every capability here, as it does everywhere after expansion.

    An outline for a resident who does yoga in the living room had no way through: no piece of
    furniture in the vocabulary declares `exercise_support`, and the one it invented — an
    `exercise_mat` — was read by this check as offering nothing, while the binder, the
    materializer and the preflight all read it as offering everything.
    """
    outline = _outline(
        world=_world_with_study("exercise_mat"),
        profile=_override(_profile(), "watch_television", "study"),
    )

    result = expand_outline(outline, package, seed=1)

    assert any(
        activity.location_ids[0] == "study"
        for day in result.bundle.scenario.days
        for activity in day.activities
        if activity.intent == "watch_television"
    )


def test_a_habit_sent_outdoors_is_accepted(package: PersonalProcessPackage) -> None:
    """Naming `outdoors` is the outline agreeing with the catalog, not contradicting the world.

    `evening_walk` and `buy_groceries` are placed `outdoors` by the activity catalog, and the
    world declares it `external` because it is not a room — so the room-kinded check refused an
    outline for stating the destination those two intents already have. Nothing is furnished out
    there by the resident either, which is why the capability half has to stay off it.
    """
    outline = _outline(
        profile=_override(
            _override(_profile(), "morning_walk", "outdoors"), "buy_groceries", "outdoors"
        )
    )

    result = expand_outline(outline, package, seed=1)

    outdoors = {
        activity.location_ids[0]
        for day in result.bundle.scenario.days
        for activity in day.activities
        if activity.intent in {"evening_walk", "buy_groceries"}
    }
    assert outdoors == {"outdoors"}


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
    covering = _with_away_intent(package, "work_shift")
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
        for activity in _outline().residents[0].profile.recurring_activities
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
    for activity in outline.residents[0].profile.recurring_activities:
        # Far wider than any author would write, so the tail certainly reaches for both edges.
        activity.cadence.jitter_minutes = 120
    outline.residents[0].profile.recurring_activities[0].cadence.window_start = "00:30"
    outline.residents[0].profile.recurring_activities[0].cadence.window_end = "02:00"

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
    covering = _with_away_intent(package, "work_shift")
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


def _planned_day(day: date, *entries: tuple[str, str, int] | tuple[str, str, int, str]) -> DayPlan:
    """A day built by hand from `(intent, HH:MM, minutes[, room])`, so the sums are checkable."""
    activities = []
    for index, entry in enumerate(entries):
        intent, start, minutes = entry[0], entry[1], entry[2]
        room = entry[3] if len(entry) == 4 else "bedroom"
        hour, minute = (int(part) for part in start.split(":"))
        begin = datetime.combine(day, time(hour, minute), tzinfo=UTC)
        activities.append(
            Activity(
                activity_id=f"{day.isoformat()}_{index}",
                actor_id="resident",
                intent=intent,
                location_ids=[room],
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
    return _measure_plan(band, days)


def _measure_plan(band: HabitSegment, days: list[DayPlan]) -> HabitGroundTruth:
    """The shared band arithmetic, run on hand-built days whose clock is UTC."""
    declared = DeclaredHabits(
        outline_id="o1",
        time_zone="UTC",
        start_date=days[0].date,
        end_date=days[-1].date + timedelta(days=1),
        seed=1,
        residents=[DeclaredResidentHabits(resident_id="resident", habits=[band])],
    )
    evidence = evidence_from_plan(
        days,
        ["resident"],
        started_at=datetime.combine(declared.start_date, time.min, UTC),
        ended_at=datetime.combine(declared.end_date, time.min, UTC),
    )
    (truth,) = measure_habits(declared, evidence)
    return truth


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


def test_one_activity_in_two_rooms_is_two_rows_and_the_band_names_the_larger() -> None:
    """The measurement a habit's own room would otherwise be averaged out of.

    Reading in the study and reading on the sofa are one intent and two behaviours, which is the
    whole reason a recurring activity may name its room. Keyed by intent alone the band reported
    one row at 100% and an evaluation could not tell that half of it happened somewhere else.
    """
    band = HabitSegment(
        habit_id="daytime", label="Daytime", window_start="09:00", window_end="17:00"
    )
    truth = _fortnight(
        band,
        [("read_and_rest", "09:00", 300, "study"), ("read_and_rest", "14:00", 180, "living_room")],
        [("read_and_rest", "09:00", 300, "study"), ("read_and_rest", "14:00", 180, "living_room")],
    )

    (observation,) = truth.habits
    rows = {(item.intent, item.location): item.minutes for item in observation.composition}
    assert rows == {
        ("read_and_rest", "study"): 14 * 300,
        ("read_and_rest", "living_room"): 14 * 180,
    }
    # The band is held by the study, and says so rather than leaving it to be re-derived.
    assert observation.dominant_intent == "read_and_rest"
    assert observation.dominant_location == "study"


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
    truth = _measure_plan(band, days)

    (observation,) = truth.habits
    assert observation.effective_start is None
    assert observation.effective_end is None
    assert observation.effective_share == 0.0


def _meal(intent: str, hour: int, *, mandatory: bool = True) -> Activity:
    moment = datetime(2026, 9, 13, hour, tzinfo=UTC)
    return Activity(
        activity_id=f"2026-09-13_{intent}",
        actor_id="resident",
        intent=intent,
        location_ids=["kitchen"],
        start_window=DateTimeWindow(
            earliest=moment - timedelta(hours=2), preferred=moment, latest=moment
        ),
        duration=DurationRange(minimum_minutes=12, preferred_minutes=24, maximum_minutes=75),
        mandatory=mandatory,
    )


def test_a_meal_waits_for_the_day_to_cook_it() -> None:
    """Nothing said the cooking comes first, and on a congested day the compiler used the freedom.

    `prepare_simple_lunch` and `eat_lunch` are two habits with two bands, the author's bands
    overlap by the best part of two hours, and between the two activities there was no ordering of
    any kind. So the solver put lunch at 12:19, squeezed to its twelve-minute minimum, and left the
    cooking at its own preferred 13:32: twelve dinners of twenty-nine and five lunches of nine came
    out that way over one generated month.
    """
    activities = _cook_before_eating(
        [_meal("prepare_simple_lunch", 13), _meal("eat_lunch", 12), _meal("wake_up", 8)]
    )
    by_intent = {item.intent: item for item in activities}

    groups = by_intent["eat_lunch"].dependency_groups
    assert [group.activity_ids for group in groups] == [["2026-09-13_prepare_simple_lunch"]]
    assert groups[0].minimum_lag_minutes == 0
    # Only the meal waits. The cooking has nothing to wait for, and neither does the morning.
    assert not by_intent["prepare_simple_lunch"].dependency_groups
    assert not by_intent["wake_up"].dependency_groups


def test_breakfast_waits_for_the_morning_to_make_it() -> None:
    """The third meal, and the one that had no preparation to wait for until `prepare_breakfast`.

    Lunch and dinner have had a cooking intent since the first catalog; breakfast had none an
    outline could declare, so the row was unreachable rather than absent by choice. Two authored
    horizons ate 30 and 132 breakfasts with nothing before any of them.
    """
    activities = _cook_before_eating([_meal("eat_breakfast", 8), _meal("prepare_breakfast", 7)])
    by_intent = {item.intent: item for item in activities}

    groups = by_intent["eat_breakfast"].dependency_groups
    assert [group.activity_ids for group in groups] == [["2026-09-13_prepare_breakfast"]]
    assert not by_intent["prepare_breakfast"].dependency_groups


def test_every_meal_names_a_preparation_the_vocabulary_actually_has() -> None:
    """A row naming an intent no outline can declare orders nothing and says nothing.

    That is what a breakfast row would have been before `prepare_breakfast` had a reference
    process model: `INTENT_CATALOG` is what the authoring prompt's in-home list is rendered from,
    so an intent missing from it cannot appear in an outline and cannot appear in a day.
    """
    known = {spec.intent_id for spec in INTENT_CATALOG}
    for meal, preparation in _MEAL_AFTER_PREPARATION.items():
        assert meal in known
        assert preparation in known


def test_a_mandatory_meal_is_not_chained_to_cooking_the_author_made_optional() -> None:
    """The solver reads a dependency as `presence(meal) <= presence(cooking)`.

    So tying a mandatory dinner to a sacrificial preparation makes the preparation mandatory by the
    back door, and over-constrains the one day that could not fit it. Where the author said the
    cooking may be dropped, an uncooked dinner is what they asked for.
    """
    kept = _cook_before_eating(
        [
            _meal("prepare_light_dinner", 19, mandatory=False),
            _meal("eat_dinner", 20, mandatory=True),
        ]
    )
    assert all(not item.dependency_groups for item in kept)

    # Both sacrificial is a different matter: dropping the cooking drops the meal, which is true.
    chained = _cook_before_eating(
        [
            _meal("prepare_light_dinner", 19, mandatory=False),
            _meal("eat_dinner", 20, mandatory=False),
        ]
    )
    assert [item.intent for item in chained if item.dependency_groups] == ["eat_dinner"]


# --- the household ------------------------------------------------------------------------------


def _renamed(profile: BehavioralProfile, suffix: str) -> BehavioralProfile:
    """The same routine under identifiers of its own.

    Recurring activity identifiers are unique across the whole outline, because the expander merges
    every resident's day into one scenario and two people who had both called an activity
    `eat_breakfast` would arrive there as one activity performed twice.
    """
    return profile.model_copy(
        update={
            "profile_id": f"{profile.profile_id}_{suffix}",
            "persona_id": f"{profile.persona_id}_{suffix}",
            "recurring_activities": [
                item.model_copy(
                    update={"recurring_activity_id": f"{item.recurring_activity_id}_{suffix}"}
                )
                for item in profile.recurring_activities
            ],
        }
    )


def _without(profile: BehavioralProfile, *activity_ids: str) -> BehavioralProfile:
    return profile.model_copy(
        update={
            "recurring_activities": [
                item
                for item in profile.recurring_activities
                if item.recurring_activity_id not in activity_ids
            ]
        }
    )


def _two_residents() -> list[OutlineResident]:
    return [
        _resident(resident_id="r1", profile=_renamed(_profile(), "r1")),
        _resident(resident_id="r2", profile=_renamed(_profile(), "r2")),
    ]


def _couple(**household: Any) -> HorizonOutline:
    """Two residents, one house, whatever the household declares on top."""
    return _outline(residents=_two_residents(), household=Household(**household))


def _joint_dinner(**overrides: Any) -> JointActivity:
    fields: dict[str, Any] = {
        "activity": _recurring(
            "household_dinner",
            RecurringActivityKind.anchor,
            ("19:00", "21:00"),
            intent="eat_dinner",
        ),
        "participant_ids": ["r1", "r2"],
        # Pinned off here: these tests are about when a meal is shared and how it is emitted, and
        # they count one interval. Degradation — on by default — has tests of its own below.
        "degrade_to_independent": False,
    }
    fields.update(overrides)
    return JointActivity(**fields)


def _shared_couple(**overrides: Any) -> HorizonOutline:
    """The couple with their own dinners replaced by one declared for the household."""
    joint = _joint_dinner(**overrides)
    return _outline(
        residents=[
            _resident(
                resident_id="r1", profile=_without(_renamed(_profile(), "r1"), "eat_dinner_r1")
            ),
            _resident(
                resident_id="r2", profile=_without(_renamed(_profile(), "r2"), "eat_dinner_r2")
            ),
        ],
        household=Household(joint_activities=[joint]),
    )


def _occurrences_of(day: DayPlan, activity_id: str) -> list[Activity]:
    return [activity for activity in day.activities if f"activity:{activity_id}" in activity.labels]


def test_two_residents_are_one_scenario_with_two_rosters(package: PersonalProcessPackage) -> None:
    """One house, one log, two people: the household is a scenario, not two scenarios."""
    result = expand_outline(_couple(), package, seed=1)
    scenario = result.bundle.scenario

    assert [item.resident_id for item in scenario.residents] == ["r1", "r2"]
    assert [item.resident_id for item in scenario.initial_state.residents] == ["r1", "r2"]
    actors = {activity.actor_id for day in scenario.days for activity in day.activities}
    assert actors == {"r1", "r2"}


def test_two_residents_never_share_an_activity_identifier(
    package: PersonalProcessPackage,
) -> None:
    """Identifiers are `<date>_<index>_<intent>`, so two people waking on one morning collide."""
    result = expand_outline(_couple(), package, seed=1)

    for day in result.bundle.scenario.days:
        identifiers = [activity.activity_id for activity in day.activities]
        assert len(set(identifiers)) == len(identifiers)


def test_one_ground_truth_per_resident(package: PersonalProcessPackage) -> None:
    """Habit segmentation is defined over a person, so a shared log has N answer sheets."""
    band = HabitSegment(
        habit_id="evening", label="Evening", window_start="18:00", window_end="23:00"
    )
    outline = _outline(
        residents=[
            _resident(
                resident_id="r1",
                profile=_renamed(_profile(), "r1"),
                habits=[band.model_copy(update={"habit_id": "evening_r1"})],
            ),
            _resident(
                resident_id="r2",
                profile=_renamed(_profile(), "r2"),
                habits=[band.model_copy(update={"habit_id": "evening_r2"})],
            ),
        ]
    )

    result = expand_outline(outline, package, seed=1)

    assert [item.resident_id for item in result.declared_habits.residents] == ["r1", "r2"]
    assert [item.habits[0].habit_id for item in result.declared_habits.residents] == [
        "evening_r1",
        "evening_r2",
    ]
    assert [item.resident_id for item in result.planned_bands] == ["r1", "r2"]
    assert {item.measured_on for item in result.planned_bands} == {"expanded_plan"}
    extension = result.bundle.scenario.extensions[DECLARED_HABITS_EXTENSION]
    assert [item["residentId"] for item in extension["residents"]] == ["r1", "r2"]  # type: ignore[index,union-attr]


def test_a_joint_activity_is_emitted_once_with_every_participant_named(
    package: PersonalProcessPackage,
) -> None:
    """The rule the household level exists for: one dinner, not two dinners forty minutes apart."""
    result = expand_outline(_shared_couple(), package, seed=1)

    for day in result.bundle.scenario.days:
        dinners = _occurrences_of(day, "household_dinner")
        assert len(dinners) == 1
        assert dinners[0].actor_id == "r1"
        # `participantIds` names the people taking part besides the actor; repeating him there is
        # a validation failure, and `occupied_residents()` adds him back regardless.
        assert dinners[0].participant_ids == ["r2"]


def test_a_shared_dinner_is_counted_in_the_band_of_the_resident_who_does_not_own_it(
    package: PersonalProcessPackage,
) -> None:
    """She was at the table. Measuring her evening by `actor_id` alone would report it empty."""
    band = HabitSegment(
        habit_id="evening_r2", label="Evening", window_start="18:30", window_end="22:00"
    )
    outline = _shared_couple()
    outline = outline.model_copy(
        update={
            "residents": [
                outline.residents[0],
                outline.residents[1].model_copy(update={"habits": [band]}),
            ]
        }
    )

    truth = expand_outline(outline, package, seed=1).planned_bands[1]

    assert truth.resident_id == "r2"
    assert "eat_dinner" in {row.intent for row in truth.habits[0].composition}


def test_an_optional_joint_activity_is_shared_on_some_days_and_not_on_others(
    package: PersonalProcessPackage,
) -> None:
    """A propensity is a number, and a number that is neither 0 nor 1 has to produce a mixture."""
    outline = _shared_couple(
        sharing=SharingMode.optional_joint,
        propensity=SharingPropensity(default=0.5),
    )

    days = expand_outline(outline, package, seed=1).bundle.scenario.days
    counts = {len(_occurrences_of(day, "household_dinner")) for day in days}

    assert counts == {1, 2}


def test_a_weekend_propensity_does_not_leak_into_the_working_week(
    package: PersonalProcessPackage,
) -> None:
    """The argument for indexing the number: a single average fabricates a weekly pattern."""
    outline = _shared_couple(
        sharing=SharingMode.optional_joint,
        propensity=SharingPropensity(default=0.0, weekend=1.0),
    )

    days = expand_outline(outline, package, seed=1).bundle.scenario.days
    shared = {
        day.date.weekday() for day in days if len(_occurrences_of(day, "household_dinner")) == 1
    }

    assert shared == {5, 6}


def test_a_propensity_of_zero_still_feeds_both_residents(
    package: PersonalProcessPackage,
) -> None:
    """Not shared is two dinners, not none: they eat, they just do not eat together."""
    outline = _shared_couple(
        sharing=SharingMode.optional_joint, propensity=SharingPropensity(default=0.0)
    )

    for day in expand_outline(outline, package, seed=1).bundle.scenario.days:
        dinners = _occurrences_of(day, "household_dinner")
        assert len(dinners) == 2
        assert {item.actor_id for item in dinners} == {"r1", "r2"}
        assert all(not item.participant_ids for item in dinners)


def _late_worker(**overrides: Any) -> HorizonOutline:
    """The couple, with one of them at work until a quarter past eight on the working days."""
    outline = _shared_couple(**overrides)
    shift = FixedCommitment(
        commitment_id="evening_shift",
        label="Evening shift",
        intent="work_shift",
        weekdays=[
            Weekday.monday,
            Weekday.tuesday,
            Weekday.wednesday,
            Weekday.thursday,
            Weekday.friday,
        ],
        start_time="19:00",
        end_time="20:15",
    )
    return outline.model_copy(
        update={
            "residents": [
                outline.residents[0],
                outline.residents[1].model_copy(update={"fixed_commitments": [shift]}),
            ]
        }
    )


def test_a_minimum_overlap_refuses_a_shared_meal_nobody_had_time_for(
    package: PersonalProcessPackage,
) -> None:
    """A dinner squeezed into the minutes a shift leaves over is not a shared dinner.

    The shift leaves them forty-five minutes in common from Monday to Friday and the whole band at
    the weekend, so a minimum of one lets every day share and a minimum of an hour keeps the
    working week apart. Neither is refused outright: both are possible on some day.
    """

    # An absence needs an away intent, and the shared fixture only binds the home catalog.
    covering = _with_away_intent(package, "work_shift")

    def shared_weekdays(outline: HorizonOutline) -> set[int]:
        return {
            day.date.weekday()
            for day in expand_outline(outline, covering, seed=1).bundle.scenario.days
            if len(_occurrences_of(day, "household_dinner")) == 1
        }

    assert shared_weekdays(_late_worker(minimum_shared_minutes=1)) == set(range(7))
    assert shared_weekdays(_late_worker(minimum_shared_minutes=60)) == {5, 6}


def test_a_shared_meal_starts_soon_after_the_last_one_gets_home(
    package: PersonalProcessPackage,
) -> None:
    """Arrives, and then they eat together — within twenty minutes, not some time that evening.

    No-overlap alone kept the dinner out of the shift and nothing else: the one at home could be
    left "waiting" until the band closed. The dependency on the shift carries the design's maximum
    lag, and compiling the day shows the dinner beginning inside it. At the weekend nobody is out,
    so there is nothing to anchor to.
    """
    covering = _with_away_intent(package, "work_shift")
    scenario = expand_outline(
        _late_worker(minimum_shared_minutes=1), covering, seed=1
    ).bundle.scenario
    monday, saturday = scenario.days[0], scenario.days[5]

    (dinner,) = _occurrences_of(monday, "household_dinner")
    (shift,) = [item for item in monday.activities if "commitment:evening_shift" in item.labels]
    assert [(group.activity_ids, group.maximum_lag_minutes) for group in dinner.dependency_groups][
        -1
    ] == ([shift.activity_id], SHARED_ARRIVAL_MAXIMUM_LAG_MINUTES)
    assert not any(
        group.maximum_lag_minutes
        for item in _occurrences_of(saturday, "household_dinner")
        for group in item.dependency_groups
    )

    one_day = scenario.model_copy(
        update={
            "days": [monday],
            "simulation_window": SimulationWindow(
                start=datetime.combine(monday.date, time.min, dinner.start_window.preferred.tzinfo),
                end=datetime.combine(
                    monday.date + timedelta(days=1), time.min, dinner.start_window.preferred.tzinfo
                ),
            ),
        }
    )
    one_day = one_day.model_copy(
        update={
            "days": [
                monday.model_copy(
                    update={
                        "activities": [
                            item.model_copy(update={"allow_boundary_truncation": True})
                            for item in monday.activities
                        ]
                    }
                )
            ],
            "initial_state": one_day.initial_state.model_copy(
                update={"at": one_day.simulation_window.start}
            ),
        }
    )
    plan = compile_scenario(one_day).plan
    assert plan is not None
    scheduled = {item.source_activity_id: item for day in plan.days for item in day.activities}
    lag = scheduled[dinner.activity_id].scheduled_start - scheduled[shift.activity_id].scheduled_end
    assert timedelta() <= lag <= timedelta(minutes=SHARED_ARRIVAL_MAXIMUM_LAG_MINUTES)


def test_a_shared_meal_that_can_never_happen_is_refused_before_the_days_exist(
    package: PersonalProcessPackage,
) -> None:
    """A propensity above zero on bands that never meet declares a dinner nobody ever has."""
    with pytest.raises(ExpansionError, match="never leave them more than"):
        expand_outline(_shared_couple(minimum_shared_minutes=24 * 60), package, seed=1)


def _housemates(**second: Any) -> HorizonOutline:
    """Two friends splitting the rent, in a flat with a bed in each of two bedrooms."""
    world = _world((*_ROOMS, "second_bedroom"))
    world = world.model_copy(
        update={
            "resources": [
                *world.resources,
                Resource(resource_id="bed_main", resource_type="bed", location_id="bedroom"),
                Resource(
                    resource_id="bed_spare",
                    resource_type="single_bed",
                    location_id="second_bedroom",
                ),
            ],
            "start_location_id": "bedroom",
        }
    )
    first, other = _two_residents()
    return _outline(
        world=world,
        residents=[first, other.model_copy(update=second)],
        household=Household(
            relations=[HouseholdRelation(between=["r1", "r2"], kind=RelationKind.housemates)]
        ),
    )


def test_a_housemate_sleeps_in_her_own_room_every_night(package: PersonalProcessPackage) -> None:
    """Where she wakes on the first morning is where her bed is, on every night after it too.

    `startLocationId` used to be read for that first midnight only; every night after it both
    friends walked to the catalog's bedroom and lay down in one bed.
    """
    outline = _housemates(start_location_id="second_bedroom")

    days = expand_outline(outline, package, seed=1).bundle.scenario.days
    rooms: dict[str, set[str]] = defaultdict(set)
    for day in days:
        for activity in day.activities:
            if activity.intent in {"sleep", "wake_up"}:
                rooms[activity.actor_id].add(activity.location_ids[0])

    assert rooms == {"r1": {"bedroom"}, "r2": {"second_bedroom"}}


def test_housemates_are_not_put_in_one_bedroom_without_saying_so(
    package: PersonalProcessPackage,
) -> None:
    """Two friends do not share a bed (§6); a house that follows the family gives them two rooms."""
    with pytest.raises(ExpansionError, match="housemates and would both sleep in 'bedroom'"):
        expand_outline(_housemates(), package, seed=1)

    # Choosing to share it is one line, like every other permissive setting.
    shared = _housemates()
    shared = shared.model_copy(
        update={
            "household": shared.household.model_copy(update={"shared_location_ids": ["bedroom"]})
        }
    )
    expand_outline(
        HorizonOutline.model_validate_json(shared.model_dump_json(by_alias=True)), package, seed=1
    )


def test_two_nights_may_not_be_asked_to_share_one_bedroom(
    package: PersonalProcessPackage,
) -> None:
    """The hard constraint of a household: declared privacy over the night has nowhere to go."""
    outline = _outline(
        residents=_two_residents(),
        household=Household(
            location_privacy=[LocationPrivacy(location_id="bedroom", subject_id="r1")]
        ),
    )

    with pytest.raises(ExpansionError, match="one such room for two nights"):
        expand_outline(outline, package, seed=1)


def test_the_household_expansion_is_deterministic(package: PersonalProcessPackage) -> None:
    """Two residents double the moving parts and must not double the sources of variation."""
    first = expand_outline(_shared_couple(), package, seed=7).bundle.scenario
    second = expand_outline(_shared_couple(), package, seed=7).bundle.scenario

    assert first.model_dump_json(by_alias=True) == second.model_dump_json(by_alias=True)


def test_one_resident_is_the_household_of_one(package: PersonalProcessPackage) -> None:
    """N=1 is not a separate path: the same code, with every loop running once."""
    result = expand_outline(_outline(), package, seed=1)

    assert len(result.planned_bands) == 1
    assert [item.resident_id for item in result.bundle.scenario.residents] == ["resident"]


def _bathroom_world() -> OutlineWorld:
    """The test world with one shower in the bathroom, which is what makes it a bathroom."""
    world = _world()
    return world.model_copy(
        update={
            "resources": [
                *world.resources,
                Resource(resource_id="shower", resource_type="shower", location_id="bathroom"),
            ]
        }
    )


def _privacy_marks(days: Sequence[DayPlan]) -> dict[str, set[str]]:
    """Who each actor's activities exclude, gathered over the horizon."""
    marks: dict[str, set[str]] = defaultdict(set)
    for day in days:
        for activity in day.activities:
            excluded = activity.extensions.get(PRIVACY_EXTENSION)
            if isinstance(excluded, list):
                marks[activity.actor_id].update(str(item) for item in excluded)
    return dict(marks)


def test_a_room_with_one_sanitary_fixture_is_private_without_anyone_declaring_it(
    package: PersonalProcessPackage,
) -> None:
    """The restrictive default: the cost of getting it wrong the other way is a false dataset."""
    outline = _outline(world=_bathroom_world(), residents=_two_residents())

    days = expand_outline(outline, package, seed=1).bundle.scenario.days
    bathroom = [
        activity
        for day in days
        for activity in day.activities
        if "bathroom" in activity.location_ids
    ]

    assert bathroom
    assert all(
        activity.extensions[PRIVACY_EXTENSION]
        == [item for item in ("r1", "r2") if item != activity.actor_id]
        for activity in bathroom
    )


def test_a_household_that_shares_its_bathroom_says_so_in_one_line(
    package: PersonalProcessPackage,
) -> None:
    """Permissive settings are chosen, never inherited — but choosing them is one field."""
    outline = _outline(
        world=_bathroom_world(),
        residents=_two_residents(),
        household=Household(shared_location_ids=["bathroom"]),
    )

    days = expand_outline(outline, package, seed=1).bundle.scenario.days

    assert _privacy_marks(days) == {}


def test_an_activity_names_each_object_it_holds_so_uses_are_serialised(
    package: PersonalProcessPackage,
) -> None:
    """Serialisation, not privacy: a bathroom the couple shares still has one toilet and one tap.

    The toilet trip names the toilet and the basin it washes its hands at, the television names
    the set it switches on, and a meal — which switches nothing and sits on a chair — names nothing.
    """
    world = _world().model_copy(
        update={
            "resources": [
                Resource(resource_id=resource_id, resource_type=kind, location_id=room)
                for resource_id, kind, room in CORE_RESOURCES
            ]
        }
    )
    outline = _outline(
        world=world,
        residents=_two_residents(),
        household=Household(shared_location_ids=["bathroom"]),
    )
    # The reference process models, because which object an activity holds is read off what its
    # process actually does; the module package points every intent at one breakfast.
    reference = [
        _retarget_reference(spec.intent_id, resident)
        for resident in ("r1", "r2")
        for spec in INTENT_CATALOG
    ]
    package = package.model_copy(
        update={
            "process_models": [*package.process_models, *reference],
            "bindings": [
                binding.model_copy(
                    update={"process_model_id": f"{binding.resident_id}__{binding.intent}"}
                )
                if binding.resident_id in {"r1", "r2"}
                and binding.intent in {spec.intent_id for spec in INTENT_CATALOG}
                else binding
                for binding in package.bindings
            ],
        }
    )

    days = expand_outline(outline, package, seed=1).bundle.scenario.days
    held: dict[str, list[set[str]]] = defaultdict(list)
    for day in days:
        for activity in day.activities:
            held[activity.intent].append({item.resource_id for item in activity.required_resources})

    assert held["use_toilet"]
    assert all(item == {"toilet_01", "washbasin_01"} for item in held["use_toilet"])
    assert all(item == {"television_01"} for item in held["watch_television"])
    assert all(item == set() for item in held["eat_dinner"])


def test_a_room_with_no_sanitary_fixture_is_not_private_by_default(
    package: PersonalProcessPackage,
) -> None:
    """Two people in a kitchen is ordinary, and a default that forbade it would be a fiction."""
    outline = _outline(world=_bathroom_world(), residents=_two_residents())

    days = expand_outline(outline, package, seed=1).bundle.scenario.days
    kitchen = [
        activity
        for day in days
        for activity in day.activities
        if activity.location_ids == ["kitchen"]
    ]

    assert kitchen
    assert all(PRIVACY_EXTENSION not in activity.extensions for activity in kitchen)


def test_a_directional_rule_reaches_one_way_only(package: PersonalProcessPackage) -> None:
    """Between a parent and a small child the norm is not reciprocal, and has to be sayable."""
    outline = _outline(
        residents=_two_residents(),
        household=Household(
            location_privacy=[
                LocationPrivacy(
                    location_id="living_room",
                    subject_id="r1",
                    excluded_resident_ids=["r2"],
                    symmetric=False,
                )
            ]
        ),
    )

    days = expand_outline(outline, package, seed=1).bundle.scenario.days

    assert _privacy_marks(days) == {"r1": {"r2"}}


def test_the_symmetric_shorthand_writes_the_rule_both_ways(
    package: PersonalProcessPackage,
) -> None:
    """Between two adults the norm is almost always reciprocal, and is written once."""
    outline = _outline(
        residents=_two_residents(),
        household=Household(
            location_privacy=[
                LocationPrivacy(
                    location_id="living_room", subject_id="r1", excluded_resident_ids=["r2"]
                )
            ]
        ),
    )

    days = expand_outline(outline, package, seed=1).bundle.scenario.days

    assert _privacy_marks(days) == {"r1": {"r2"}, "r2": {"r1"}}


def test_an_exclusive_sharing_policy_is_privacy_keyed_by_intent(
    package: PersonalProcessPackage,
) -> None:
    """The same statement from the other end: whichever room that intent happens in."""
    outline = _outline(
        residents=_two_residents(),
        household=Household(
            sharing_policies=[
                SharingPolicy(
                    between=["r1", "r2"],
                    intent="eat_breakfast",
                    sharing=SharingMode.exclusive,
                )
            ]
        ),
    )

    days = expand_outline(outline, package, seed=1).bundle.scenario.days
    marked = {
        activity.intent
        for day in days
        for activity in day.activities
        if PRIVACY_EXTENSION in activity.extensions
    }

    assert marked == {"eat_breakfast"}


def test_a_household_of_one_is_never_private_from_anybody(
    package: PersonalProcessPackage,
) -> None:
    """There is nobody to exclude, so the restrictive default has nothing to say."""
    days = expand_outline(_outline(world=_bathroom_world()), package, seed=1).bundle.scenario.days

    assert _privacy_marks(days) == {}


# --- the ambiguity share and the household document ---------------------------------------------


def test_a_household_of_one_has_nothing_to_be_ambiguous_with(
    package: PersonalProcessPackage,
) -> None:
    """Zero by construction, not by convention: there is nobody else in the room."""
    band = HabitSegment(
        habit_id="evening", label="Evening", window_start="18:00", window_end="23:00"
    )

    truth = expand_outline(_outline(habits=[band]), package, seed=1).planned_bands[0]

    assert truth.habits[0].ambiguous_minutes == 0.0
    assert truth.habits[0].ambiguous_share == 0.0


def test_a_shared_dinner_makes_the_evening_band_ambiguous(
    package: PersonalProcessPackage,
) -> None:
    """The number this whole level exists to publish, and the second axis of difficulty.

    A minute two bodies were both present for cannot be attributed by a log that does not
    distinguish bodies. Without saying how many such minutes a band holds, an algorithm failing on
    a crowded band and one failing on a noisy band report the same figure and mean different
    things.
    """
    band = HabitSegment(
        habit_id="evening_r2", label="Evening", window_start="18:00", window_end="23:00"
    )
    outline = _shared_couple()
    outline = outline.model_copy(
        update={
            "residents": [
                outline.residents[0],
                outline.residents[1].model_copy(update={"habits": [band]}),
            ]
        }
    )

    observation = expand_outline(outline, package, seed=1).planned_bands[1].habits[0]

    assert observation.resident_id == "r2"
    assert observation.ambiguous_minutes > 0
    assert 0 < observation.ambiguous_share <= 1


def test_every_band_says_whose_it_is(package: PersonalProcessPackage) -> None:
    """An export flattens both residents' bands into one table, and a row has to be readable."""
    band = HabitSegment(
        habit_id="evening", label="Evening", window_start="18:00", window_end="23:00"
    )
    outline = _outline(
        residents=[
            _resident(
                resident_id="r1",
                profile=_renamed(_profile(), "r1"),
                habits=[band.model_copy(update={"habit_id": "evening_r1"})],
            ),
            _resident(
                resident_id="r2",
                profile=_renamed(_profile(), "r2"),
                habits=[band.model_copy(update={"habit_id": "evening_r2"})],
            ),
        ]
    )

    truths = expand_outline(outline, package, seed=1).planned_bands

    assert [item.habits[0].resident_id for item in truths] == ["r1", "r2"]


def _household_of_plan(outline: HorizonOutline, package: PersonalProcessPackage) -> Any:
    """The household arithmetic run on an expansion's plan: the same code a run's export uses."""
    result = expand_outline(outline, package, seed=1)
    scenario = result.bundle.scenario
    evidence = evidence_from_plan(
        scenario.days,
        outline.resident_ids,
        started_at=scenario.simulation_window.start,
        ended_at=scenario.simulation_window.end,
    )
    return measure_household(result.declared_habits, evidence, external_locations=["outdoors"])


def test_the_household_document_names_the_rooms_they_shared(
    package: PersonalProcessPackage,
) -> None:
    """What N per-resident sheets cannot say: the two of them were in there at the same
    time."""
    household = _household_of_plan(_shared_couple(), package)

    assert household.resident_ids == ["r1", "r2"]
    assert household.co_presence
    assert all(len(item.resident_ids) == 2 for item in household.co_presence)
    assert all(item.minutes > 0 for item in household.co_presence)


def test_the_household_document_lists_each_shared_meal_once(
    package: PersonalProcessPackage,
) -> None:
    """A reader counting dinners gets dinners, not the number of people who ate one."""
    household = _household_of_plan(_shared_couple(), package)

    dinners = [item for item in household.shared_episodes if item.intent == "eat_dinner"]
    assert dinners
    assert all(item.participant_ids == ["r1", "r2"] for item in dinners)
    assert len({(item.day, item.activity_id) for item in dinners}) == len(dinners)


def test_a_household_of_one_publishes_an_empty_document_rather_than_none(
    package: PersonalProcessPackage,
) -> None:
    """Empty is the true answer, and it saves every consumer an existence check."""
    household = _household_of_plan(_outline(), package)

    assert household.resident_ids == ["resident"]
    assert household.co_presence == []
    assert household.shared_episodes == []
    assert household.days
    assert all(item.shared_minutes == {"resident": 0.0} for item in household.days)


def test_the_household_says_how_often_it_shared_against_how_often_it_said_it_would(
    package: PersonalProcessPackage,
) -> None:
    """Declared against realised, weekdays and weekends apart (§15.2).

    "Never in the week, always at the weekend" is two numbers and has to come back as two rows;
    one average of them would describe a household that does not exist. Counted over the days the
    dinner ran at all, together or apart, so the realised share is a fraction of days — the unit
    the propensity was declared in.
    """
    outline = _shared_couple(
        sharing=SharingMode.optional_joint,
        propensity=SharingPropensity(default=0.25, weekend=1.0),
    )
    days = expand_outline(outline, package, seed=1).bundle.scenario.days

    household = _household_of_plan(outline, package)
    rows = {item.day_class: item for item in household.sharing}

    assert set(rows) == {"weekday", "weekend"}
    assert rows["weekend"].declared_propensity == 1.0
    assert rows["weekday"].declared_propensity == 0.25
    assert rows["weekend"].realised_share == 1.0
    weekdays = [
        day for day in days if day.date.weekday() < 5 and _occurrences_of(day, "household_dinner")
    ]
    shared = [day for day in weekdays if len(_occurrences_of(day, "household_dinner")) == 1]
    assert rows["weekday"].days_with_occurrence == len(weekdays)
    assert rows["weekday"].days_shared == len(shared)
    assert 0 < rows["weekday"].days_shared < rows["weekday"].days_with_occurrence
    assert all(item.participant_ids == ["r1", "r2"] for item in household.sharing)


def test_only_the_declaration_travels_inside_the_scenario(
    package: PersonalProcessPackage,
) -> None:
    """The bands ride with the days; nothing measured does, because only a run can be measured.

    A measurement made at expansion is a measurement of the plan. Carried in the scenario it reached
    every export as the ground truth of a run it had never seen, which is the defect this replaces.
    """
    scenario = expand_outline(_shared_couple(), package, seed=1).bundle.scenario

    assert DECLARED_HABITS_EXTENSION in scenario.extensions
    assert "habitGroundTruths" not in scenario.extensions
    assert "householdGroundTruth" not in scenario.extensions


def test_the_wait_in_front_of_a_shared_meal_happens_where_the_meal_will(
    package: PersonalProcessPackage,
) -> None:
    """A wait is not a hole in the plan. It is time spent in the room the other one is coming to.

    Anchoring a shared activity to the last participant to become free produces the wait for free;
    what this covers is that the minutes are somewhere. Left in the catalog's default room they
    are what `behaviour.py` counts as long idle — a motionless body, which is what the replay
    shows and what makes the trace read as a dot on a sofa.
    """
    days = expand_outline(_shared_couple(), package, seed=1).bundle.scenario.days

    placed = []
    for day in days:
        for waiting_start, waiting_end, room in _waiting_rooms(day.activities):
            placed.extend(
                activity.location_ids[0] == room
                for activity in day.activities
                if FILL_LABEL in activity.labels
                and activity.start_window is not None
                and waiting_start <= activity.start_window.preferred < waiting_end
            )

    assert placed, "no filler landed inside a wait, so there is nothing to check"
    assert all(placed)


def test_a_filler_is_only_what_that_resident_can_perform(package: PersonalProcessPackage) -> None:
    """One housemate makes coffee and the other never does; the other is not handed a coffee.

    The fillable intents were read off the whole package, so a process only one of two people had
    was offered to both — and a month for a couple was refused 62 times over, for the one whose
    package had never mentioned it.
    """
    coffee = "prepare_and_drink_hot_drink"
    assert coffee in FILL_INTENTS
    partial = package.model_copy(
        update={
            "bindings": [
                item
                for item in package.bindings
                if not (item.resident_id == "r2" and item.intent == coffee)
            ]
        }
    )

    days = expand_outline(_couple(), partial, seed=1).bundle.scenario.days

    filled: dict[str, set[str]] = defaultdict(set)
    for day in days:
        for activity in day.activities:
            if FILL_LABEL in activity.labels:
                filled[activity.actor_id].add(activity.intent)
    assert coffee in filled["r1"]
    assert filled["r2"], "r2 received no filler at all, so there is nothing to check"
    assert coffee not in filled["r2"]


def test_no_wait_intent_is_coined(package: PersonalProcessPackage) -> None:
    """The catalogue is closed, and nobody waits — they do something else and watch the clock."""
    days = expand_outline(_shared_couple(), package, seed=1).bundle.scenario.days

    intents = {activity.intent for day in days for activity in day.activities}

    assert all(item in {spec.intent_id for spec in INTENT_CATALOG} for item in intents)


def test_a_degradable_meal_is_written_twice_and_chosen_once(
    package: PersonalProcessPackage,
) -> None:
    """The shared sitting and the two separate ones, in one group the compiler picks from."""
    days = expand_outline(
        _shared_couple(degrade_to_independent=True), package, seed=1
    ).bundle.scenario.days

    for day in days:
        dinners = _occurrences_of(day, "household_dinner")
        branches = {
            item.extensions[BRANCH_EXTENSION]["branch"]  # type: ignore[index,call-overload]
            for item in dinners
        }
        assert branches == {"joint", "separate"}
        groups = {
            item.extensions[BRANCH_EXTENSION]["group"]  # type: ignore[index,call-overload]
            for item in dinners
        }
        assert len(groups) == 1
        assert all(not item.mandatory for item in dinners)


def test_the_shared_arm_outweighs_both_halves_of_the_separate_one() -> None:
    """How "share it if it fits" is expressed: the objective's first stage, and nothing new."""
    assert JOINT_BRANCH_PRIORITY > 2 * SEPARATE_BRANCH_PRIORITY
    # Nothing in a household is binary: a family of four still eats together when it fits.
    for participants in (2, 3, 4, 6):
        assert participants * _separate_priority(participants) < JOINT_BRANCH_PRIORITY
    assert _separate_priority(2) == SEPARATE_BRANCH_PRIORITY


def test_a_degradable_meal_is_measured_on_its_shared_arm_only(
    package: PersonalProcessPackage,
) -> None:
    """Counting both arms would report a household eating twice as many dinners as it has."""
    band = HabitSegment(
        habit_id="evening_r1", label="Evening", window_start="18:00", window_end="23:00"
    )
    outline = _shared_couple(degrade_to_independent=True)
    outline = outline.model_copy(
        update={
            "residents": [
                outline.residents[0].model_copy(update={"habits": [band]}),
                outline.residents[1],
            ]
        }
    )

    truth = expand_outline(outline, package, seed=1).planned_bands[0]
    dinner = [row for row in truth.habits[0].composition if row.intent == "eat_dinner"]

    assert dinner
    # One dinner a day inside a five-hour band, not two.
    assert dinner[0].share < 0.5


def test_a_joint_activity_that_may_not_degrade_stays_one_interval(
    package: PersonalProcessPackage,
) -> None:
    """Turned off, a shared activity is one interval: the author chose squeeze over separate."""
    days = expand_outline(
        _shared_couple(degrade_to_independent=False), package, seed=1
    ).bundle.scenario.days

    for day in days:
        dinners = _occurrences_of(day, "household_dinner")
        assert len(dinners) == 1
        assert BRANCH_EXTENSION not in dinners[0].extensions


def test_the_expanded_household_is_a_valid_scenario(package: PersonalProcessPackage) -> None:
    """The guard that was missing: every expander test read the days and none validated them.

    `participantIds` names the people taking part *besides* the actor, and a joint activity that
    repeated its own actor there produced a scenario the contract rejects — through an expansion
    that looked right in every assertion about intents, rooms and counts.
    """
    from smart_home_sim.validation.service import validate_payload

    scenario = expand_outline(_shared_couple(), package, seed=1).bundle.scenario
    report = validate_payload(json.loads(scenario.model_dump_json(by_alias=True)))

    assert [item.code for item in report.issues] == []


def test_a_package_that_implements_the_household_for_one_resident_is_refused(
    package: PersonalProcessPackage,
) -> None:
    """A binding belongs to a person: dinner implemented for one of two is implemented for one."""
    one_sided = package.model_copy(
        update={"bindings": [item for item in package.bindings if item.resident_id != "r2"]}
    )

    with pytest.raises(ExpansionError, match="does not implement for 'r2'"):
        expand_outline(_shared_couple(), one_sided, seed=1)


def test_a_shared_arm_is_never_shorter_than_the_author_said_sharing_needs(
    package: PersonalProcessPackage,
) -> None:
    """Below `minimumSharedMinutes` it is not a shared meal, so the shared arm stops there.

    Without the floor the compiler never chose: a twelve-minute shared dinner is still a dinner, the
    objective prefers the shared arm, and degradation on or off served the same twelve minutes.
    """
    days = expand_outline(
        _shared_couple(degrade_to_independent=True, minimum_shared_minutes=25), package, seed=1
    ).bundle.scenario.days

    shared_arms = [
        item
        for day in days
        for item in _occurrences_of(day, "household_dinner")
        if item.extensions[BRANCH_EXTENSION]["branch"] == "joint"  # type: ignore[index,call-overload]
    ]
    assert shared_arms
    assert all(
        item.duration is not None and item.duration.minimum_minutes >= 25 for item in shared_arms
    )


def test_a_shared_activity_may_degrade_unless_the_author_says_otherwise() -> None:
    """On by default, now that the ground truth is measured on what the compiler chose."""
    assert _recurring_joint_default().degrade_to_independent is True


def _recurring_joint_default() -> JointActivity:
    return JointActivity(
        activity=_recurring("dinner", RecurringActivityKind.anchor, intent="eat_dinner"),
        participant_ids=["r1", "r2"],
    )


def test_the_package_is_told_the_version_of_the_scenario_it_could_not_have_seen(
    package: PersonalProcessPackage,
) -> None:
    """The scenario is built from the outline, so its version is the expander's to state.

    A model that was told `1.0.0` still wrote `2.0.0`, the outline's schema version, and the whole
    horizon was refused as targeting a different scenario. The identifier is not aligned: a package
    written for another outline is a real mistake, and stays one.
    """
    outline = _outline()
    guessed = package.model_copy(
        update={"source_scenario_id": outline.outline_id, "source_scenario_version": "2.0.0"}
    )

    bundle = expand_outline(outline, guessed, seed=1).bundle

    assert bundle.personal_process_package.source_scenario_version == bundle.scenario.schema_version
    elsewhere = guessed.model_copy(update={"source_scenario_id": "another_outline"})
    kept = expand_outline(outline, elsewhere, seed=1).bundle.personal_process_package
    assert (kept.source_scenario_id, kept.source_scenario_version) == ("another_outline", "2.0.0")
