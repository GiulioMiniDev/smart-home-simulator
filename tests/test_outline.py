from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import (
    AuthorType,
    Location,
    LocationKind,
    Provenance,
    Resource,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.cadence import add_months, build_cadence_calendar
from smart_home_sim.hybrid_planning.outline import (
    ActivityDisplacement,
    ActivityOverride,
    Displacement,
    FixedCommitment,
    HabitSegment,
    HorizonAuthoringBundle,
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
from tools.build_outline_example import build_outline

_NOW = datetime(2026, 8, 2, 11, 54, tzinfo=UTC)
_START = date(2026, 8, 3)  # a Monday
_MONTHS = 8


def _recurring(
    recurring_activity_id: str, kind: RecurringActivityKind = RecurringActivityKind.anchor
) -> RecurringActivity:
    return RecurringActivity(
        recurring_activity_id=recurring_activity_id,
        label=recurring_activity_id,
        kind=kind,
        cadence=ActivityCadence(
            period=CadencePeriod.day,
            times_per_period=1,
            window_start="08:00",
            window_end="09:00",
        ),
    )


def _profile() -> BehavioralProfile:
    kinds = (
        (RecurringActivityKind.anchor, 3),
        (RecurringActivityKind.contextual, 2),
        (RecurringActivityKind.optional, 2),
        (RecurringActivityKind.rare, 1),
    )
    recurring_activities = [
        _recurring(f"{kind.value}_{index}", kind) for kind, count in kinds for index in range(count)
    ]
    return BehavioralProfile(
        profile_id="meredith_profile",
        persona_id="meredith",
        recurring_activities=recurring_activities,
        provenance=Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    )


def _world() -> OutlineWorld:
    return OutlineWorld(
        home_model=VersionedReference(reference_id="synthetic-flat", version="1.0.0"),
        locations=[
            Location(location_id="home_bedroom", kind=LocationKind.room),
            Location(location_id="home_kitchen", kind=LocationKind.room),
            Location(
                location_id="home",
                kind=LocationKind.composite,
                member_location_ids=["home_bedroom", "home_kitchen"],
            ),
        ],
        resources=[
            Resource(resource_id="stove", resource_type="appliance", location_id="home_kitchen")
        ],
        start_location_id="home_bedroom",
    )


def _outline(**overrides: Any) -> HorizonOutline:
    fields: dict[str, Any] = {
        "outline_id": "meredith-8-months",
        "title": "Meredith Merrino eight-month routine",
        "resident_id": "meredith",
        "time_zone": "America/New_York",
        "start_date": _START,
        "months": _MONTHS,
        "world": _world(),
        "profile": _profile(),
        "provenance": Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    }
    fields.update(overrides)
    return HorizonOutline(**fields)


def _phase(**overrides: Any) -> OutlinePhase:
    fields: dict[str, Any] = {
        "phase_id": "autumn_course",
        "label": "Evening course",
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 12, 15),
    }
    fields.update(overrides)
    return OutlinePhase(**fields)


def _event(**overrides: Any) -> OutlineEvent:
    fields: dict[str, Any] = {
        "event_id": "dentist",
        "label": "Dentist appointment",
        "earliest_date": date(2026, 9, 1),
        "latest_date": date(2026, 9, 30),
    }
    fields.update(overrides)
    return OutlineEvent(**fields)


def test_minimal_outline_is_accepted() -> None:
    outline = _outline()

    assert outline.document_type == "horizon_outline"
    assert outline.schema_version == "1.0.0"
    assert outline.end_date == add_months(_START, _MONTHS)


def test_end_date_agrees_with_the_cadence_calendar() -> None:
    """The outline and the expander must not disagree about where the horizon stops."""
    outline = _outline()

    calendar = build_cadence_calendar(
        outline.profile, start_date=outline.start_date, months=outline.months, seed=0
    ).calendar

    assert len(calendar.days) == (outline.end_date - outline.start_date).days


def test_outline_carries_no_absolute_instant() -> None:
    """ADR-018 constraint 1 is structural: no field of this contract can hold a timestamp."""
    payload = json.loads(
        _outline(
            fixed_commitments=[
                FixedCommitment(
                    commitment_id="salon",
                    label="Hair salon",
                    weekdays=[Weekday.monday, Weekday.friday],
                    start_time="09:00",
                    end_time="17:00",
                )
            ],
            phases=[_phase()],
            events=[_event()],
        ).model_dump_json(by_alias=True)
    )

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            # Provenance records when the document was authored, which is metadata about the
            # outline rather than a moment inside the horizon it describes.
            for key, value in node.items():
                if key != "provenance":
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            assert "T" not in node or not node[:4].isdigit(), f"{path} looks like an instant"

    walk(payload, "$")


def test_phase_outside_the_horizon_is_rejected() -> None:
    with pytest.raises(ValidationError, match="falls outside the horizon"):
        _outline(phases=[_phase(start_date=date(2026, 7, 1), end_date=date(2026, 7, 20))])


def test_phase_ending_before_it_starts_is_rejected() -> None:
    with pytest.raises(ValidationError, match="ends before it starts"):
        _phase(start_date=date(2026, 12, 1), end_date=date(2026, 10, 1))


def test_phase_overriding_an_unknown_activity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="overrides unknown activity"):
        _outline(
            phases=[
                _phase(
                    activity_overrides=[
                        ActivityOverride(recurring_activity_id="ghost", suspended=True)
                    ]
                )
            ]
        )


