"""Write the reference `horizon_outline` example: eight months of Meredith Merrino.

The persona facts are taken verbatim from the `authoringAssumptions` of the eight-month bundle
that motivated ADR-018, so the example and the artifact it replaces describe the same person.
That bundle spent 3 220 006 bytes stating those eight months day by day; this states them once.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from smart_home_sim.domain.models import (
    AuthorType,
    ExternalPerson,
    Location,
    LocationKind,
    Provenance,
    Resource,
    VersionedReference,
)
from smart_home_sim.hybrid_planning.outline import (
    ActivityDisplacement,
    ActivityOverride,
    Displacement,
    FixedCommitment,
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

ROOT = Path(__file__).parents[1]
EXAMPLE_PATH = ROOT / "examples/authoring/meredith.horizon-outline.json"
AUTHORED_AT = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
WEEKDAYS = [
    Weekday.monday,
    Weekday.tuesday,
    Weekday.wednesday,
    Weekday.thursday,
    Weekday.friday,
]


def _recurring(
    recurring_activity_id: str,
    label: str,
    kind: RecurringActivityKind,
    period: CadencePeriod,
    band: tuple[str, str],
    *,
    times: int = 1,
    every: int = 1,
    weekdays: list[Weekday] | None = None,
    jitter: int = 30,
    difficulty: str = "medium",
    intent: str | None = None,
    note: str = "",
) -> RecurringActivity:
    return RecurringActivity(
        recurring_activity_id=recurring_activity_id,
        label=label,
        kind=kind,
        mining_difficulty=difficulty,  # type: ignore[arg-type]
        intent=intent,
        note=note,
        cadence=ActivityCadence(
            period=period,
            times_per_period=times,
            every_n_periods=every,
            weekdays=weekdays or [],
            window_start=band[0],
            window_end=band[1],
            jitter_minutes=jitter,
        ),
    )


def build_profile() -> BehavioralProfile:
    recurring_activities = [
        _recurring(
            "morning_run",
            "Morning run",
            RecurringActivityKind.anchor,
            CadencePeriod.day,
            ("06:00", "08:00"),
            intent="evening_walk",
            jitter=25,
            difficulty="easy",
            note="Runs before work; the catalog has no running intent, the action kind carries it.",
        ),
        _recurring(
            "breakfast_at_home",
            "Breakfast at home",
            RecurringActivityKind.anchor,
            CadencePeriod.day,
            ("07:00", "09:00"),
            intent="eat_breakfast",
            jitter=20,
            difficulty="easy",
        ),
        _recurring(
            "dinner_at_home",
            "Dinner at home",
            RecurringActivityKind.anchor,
            CadencePeriod.day,
            ("19:30", "21:30"),
            intent="eat_dinner",
            jitter=35,
            difficulty="easy",
        ),
        _recurring(
            "grocery_shopping",
            "Grocery shopping",
            RecurringActivityKind.contextual,
            CadencePeriod.week,
            ("17:30", "19:30"),
            intent="buy_groceries",
            weekdays=[Weekday.wednesday, Weekday.saturday],
            difficulty="medium",
        ),
        _recurring(
            "laundry",
            "Laundry",
            RecurringActivityKind.contextual,
            CadencePeriod.week,
            ("18:00", "21:00"),
            intent="start_laundry",
            times=2,
            difficulty="medium",
        ),
        _recurring(
            "evening_television",
            "Evening television",
            RecurringActivityKind.optional,
            CadencePeriod.day,
            ("20:30", "23:00"),
            intent="watch_television",
            jitter=45,
            difficulty="hard",
            note="Skipped on late or social evenings; the softest signal in the profile.",
        ),
        _recurring(
            "aperitivo_with_friends",
            "Saturday aperitivo with friends",
            RecurringActivityKind.optional,
            CadencePeriod.week,
            ("18:30", "21:00"),
            intent="evening_walk",
            weekdays=[Weekday.saturday],
            difficulty="medium",
        ),
        _recurring(
            "long_phone_call_family",
            "Long call with family",
            RecurringActivityKind.rare,
            CadencePeriod.month,
            ("18:00", "21:00"),
            intent="phone_call",
            times=2,
            difficulty="hard",
        ),
    ]
    return BehavioralProfile(
        profile_id="meredith-merrino-profile-1",
        persona_id="meredith",
        recurring_activities=recurring_activities,
        provenance=Provenance(
            author_type=AuthorType.external_llm,
            generator_name="smart-home-simulator-external-llm-authoring",
            generator_version="1.4.0",
            model_name="GPT-5.6 Thinking",
            prompt_template_version="generate-horizon-outline-1.0.0",
            generated_at=AUTHORED_AT,
            human_reviewed=True,
        ),
    )


def build_world() -> OutlineWorld:
    # The activity catalog places every intent in one of these rooms, so the world has to
    # declare them under exactly these identifiers.
    rooms = ("bedroom", "bathroom", "kitchen", "living_room", "balcony")
    return OutlineWorld(
        home_model=VersionedReference(reference_id="synthetic-long-island-flat-1", version="1.0.0"),
        locations=[
            *(Location(location_id=room, kind=LocationKind.room) for room in rooms),
            Location(location_id="outdoors", kind=LocationKind.external),
            Location(location_id="outside_salon", kind=LocationKind.external),
            Location(
                location_id="home", kind=LocationKind.composite, member_location_ids=list(rooms)
            ),
        ],
        resources=[
            Resource(resource_id="kitchen_stove", resource_type="appliance", location_id="kitchen"),
            Resource(
                resource_id="washing_machine",
                resource_type="appliance",
                location_id="bathroom",
            ),
            Resource(
                resource_id="living_room_television",
                resource_type="appliance",
                location_id="living_room",
            ),
        ],
        external_people=[
            ExternalPerson(
                external_person_id="friend_group",
                display_name="Saturday friends",
                relationship_to_residents={"meredith": "friends"},
            )
        ],
        start_location_id="bedroom",
        resident_facts={"at_home": True, "posture": "lying"},
    )


def build_habits() -> list[HabitSegment]:
    """The bands of Meredith's day, in the literature's sense of the word.

    Deliberately uneven and with a gap over the working hours: she is out then, and time no band
    claims is simply unsegmented rather than forced into a tidy grid.
    """
    return [
        HabitSegment(
            habit_id="night",
            label="Night",
            window_start="22:30",
            window_end="06:00",
            note="Wraps past midnight, which only a habit band may do.",
        ),
        HabitSegment(
            habit_id="morning_routine",
            label="Morning routine",
            window_start="06:00",
            window_end="09:00",
            recurring_activity_ids=["morning_run", "breakfast_at_home"],
        ),
        HabitSegment(
            habit_id="late_afternoon",
            label="Late afternoon errands",
            window_start="17:00",
            window_end="19:30",
            recurring_activity_ids=["grocery_shopping", "laundry"],
        ),
        HabitSegment(
            habit_id="evening",
            label="Evening at home",
            window_start="19:30",
            window_end="22:30",
            recurring_activity_ids=[
                "dinner_at_home",
                "evening_television",
                "long_phone_call_family",
            ],
        ),
    ]


def build_outline() -> HorizonOutline:
    return HorizonOutline(
        outline_id="meredith-merrino-long-island-8-months-2026-2027",
        title="Meredith Merrino eight-month smart-home routine",
        resident_id="meredith",
        time_zone="America/New_York",
        start_date=date(2026, 8, 3),
        months=8,
        world=build_world(),
        profile=build_profile(),
        habits=build_habits(),
        fixed_commitments=[
            FixedCommitment(
                commitment_id="hair_salon_shift",
                label="Hair salon",
                intent="work_shift",
                weekdays=WEEKDAYS,
                start_time="09:00",
                end_time="17:00",
                note="Fixed by the employer, so the clock times are a fact about the world.",
            )
        ],
        phases=[
            OutlinePhase(
                phase_id="late_summer_heat",
                label="Late-summer heat",
                start_date=date(2026, 8, 3),
                end_date=date(2026, 9, 6),
                activity_overrides=[
                    ActivityOverride(
                        recurring_activity_id="morning_run",
                        cadence=ActivityCadence(
                            period=CadencePeriod.day,
                            times_per_period=1,
                            window_start="05:30",
                            window_end="07:00",
                            jitter_minutes=20,
                        ),
                    )
                ],
                note="Runs earlier to beat the heat.",
            ),
            OutlinePhase(
                phase_id="winter_indoors",
                label="Winter",
                start_date=date(2026, 12, 1),
                end_date=date(2027, 2, 28),
                activity_overrides=[
                    ActivityOverride(
                        recurring_activity_id="morning_run",
                        cadence=ActivityCadence(
                            period=CadencePeriod.week,
                            times_per_period=3,
                            window_start="06:30",
                            window_end="08:00",
                            jitter_minutes=30,
                        ),
                    ),
                    ActivityOverride(
                        recurring_activity_id="aperitivo_with_friends", suspended=True
                    ),
                ],
                note="Running drops to three times a week; the outdoor aperitivo stops.",
            ),
        ],
        events=[
            OutlineEvent(
                event_id="dentist_autumn",
                label="Dentist appointment",
                intent="evening_walk",
                earliest_date=date(2026, 10, 5),
                latest_date=date(2026, 10, 30),
                window_start="09:00",
                window_end="12:00",
                minimum_minutes=45,
                maximum_minutes=90,
                weekdays=WEEKDAYS,
                displaces=[ActivityDisplacement(recurring_activity_id="morning_run")],
            ),
            OutlineEvent(
                event_id="christmas_with_family",
                label="Christmas at her family's",
                intent="evening_walk",
                earliest_date=date(2026, 12, 24),
                latest_date=date(2026, 12, 26),
                occurrences=3,
                window_start="10:00",
                window_end="22:00",
                minimum_minutes=300,
                maximum_minutes=600,
                displaces=[
                    ActivityDisplacement(recurring_activity_id="dinner_at_home"),
                    ActivityDisplacement(recurring_activity_id="evening_television"),
                ],
                note="Three consecutive days away; the home routine is displaced, not varied.",
            ),
            OutlineEvent(
                event_id="flu_week",
                label="A week of flu",
                intent="rest_or_nap",
                earliest_date=date(2027, 1, 11),
                latest_date=date(2027, 1, 17),
                occurrences=5,
                window_start="08:00",
                window_end="20:00",
                minimum_minutes=240,
                maximum_minutes=600,
                displaces=[
                    ActivityDisplacement(recurring_activity_id="morning_run"),
                    ActivityDisplacement(
                        recurring_activity_id="grocery_shopping", policy=Displacement.reschedule
                    ),
                ],
                note="The kind of disruption a recogniser should survive without unlearning.",
            ),
            OutlineEvent(
                event_id="spring_weekend_away",
                label="Weekend away",
                intent="evening_walk",
                earliest_date=date(2027, 3, 5),
                latest_date=date(2027, 3, 28),
                occurrences=2,
                window_start="09:00",
                window_end="21:00",
                minimum_minutes=480,
                maximum_minutes=720,
                weekdays=[Weekday.saturday, Weekday.sunday],
                displaces=[
                    ActivityDisplacement(recurring_activity_id="dinner_at_home"),
                    ActivityDisplacement(
                        recurring_activity_id="laundry", policy=Displacement.reschedule
                    ),
                ],
            ),
        ],
        provenance=Provenance(
            author_type=AuthorType.external_llm,
            generator_name="smart-home-simulator-external-llm-authoring",
            generator_version="1.4.0",
            model_name="GPT-5.6 Thinking",
            prompt_template_version="generate-horizon-outline-1.0.0",
            generated_at=AUTHORED_AT,
            human_reviewed=True,
            parameters={
                "authoringAssumptions": [
                    "Meredith lives alone in a synthetic large Long Island flat.",
                    "Her work schedule is Monday to Friday, 09:00 to 17:00, at a nearby salon.",
                    "The morning run maps to the evening_walk intent; the action kind is running.",
                    "Concrete daily times, sleep debt and drive dynamics are the expander's job.",
                ]
            },
        ),
        note="Structure only: no day of this horizon is described here.",
    )


def main() -> None:
    outline = build_outline()
    EXAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(outline.model_dump_json(by_alias=True))
    EXAMPLE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Wrote {EXAMPLE_PATH.relative_to(ROOT)} ({EXAMPLE_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