def test_override_must_suspend_or_replace() -> None:
    with pytest.raises(ValidationError, match="either suspend the activity or replace"):
        ActivityOverride(recurring_activity_id="anchor_0")


def test_override_cannot_suspend_and_replace_at_once() -> None:
    with pytest.raises(ValidationError, match="cannot also declare a replacement cadence"):
        ActivityOverride(
            recurring_activity_id="anchor_0",
            suspended=True,
            cadence=ActivityCadence(
                period=CadencePeriod.week,
                times_per_period=1,
                window_start="18:00",
                window_end="20:00",
            ),
        )


def test_overlapping_phases_may_not_override_the_same_habit() -> None:
    """A silent winner between two overrides is the defect class this contract exists to remove."""
    first = _phase(
        phase_id="course",
        activity_overrides=[ActivityOverride(recurring_activity_id="optional_0", suspended=True)],
    )
    second = _phase(
        phase_id="holiday",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 31),
        activity_overrides=[ActivityOverride(recurring_activity_id="optional_0", suspended=True)],
    )

    with pytest.raises(ValidationError, match="overlap and both override"):
        _outline(phases=[first, second])


def test_disjoint_phases_may_override_the_same_habit() -> None:
    first = _phase(
        phase_id="course",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 11, 30),
        activity_overrides=[ActivityOverride(recurring_activity_id="optional_0", suspended=True)],
    )
    second = _phase(
        phase_id="holiday",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 31),
        activity_overrides=[ActivityOverride(recurring_activity_id="optional_0", suspended=True)],
    )

    assert len(_outline(phases=[first, second]).phases) == 2


def test_event_window_narrower_than_its_occurrences_is_rejected() -> None:
    with pytest.raises(ValidationError, match="occurrences"):
        _event(
            earliest_date=date(2026, 9, 1),
            latest_date=date(2026, 9, 2),
            occurrences=5,
        )


def test_event_with_an_inverted_duration_range_is_rejected() -> None:
    with pytest.raises(ValidationError, match="inverted duration range"):
        _event(minimum_minutes=120, maximum_minutes=30)


def test_event_with_an_inverted_time_band_is_rejected() -> None:
    with pytest.raises(ValidationError, match="start must be before end"):
        _event(window_start="22:00", window_end="08:00")


def test_event_time_band_must_be_hh_mm() -> None:
    with pytest.raises(ValidationError, match="must be HH:MM"):
        _event(window_start="8am", window_end="10am")


def test_event_pinned_to_a_single_day_is_accepted() -> None:
    """`earliest == latest` is how a genuinely fixed date is expressed."""
    event = _event(earliest_date=date(2026, 9, 14), latest_date=date(2026, 9, 14))

    assert event.occurrences == 1


def test_event_displacing_an_unknown_activity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="displaces unknown activity"):
        _outline(events=[_event(displaces=[ActivityDisplacement(recurring_activity_id="ghost")])])


def test_commitment_is_the_only_place_clock_times_appear() -> None:
    commitment = FixedCommitment(
        commitment_id="salon",
        label="Hair salon",
        weekdays=[Weekday.monday, Weekday.tuesday],
        start_time="09:00",
        end_time="17:00",
    )

    assert commitment.start_time == "09:00"


def test_commitment_with_an_inverted_span_is_rejected() -> None:
    with pytest.raises(ValidationError, match="start must be before end"):
        FixedCommitment(
            commitment_id="salon",
            label="Hair salon",
            weekdays=[Weekday.monday],
            start_time="17:00",
            end_time="09:00",
        )


def test_commitment_repeating_a_weekday_is_rejected() -> None:
    with pytest.raises(ValidationError, match="repeats a weekday"):
        FixedCommitment(
            commitment_id="salon",
            label="Hair salon",
            weekdays=[Weekday.monday, Weekday.monday],
            start_time="09:00",
            end_time="17:00",
        )


def test_duplicate_identifiers_are_rejected() -> None:
    with pytest.raises(ValidationError, match="event identifiers must be unique"):
        _outline(events=[_event(), _event()])


def test_unknown_time_zone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown time zone"):
        _outline(time_zone="Mars/Olympus_Mons")


def test_outline_round_trips_through_json() -> None:
    outline = _outline(
        fixed_commitments=[
            FixedCommitment(
                commitment_id="salon",
                label="Hair salon",
                weekdays=[Weekday.monday],
                start_time="09:00",
                end_time="17:00",
            )
        ],
        phases=[
            _phase(
                activity_overrides=[
                    ActivityOverride(recurring_activity_id="optional_0", suspended=True)
                ]
            )
        ],
        events=[_event()],
    )

    restored = HorizonOutline.model_validate_json(outline.model_dump_json(by_alias=True))

    assert restored == outline


def test_one_event_may_skip_one_habit_and_reschedule_another() -> None:
    """The flu week is the case that forced the policy down to the activity."""
    event = _event(
        displaces=[
            ActivityDisplacement(recurring_activity_id="anchor_0"),
            ActivityDisplacement(
                recurring_activity_id="contextual_0", policy=Displacement.reschedule
            ),
        ]
    )

    assert [item.policy for item in event.displaces] == [
        Displacement.skip,
        Displacement.reschedule,
    ]


def test_displacement_defaults_to_skip() -> None:
    assert ActivityDisplacement(recurring_activity_id="anchor_0").policy is Displacement.skip


def test_event_repeating_a_displaced_habit_is_rejected() -> None:
    with pytest.raises(ValidationError, match="repeats a displaced activity"):
        _event(
            displaces=[
                ActivityDisplacement(recurring_activity_id="anchor_0"),
                ActivityDisplacement(
                    recurring_activity_id="anchor_0", policy=Displacement.reschedule
                ),
            ]
        )


def test_world_rejects_a_resource_in_an_unknown_location() -> None:
    with pytest.raises(ValidationError, match="sits in unknown location"):
        OutlineWorld(
            home_model=VersionedReference(reference_id="synthetic-flat", version="1.0.0"),
            locations=[Location(location_id="home_bedroom", kind=LocationKind.room)],
            resources=[
                Resource(resource_id="stove", resource_type="appliance", location_id="home_kitchen")
            ],
            start_location_id="home_bedroom",
        )


def test_world_rejects_a_composite_with_an_unknown_member() -> None:
    with pytest.raises(ValidationError, match="references unknown member"):
        OutlineWorld(
            home_model=VersionedReference(reference_id="synthetic-flat", version="1.0.0"),
            locations=[
                Location(location_id="home_bedroom", kind=LocationKind.room),
                Location(
                    location_id="home",
                    kind=LocationKind.composite,
                    member_location_ids=["home_attic"],
                ),
            ],
            start_location_id="home_bedroom",
        )


def test_world_rejects_starting_inside_a_composite() -> None:
    """A resident stands in a room, not in the union of rooms."""
    with pytest.raises(ValidationError, match="not a declared primitive location"):
        OutlineWorld(
            home_model=VersionedReference(reference_id="synthetic-flat", version="1.0.0"),
            locations=[
                Location(location_id="home_bedroom", kind=LocationKind.room),
                Location(
                    location_id="home",
                    kind=LocationKind.composite,
                    member_location_ids=["home_bedroom"],
                ),
            ],
            start_location_id="home",
        )


def test_world_rejects_duplicate_location_identifiers() -> None:
    with pytest.raises(ValidationError, match="location identifiers must be unique"):
        OutlineWorld(
            home_model=VersionedReference(reference_id="synthetic-flat", version="1.0.0"),
            locations=[
                Location(location_id="home_bedroom", kind=LocationKind.room),
                Location(location_id="home_bedroom", kind=LocationKind.room),
            ],
            start_location_id="home_bedroom",
        )


def test_authoring_bundle_carries_the_outline_and_the_package() -> None:
    """The envelope is what the external model returns; both halves are O(1) in the horizon."""
    minimal = json.loads(
        (Path(__file__).parents[1] / "examples/authoring/minimal.authoring-bundle.json").read_text(
            encoding="utf-8"
        )
    )
    package = PersonalProcessPackage.model_validate_json(
        json.dumps(minimal["personalProcessPackage"])
    )

    bundle = HorizonAuthoringBundle(outline=_outline(), personal_process_package=package)
    restored = HorizonAuthoringBundle.model_validate_json(bundle.model_dump_json(by_alias=True))

    assert restored == bundle
    assert bundle.document_type == "horizon_authoring_bundle"


def test_reference_example_is_valid_and_small() -> None:
    """The published example must load, and must stay the size of a structure, not a horizon."""
    path = Path(__file__).parents[1] / "examples/authoring/meredith.horizon-outline.json"

    outline = HorizonOutline.model_validate_json(path.read_text(encoding="utf-8"))

    assert outline.resident_id == "meredith"
    assert outline.months == 8
    assert outline.end_date == date(2027, 4, 3)
    assert outline.provenance.human_reviewed is True
    # The bundle it replaces described the same eight months in 3 220 006 bytes.
    assert path.stat().st_size < 16 * 1024


def test_reference_example_matches_its_builder() -> None:
    """The example is generated, so it cannot drift away from the contract it illustrates."""
    path = Path(__file__).parents[1] / "examples/authoring/meredith.horizon-outline.json"

    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(
        build_outline().model_dump_json(by_alias=True)
    )


def test_outline_stays_small_across_horizon_lengths() -> None:
    """Nothing in the contract grows with the number of days; that is its whole point.

    The eight-month bundle this contract replaces weighed 3 220 006 bytes, 98.2% of it days.
    """
    eight_months = len(_outline(months=8).model_dump_json(by_alias=True))
    five_years = len(_outline(months=60).model_dump_json(by_alias=True))

    # Only the digits of `months` differ; the horizon contributes nothing else.
    assert five_years - eight_months == len("60") - len("8")
    assert eight_months < 4096


def test_habit_bands_may_not_overlap() -> None:
    """A segmentation that assigned one minute to two bins would not be a segmentation."""
    with pytest.raises(ValidationError, match="overlap in the day"):
        _outline(
            habits=[
                HabitSegment(
                    habit_id="morning", label="Morning", window_start="06:00", window_end="10:00"
                ),
                HabitSegment(
                    habit_id="brunch", label="Brunch", window_start="09:00", window_end="11:00"
                ),
            ]
        )


def test_only_a_habit_band_may_cross_midnight() -> None:
    night = HabitSegment(habit_id="night", label="Night", window_start="22:30", window_end="06:15")

    assert night.crosses_midnight
    assert night.minute_spans() == [(22 * 60 + 30, 24 * 60), (0, 6 * 60 + 15)]


def test_a_habit_band_listing_an_unknown_activity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="lists unknown activity"):
        _outline(
            habits=[
                HabitSegment(
                    habit_id="morning",
                    label="Morning",
                    window_start="06:00",
                    window_end="10:00",
                    recurring_activity_ids=["ghost"],
                )
            ]
        )


def test_an_empty_habit_band_is_rejected() -> None:
    with pytest.raises(ValidationError, match="empty band"):
        HabitSegment(habit_id="x", label="X", window_start="08:00", window_end="08:00")


def test_the_reference_example_declares_habit_bands() -> None:
    """The example is what a reader copies, so it must show the concept, not just allow it."""
    path = Path(__file__).parents[1] / "examples/authoring/meredith.horizon-outline.json"

    outline = HorizonOutline.model_validate_json(path.read_text(encoding="utf-8"))

    assert len(outline.habits) >= 3
    assert any(segment.crosses_midnight for segment in outline.habits)
