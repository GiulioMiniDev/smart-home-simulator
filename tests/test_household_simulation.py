"""A shared house, simulated: every body a shared activity occupies is moved, seated and observed.

The compiler has always occupied every participant of an activity. The engine did not: it ran the
actor's process model and nothing else, so at a couple's dinner the actor sat down in the kitchen
and the other resident stayed in the sitting room — three evenings out of three, in the trace, the
sensor log and the replay alike. These tests run one real day of a two-resident household through
materialization, compilation, simulation and realistic sensor projection, and read the result back.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from smart_home_sim.cli import app
from smart_home_sim.domain.behavior import (
    BehaviorCatalogReferences,
    CatalogReference,
    PersonalProcessPackage,
    ProcessBinding,
    ProcessNode,
)
from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.domain.execution import (
    ActivityExecution,
    ExecutionTrace,
    semantic_activity_executions,
)
from smart_home_sim.domain.materialization import SensorDeploymentPolicy
from smart_home_sim.domain.models import (
    PRIVACY_EXTENSION,
    AuthorType,
    Location,
    LocationKind,
    Provenance,
    Resource,
    Scenario,
    SimulationWindow,
    VersionedReference,
)
from smart_home_sim.domain.plan import CanonicalActivity
from smart_home_sim.hybrid_planning.dwelling import CORE_RESOURCES
from smart_home_sim.hybrid_planning.expander import expand_outline
from smart_home_sim.hybrid_planning.habits import evidence_from_trace, ground_truth_of_run
from smart_home_sim.hybrid_planning.intents import INTENT_CATALOG
from smart_home_sim.hybrid_planning.outline import (
    HabitSegment,
    HorizonOutline,
    Household,
    HouseholdRelation,
    JointActivity,
    OutlineResident,
    OutlineWorld,
    RelationKind,
)
from smart_home_sim.hybrid_planning.package_authoring import (
    ACTION_CATALOG_VERSION,
    ACTIVITY_CATALOG_VERSION,
    VARIABLE_CATALOG_VERSION,
    _retarget_reference,
)
from smart_home_sim.hybrid_planning.recurring_activities import (
    ActivityCadence,
    BehavioralProfile,
    CadencePeriod,
    RecurringActivity,
    RecurringActivityKind,
)
from smart_home_sim.materialization import materialize_workspace
from smart_home_sim.profiling.builder import OCCUPYING_STATUSES
from smart_home_sim.sensors.service import _motion_pulses
from smart_home_sim.simulation.service import (
    OPENABLE_WAIT_LIMIT_SECONDS,
    SHARED_WAIT_SHORT_SECONDS,
    simulate_bundle,
    validate_execution_trace,
)

_NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
_RESIDENTS = ("luca", "marco")
_ROOMS = ("bedroom", "bathroom", "kitchen", "living_room", "balcony")


def _recurring(
    activity_id: str,
    kind: RecurringActivityKind,
    band: tuple[str, str],
    intent: str,
    *,
    period: CadencePeriod = CadencePeriod.day,
) -> RecurringActivity:
    return RecurringActivity(
        recurring_activity_id=activity_id,
        label=activity_id,
        kind=kind,
        intent=intent,
        cadence=ActivityCadence(
            period=period,
            times_per_period=1,
            window_start=band[0],
            window_end=band[1],
            jitter_minutes=20,
        ),
    )


def _profile(resident: str) -> BehavioralProfile:
    spec = [
        ("wash", RecurringActivityKind.anchor, ("07:00", "09:00"), "morning_toilet_and_wash"),
        ("breakfast", RecurringActivityKind.anchor, ("08:00", "10:00"), "eat_breakfast"),
        ("read", RecurringActivityKind.anchor, ("10:00", "12:00"), "read_and_rest"),
        ("lunch", RecurringActivityKind.contextual, ("12:30", "14:00"), "eat_lunch"),
        ("tidy", RecurringActivityKind.contextual, ("15:00", "17:00"), "clean_kitchen"),
        ("call", RecurringActivityKind.optional, ("17:00", "18:30"), "phone_call"),
        ("hygiene", RecurringActivityKind.optional, ("22:40", "23:30"), "evening_hygiene"),
        ("batch_cook", RecurringActivityKind.rare, ("11:00", "12:30"), "weekly_meal_preparation"),
    ]
    return BehavioralProfile(
        profile_id=f"profile_{resident}",
        persona_id=resident,
        recurring_activities=[
            _recurring(
                f"{name}_{resident}",
                kind,
                band,
                intent,
                period=CadencePeriod.week if name == "batch_cook" else CadencePeriod.day,
            )
            for name, kind, band, intent in spec
        ],
        provenance=Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    )


def _bands(resident: str) -> list[HabitSegment]:
    """Four bands that divide the day between them, the evening holding the shared dinner."""
    return [
        HabitSegment(habit_id=f"{name}_{resident}", label=name, window_start=start, window_end=end)
        for name, start, end in (
            ("night", "22:40", "07:00"),
            ("morning", "07:00", "12:00"),
            ("afternoon", "12:00", "18:00"),
            ("evening", "18:00", "22:40"),
        )
    ]


def _package() -> PersonalProcessPackage:
    """The reference models, once per resident: a package is personal, per resident."""
    models = []
    bindings = []
    for resident in _RESIDENTS:
        for spec in INTENT_CATALOG:
            model = _retarget_reference(spec.intent_id, resident)
            models.append(model)
            bindings.append(
                ProcessBinding(
                    binding_id=f"{resident}__{spec.intent_id}",
                    resident_id=resident,
                    intent=spec.intent_id,
                    process_model_id=model.process_model_id,
                )
            )
    return PersonalProcessPackage(
        package_id="household",
        package_version="1.0.0",
        source_scenario_id="household",
        source_scenario_version="1.0.0",
        language="en",
        provenance=Provenance(
            author_type=AuthorType.rule_generator,
            generator_name="test_household_simulation",
            generator_version="1.0.0",
            generated_at=_NOW,
        ),
        catalogs=BehaviorCatalogReferences(
            activity_catalog=CatalogReference(
                catalog_id="smart_home_activity_catalog", version=ACTIVITY_CATALOG_VERSION
            ),
            variable_catalog=CatalogReference(
                catalog_id="smart_home_variable_catalog", version=VARIABLE_CATALOG_VERSION
            ),
            action_catalog=CatalogReference(
                catalog_id="smart_home_action_catalog", version=ACTION_CATALOG_VERSION
            ),
        ),
        process_models=models,
        bindings=bindings,
    )


def _outline() -> HorizonOutline:
    return HorizonOutline(
        outline_id="household",
        title="A couple",
        time_zone="Europe/Rome",
        start_date=date(2026, 9, 1),
        months=1,
        world=OutlineWorld(
            home_model=VersionedReference(reference_id="synthetic", version="1.0.0"),
            locations=[
                *(Location(location_id=room, kind=LocationKind.room) for room in _ROOMS),
                Location(location_id="outdoors", kind=LocationKind.external),
            ],
            # A furnished flat for two: a toilet and a shower make the bathroom a shared one by
            # default, so the morning washes meet at the one basin, and the kitchen table has a
            # chair for each of them.
            resources=[
                *(
                    Resource(resource_id=resource_id, resource_type=kind, location_id=room)
                    for resource_id, kind, room in CORE_RESOURCES
                ),
                Resource(
                    resource_id="kitchen_chair_02", resource_type="chair", location_id="kitchen"
                ),
            ],
            start_location_id="bedroom",
        ),
        residents=[
            OutlineResident(
                resident_id=resident, profile=_profile(resident), habits=_bands(resident)
            )
            for resident in _RESIDENTS
        ],
        household=Household(
            relations=[HouseholdRelation(between=list(_RESIDENTS), kind=RelationKind.couple)],
            joint_activities=[
                JointActivity(
                    activity=_recurring(
                        "dinner",
                        RecurringActivityKind.anchor,
                        ("19:00", "21:00"),
                        "eat_dinner",
                    ),
                    participant_ids=list(_RESIDENTS),
                ),
                JointActivity(
                    activity=_recurring(
                        "television",
                        RecurringActivityKind.anchor,
                        ("21:00", "22:30"),
                        "watch_television",
                    ),
                    participant_ids=list(_RESIDENTS),
                ),
            ],
        ),
        provenance=Provenance(author_type=AuthorType.external_llm, generated_at=_NOW),
    )


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One day of the couple, plus the truncatable day its last evening spills into."""
    return materialized_run(_outline(), tmp_path_factory.mktemp("household"))


def materialized_run(
    outline: HorizonOutline, root: Path, package: PersonalProcessPackage | None = None
) -> Path:
    """Expand, cut to two days, and materialize with the sensors the application runs with."""
    package = package or _package()
    scenario = expand_outline(outline, package, seed=1).bundle.scenario
    days = scenario.days[:2]
    # Both morning washes asked for the same minutes, in a bathroom with one basin. Left to the
    # wobble they happened not to meet on this seed, and the day that stopped the run was the one
    # where they did: the second tap failed `sink_faucet.active`.
    washes = [item for item in days[0].activities if item.intent == "morning_toilet_and_wash"]
    later = max(washes, key=lambda item: str(item.start_window.preferred)).start_window
    days = [
        days[0].model_copy(
            update={
                "activities": [
                    item.model_copy(update={"start_window": later})
                    if item.intent == "morning_toilet_and_wash"
                    else item
                    for item in days[0].activities
                ]
            }
        ),
        days[1],
    ]
    days = [
        days[0],
        days[1].model_copy(
            update={
                "activities": [
                    item.model_copy(update={"allow_boundary_truncation": True, "mandatory": False})
                    for item in days[1].activities
                ]
            }
        ),
    ]
    tz = days[0].activities[0].start_window.preferred.tzinfo  # type: ignore[union-attr]
    window = SimulationWindow(
        start=datetime.combine(days[0].date, time.min, tz),
        end=datetime.combine(days[-1].date + timedelta(days=1), time.min, tz),
    )
    scenario = scenario.model_copy(
        update={
            "days": days,
            "simulation_window": window,
            "initial_state": scenario.initial_state.model_copy(update={"at": window.start}),
        }
    )
    (root / "scenario.json").write_text(scenario.model_dump_json(by_alias=True), encoding="utf-8")
    (root / "package.json").write_text(package.model_dump_json(by_alias=True), encoding="utf-8")
    # The policy the application runs with: realistic sensors, whose reconciliation is where two
    # bodies in one cone become one observation.
    materialize_workspace(
        root / "scenario.json",
        root / "package.json",
        root / "run",
        sensor_policy=SensorDeploymentPolicy.realistic(),
    )
    return root / "run"


@pytest.fixture(scope="module")
def trace(run: Path) -> ExecutionTrace:
    return ExecutionTrace.model_validate_json(
        (run / "execution-trace.json").read_text(encoding="utf-8")
    )


def _shared(trace: ExecutionTrace) -> list[ActivityExecution]:
    return [
        item
        for item in trace.activity_executions
        if item.participant_ids and item.status != "dropped"
    ]


def _region_at(trace: ExecutionTrace, resident: str, moment: datetime) -> str | None:
    region = None
    for movement in sorted(trace.movements, key=lambda item: item.ended_at):
        if movement.actor_id != resident:
            continue
        if movement.ended_at > moment:
            break
        region = movement.destination_region_id
    return region


def test_a_shared_activity_names_everyone_who_took_part(trace: ExecutionTrace) -> None:
    """One execution, every participant named: a diary listing it per person would count double."""
    shared = _shared(trace)

    assert {item.intent for item in shared} == {"eat_dinner", "watch_television"}
    for item in shared:
        assert sorted([item.actor_id, *item.participant_ids]) == list(_RESIDENTS)


def test_every_participant_is_in_the_room_the_actor_is_in(trace: ExecutionTrace) -> None:
    """The defect this exists for: the actor at the table and the other one in the sitting room."""
    for item in _shared(trace):
        middle = item.actual_start + (item.actual_end - item.actual_start) / 2
        rooms = {resident: _region_at(trace, resident, middle) for resident in _RESIDENTS}
        assert len(set(rooms.values())) == 1, (item.intent, item.actual_start, rooms)


def test_a_participant_walks_and_sits_under_the_shared_execution(trace: ExecutionTrace) -> None:
    """Her steps are ordinary actions, filed where the invariants look, under her own id."""
    actions = {item.action_execution_id: item for item in trace.action_executions}
    for item in _shared(trace):
        participant_actions = [
            actions[action_id]
            for action_id in item.action_execution_ids
            if actions[action_id].actor_id in item.participant_ids
        ]
        assert participant_actions, (item.intent, item.actual_start)
        assert all(
            action.activity_execution_id == item.activity_execution_id
            for action in participant_actions
        )


def test_two_bodies_never_rest_on_the_same_place(trace: ExecutionTrace) -> None:
    """A chair somebody is sitting on is not the nearest free seat."""
    current: dict[str, Any] = {}
    for transition in sorted(trace.state_transitions, key=lambda item: item.at):
        if transition.subject_type != "resident" or transition.fact != "resting_at":
            continue
        current[transition.subject_id] = transition.value
        places = [
            (value["regionId"], round(value["x"], 3), round(value["y"], 3))
            for value in current.values()
            if isinstance(value, dict)
        ]
        assert len(places) == len(set(places)), (transition.at, current)


# --- one object, one use at a time ----------------------------------------------------------------


def _held_resources(run: Path) -> dict[str, set[str]]:
    scenario = Scenario.model_validate_json((run / "scenario.json").read_text(encoding="utf-8"))
    return {
        activity.activity_id: {item.resource_id for item in activity.required_resources}
        for day in scenario.days
        for activity in day.activities
    }


def test_the_plan_names_the_objects_the_binder_hands_out(run: Path) -> None:
    """The expander names a basin before any home exists and the binder picks one after it does.

    The compiler can only serialise what the plan names, so the two answers have to be the same
    object: a plan serialising the kitchen sink while the binder sends both washes to the bathroom
    basin is the defect again with a constraint beside it.
    """
    bundle = SimulationBundle.model_validate_json(
        (run / "simulation-bundle.json").read_text(encoding="utf-8")
    )
    bound: dict[str, set[str]] = defaultdict(set)
    for binding in bundle.action_bindings:
        for capability in binding.capability_bindings:
            if capability.capability in {"switchable", "personal_care_support"}:
                bound[binding.source_activity_id].add(capability.provider_id)
    held = _held_resources(run)

    assert {"toilet_01", "washbasin_01"} <= set().union(*bound.values())
    for activity_id, resources in held.items():
        assert bound.get(activity_id, set()) == resources, activity_id


def test_two_washes_at_one_basin_take_turns(run: Path, trace: ExecutionTrace) -> None:
    """A tap already running is not turned on a second time: one use of an object at a time.

    The fixture asks for both morning washes in the same minutes in a bathroom the couple shares,
    which is what made the second `activate` of the tap fail before the plan said who held it. The
    run getting this far is half the assertion; the other half is that no two uses of one object
    overlap in the times the trace records.
    """
    held = _held_resources(run)
    spans: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    for item in trace.activity_executions:
        if item.status == "dropped":
            continue
        for resource_id in held.get(item.source_activity_id, set()):
            spans[resource_id].append((item.actual_start, item.actual_end, item.actor_id))

    assert {actor for *_, actor in spans["washbasin_01"]} == set(_RESIDENTS)
    for resource_id, uses in spans.items():
        uses.sort()
        for (_, first_end, _), (second_start, _, _) in pairwise(uses):
            assert first_end <= second_start, resource_id


def test_the_shared_house_is_one_observation_where_one_cone_saw_two_bodies(run: Path) -> None:
    """A PIR says something moved, never who: the record is one, and the oracle names both."""
    trace = ExecutionTrace.model_validate_json(
        (run / "execution-trace.json").read_text(encoding="utf-8")
    )
    log = json.loads((run / "observable-sensor-log.json").read_text(encoding="utf-8"))
    links = {
        item["observationId"]: item
        for item in json.loads((run / "oracle-mapping.json").read_text(encoding="utf-8"))["links"]
    }
    windows = [(item.actual_start, item.actual_end) for item in _shared(trace)]
    named = [
        links[record["observationId"]]["residentIds"]
        for record in log["records"]
        if record["sensorType"] == "pir"
        and any(
            start <= datetime.fromisoformat(record["observedAt"]) <= end for start, end in windows
        )
    ]

    together = [item for item in named if len(item) == 2]
    assert together, "no observation during a shared activity names both residents"
    assert all(item == sorted(item) for item in together)


# --- waiting for each other -----------------------------------------------------------------------

# One evening of the fixture, cut down to the activities a test names and moved to the minutes it
# gives them. Found by what they are rather than by identifier, because identifiers number a day's
# activities and move whenever the day gains one. The shared television is luca's with marco.
_TELEVISION = "television"
_LUCA_CALL = "luca_call"
_MARCO_CALL = "marco_call"
_MARCO_HYGIENE = "marco_hygiene"
_LUCA_HYGIENE = "luca_hygiene"
_MARCO_TOILET = "marco_toilet"
_LUCA_LUNCH = "luca_lunch"
_MARCO_LUNCH = "marco_lunch"
_MARCO_DRINK = "marco_drink"
_ROLE_INTENTS = {
    "call": "phone_call",
    "hygiene": "evening_hygiene",
    "toilet": "use_toilet",
    "lunch": "eat_lunch",
    "drink": "prepare_and_drink_hot_drink",
}


def _role(activity: CanonicalActivity, role: str) -> bool:
    if role == _TELEVISION:
        return activity.intent == "watch_television" and bool(activity.participant_ids)
    who, _, what = role.partition("_")
    return (
        activity.actor_id == who
        and activity.intent == _ROLE_INTENTS[what]
        and not activity.participant_ids
        # The bare ones: a candidate the engine may turn down would test the drive, not the rule.
        # The toilet and the hot drink exist only as candidates, and are taken as they are.
        and (what in {"toilet", "drink"} or not activity.can_overlap_for_actor)
    )


def _evening(
    run: Path,
    timing: dict[str, tuple[int, int]],
    *,
    mandatory: dict[str, bool] | None = None,
    private_from: dict[str, list[str]] | None = None,
    drop: str | None = None,
) -> tuple[SimulationBundle, dict[str, str]]:
    """Only the named activities, each at `(minutes after the television was due, minutes long)`.

    `drop` leaves one of them out while keeping everybody else's minutes, so a test can compare an
    evening with the one it would have been without it.

    Returns the bundle and the source identifier each role was found under. Preconditions are
    cleared, so the drives cannot turn an activity down for a reason the test is not about.
    `private_from` writes a privacy declaration onto the scenario activity, as the expander does.
    """
    bundle = SimulationBundle.model_validate_json(
        (run / "simulation-bundle.json").read_text(encoding="utf-8")
    )
    day = bundle.canonical_plan.days[0]
    found = {
        role: next(item for item in day.activities if _role(item, role))
        for role in {*timing, _TELEVISION}
    }
    due = found[_TELEVISION].scheduled_start
    activities = []
    for index, (role, (offset, minutes)) in enumerate(sorted(timing.items())):
        if role == drop:
            continue
        start = due + timedelta(minutes=offset)
        update: dict[str, Any] = {
            "sequence_index": index,
            "scheduled_start": start,
            "scheduled_end": start + timedelta(minutes=minutes),
            "duration_microseconds": minutes * 60_000_000,
            "preconditions": [],
        }
        if mandatory and role in mandatory:
            update["mandatory"] = mandatory[role]
        activities.append(found[role].model_copy(update=update))
    plan_day = day.model_copy(
        update={"activities": activities, "contingencies": [], "omitted_activities": []}
    )
    ids = {role: item.source_activity_id for role, item in found.items()}
    scenario = bundle.scenario
    if private_from:
        private = {ids[role]: residents for role, residents in private_from.items()}
        scenario = scenario.model_copy(
            update={
                "days": [
                    scenario_day.model_copy(
                        update={
                            "activities": [
                                item.model_copy(
                                    update={
                                        "extensions": {
                                            **item.extensions,
                                            PRIVACY_EXTENSION: private[item.activity_id],
                                        }
                                    }
                                )
                                if item.activity_id in private
                                else item
                                for item in scenario_day.activities
                            ]
                        }
                    )
                    for scenario_day in scenario.days
                ]
            }
        )
    plan = bundle.canonical_plan.model_copy(update={"days": [plan_day]})
    return bundle.model_copy(update={"scenario": scenario, "canonical_plan": plan}), ids


def _executions(
    evening: tuple[SimulationBundle, dict[str, str]],
) -> tuple[ExecutionTrace, dict[str, ActivityExecution]]:
    bundle, ids = evening
    result = simulate_bundle(bundle)
    assert result.report.success, result.report.issues
    assert result.trace is not None
    assert not validate_execution_trace(result.trace, bundle)
    by_id = {item.source_activity_id: item for item in result.trace.activity_executions}
    return result.trace, {role: by_id[source] for role, source in ids.items() if source in by_id}


def test_a_shared_activity_waits_in_line_by_when_it_was_due(run: Path) -> None:
    """Not behind whatever the participant queued while the actor was still busy.

    Luca is on the phone until a quarter past, so the television asks for marco only then. Marco is
    on the phone until half past and his shower, due at ten past, is already waiting for him. First
    come put the shower first; the television was due earlier, and goes first.
    """
    _, executions = _executions(
        _evening(
            run,
            {
                _TELEVISION: (0, 15),
                _LUCA_CALL: (-30, 45),
                _MARCO_CALL: (-5, 35),
                _MARCO_HYGIENE: (10, 15),
            },
        )
    )
    television = executions[_TELEVISION]
    hygiene = executions[_MARCO_HYGIENE]

    assert television.status != "dropped"
    assert television.participant_ids == ["marco"]
    assert television.actual_start < hygiene.actual_start
    assert television.actual_end <= hygiene.actual_start


@pytest.mark.parametrize("mandatory", [False, True])
def test_nobody_waits_long_for_a_resident_who_cannot_put_down_what_he_is_doing(
    run: Path, mandatory: bool
) -> None:
    """A quarter of an hour at most, and then the activity happens without him — never given up.

    Marco is washing for two hours from five minutes before the television, which is nothing a
    person is called out of. Luca is free the whole time. He used to stand there for an hour and
    then, if the television was optional, give it up: on the Moretti quarter that is how Chiara
    went without lunch three times. What is shared is the company, not whether it happens.
    """
    trace, executions = _executions(
        _evening(
            run,
            {_TELEVISION: (0, 15), _MARCO_HYGIENE: (-5, 125)},
            mandatory={_TELEVISION: mandatory},
        )
    )
    television = executions[_TELEVISION]
    wash = executions[_MARCO_HYGIENE]
    limit = television.planned_start + timedelta(seconds=SHARED_WAIT_SHORT_SECONDS)
    deviations = {
        item.kind: item
        for item in trace.plan_deviations
        if item.activity_execution_id == television.activity_execution_id
    }

    # Started once the short wait ran out — a transition pause after it, never marco's wash.
    assert limit <= television.actual_start < limit + timedelta(minutes=5)
    assert television.actual_start < wash.actual_end
    assert television.status == "deviated"
    assert television.participant_ids == []
    assert deviations["fallback_applied"].cause_id == "participant_unavailable"
    assert "optional_dropped" not in deviations
    assert not any(
        item.actor_id == "marco"
        for item in trace.action_executions
        if item.activity_execution_id == television.activity_execution_id
    )


def test_somebody_on_the_phone_is_called_and_goes_back_to_the_call(run: Path) -> None:
    """A phone call is put down for the shared activity and picked up again after it.

    Marco is on the phone for two hours from five minutes before the television. He comes to the
    television straight away instead of being waited for, the call records the interruption, and
    the time he spent at the television comes out of the call rather than being added to it: his
    call ends when it would have ended with no television at all, give or take the walk back.
    """
    trace, executions = _executions(_evening(run, {_TELEVISION: (0, 15), _MARCO_CALL: (-5, 125)}))
    television = executions[_TELEVISION]
    call = executions[_MARCO_CALL]
    _, alone = _executions(
        _evening(run, {_TELEVISION: (0, 15), _MARCO_CALL: (-5, 125)}, drop=_TELEVISION)
    )

    assert television.participant_ids == ["marco"]
    assert television.actual_start < television.planned_start + timedelta(minutes=5)
    assert call.status != "dropped"
    interruptions = [
        item
        for item in trace.plan_deviations
        if item.activity_execution_id == call.activity_execution_id and item.kind == "interrupted"
    ]
    assert [item.cause_id for item in interruptions] == [television.source_activity_id]
    assert abs(call.actual_end - alone[_MARCO_CALL].actual_end) < timedelta(minutes=5)


def test_a_shared_activity_waits_for_the_one_making_a_drink(run: Path) -> None:
    """What is being made is waited for to the end, past the quarter of an hour.

    Marco is making a hot drink for forty minutes from five minutes before the television: nothing
    he walks away from, and nothing that lasts, so Luca waits for it rather than starting without
    him.
    """
    _, executions = _executions(_evening(run, {_TELEVISION: (0, 15), _MARCO_DRINK: (-5, 40)}))
    television = executions[_TELEVISION]
    drink = executions[_MARCO_DRINK]

    assert television.participant_ids == ["marco"]
    assert television.actual_start >= drink.actual_end
    assert television.actual_start > television.planned_start + timedelta(
        seconds=SHARED_WAIT_SHORT_SECONDS
    )


def test_a_toilet_trip_is_given_up_while_the_bathroom_is_private(run: Path) -> None:
    """Luca's wash empties the bathroom of marco. Marco's trip that comes due during it is given
    up, the way one whose object is in use is."""
    trace, executions = _executions(
        _evening(
            run,
            {_TELEVISION: (0, 15), _LUCA_HYGIENE: (30, 25), _MARCO_TOILET: (40, 5)},
            private_from={_LUCA_HYGIENE: ["marco"]},
        )
    )
    toilet = executions[_MARCO_TOILET]

    assert toilet.status == "dropped"
    assert any(
        item.cause_id == "room_occupied"
        and item.activity_execution_id == toilet.activity_execution_id
        for item in trace.plan_deviations
    )


def test_a_mandatory_wash_waits_for_the_bathroom_to_be_free(run: Path) -> None:
    """The other way round: the wash comes due while marco is at the toilet and starts after him."""
    _, executions = _executions(
        _evening(
            run,
            {_TELEVISION: (0, 15), _MARCO_TOILET: (28, 10), _LUCA_HYGIENE: (30, 25)},
            mandatory={_LUCA_HYGIENE: True},
            private_from={_LUCA_HYGIENE: ["marco"]},
        )
    )
    toilet = executions[_MARCO_TOILET]
    hygiene = executions[_LUCA_HYGIENE]

    assert toilet.status != "dropped"
    assert hygiene.actual_start >= toilet.actual_end


# --- an errand interrupts what it lands in ------------------------------------------------------


def _placed(
    run: Path,
    placements: dict[str, tuple[Callable[[CanonicalActivity], bool], datetime, int]],
) -> tuple[SimulationBundle, dict[str, str]]:
    """Only the first activity each predicate picks, each at `(start, minutes long)`.

    `_evening` for moments that are not measured from the television: a night, a morning on the
    sofa, an afternoon out. Preconditions are cleared for the same reason.
    """
    bundle = SimulationBundle.model_validate_json(
        (run / "simulation-bundle.json").read_text(encoding="utf-8")
    )
    day = bundle.canonical_plan.days[0]
    found = {
        role: next(item for item in day.activities if pick(item))
        for role, (pick, _, _) in placements.items()
    }
    activities = [
        found[role].model_copy(
            update={
                "sequence_index": index,
                "scheduled_start": start,
                "scheduled_end": start + timedelta(minutes=minutes),
                "duration_microseconds": minutes * 60_000_000,
                "preconditions": [],
            }
        )
        for index, (role, (_, start, minutes)) in enumerate(sorted(placements.items()))
    ]
    plan_day = day.model_copy(
        update={"activities": activities, "contingencies": [], "omitted_activities": []}
    )
    plan = bundle.canonical_plan.model_copy(update={"days": [plan_day]})
    ids = {role: item.source_activity_id for role, item in found.items()}
    return bundle.model_copy(update={"canonical_plan": plan}), ids


def _midnight(run: Path) -> datetime:
    bundle = SimulationBundle.model_validate_json(
        (run / "simulation-bundle.json").read_text(encoding="utf-8")
    )
    return bundle.scenario.simulation_window.start


def _is(resident: str, intent: str) -> Callable[[CanonicalActivity], bool]:
    return lambda item: (
        item.actor_id == resident and item.intent == intent and not item.participant_ids
    )


def _posture_at(trace: ExecutionTrace, resident: str, moment: datetime) -> str | None:
    changes = sorted(
        (item.ended_at, str(item.resolved_arguments.get("posture")))
        for item in trace.action_executions
        if item.actor_id == resident
        and item.action_type == "change_posture"
        and item.ended_at <= moment
    )
    return changes[-1][1] if changes else None


def _night_with_a_toilet_trip(run: Path) -> tuple[ExecutionTrace, dict[str, ActivityExecution]]:
    midnight = _midnight(run)
    return _executions(
        _placed(
            run,
            {
                "sleep": (_is("luca", "sleep"), midnight + timedelta(minutes=15), 7 * 60),
                "toilet": (_is("luca", "use_toilet"), midnight + timedelta(hours=3), 6),
            },
        )
    )


def test_a_toilet_trip_in_the_night_interrupts_the_sleep_and_goes_back_to_bed(run: Path) -> None:
    """Queued behind the night on her lock, 61 of 62 Verdi night visits happened after the alarm."""
    trace, executions = _night_with_a_toilet_trip(run)
    sleep, toilet = executions["sleep"], executions["toilet"]
    during = toilet.actual_start + (toilet.actual_end - toilet.actual_start) / 2
    after = toilet.actual_end + timedelta(minutes=10)
    pauses = [
        item
        for item in trace.plan_deviations
        if item.deviation_id in sleep.deviation_ids and item.kind == "interrupted"
    ]

    assert toilet.status != "dropped"
    assert toilet.actual_start - toilet.planned_start < timedelta(minutes=1)
    assert sleep.actual_start < toilet.actual_start
    assert toilet.actual_end < sleep.actual_end
    assert _region_at(trace, "luca", during) == "bathroom"
    assert _region_at(trace, "luca", after) == "bedroom"
    assert _posture_at(trace, "luca", after) == "lying"
    assert [item.cause_id for item in pauses] == [toilet.source_activity_id]
    assert pauses[0].amount_microseconds >= (toilet.actual_end - toilet.actual_start) // timedelta(
        microseconds=1
    )


def test_the_night_is_not_counted_twice_where_the_toilet_trip_cut_it(run: Path) -> None:
    """The sleep's record spans the visit; the answer sheet does not have her asleep meanwhile."""
    trace, executions = _night_with_a_toilet_trip(run)
    toilet = executions["toilet"]
    evidence = evidence_from_trace(trace, initial_regions=dict.fromkeys(_RESIDENTS, "bedroom"))
    asleep = [item for item in evidence.activities["luca"] if item.intent == "sleep"]

    assert asleep
    assert not [item for item in asleep if item.location == "bathroom"]
    assert not [
        item for item in asleep if item.start < toilet.actual_end and item.end > toilet.actual_start
    ]


def test_a_toilet_trip_waits_for_the_refrigerator_door_to_be_shut(run: Path) -> None:
    """Nobody walks off to the toilet with the refrigerator standing open behind them."""
    lunch_at = _midnight(run) + timedelta(hours=13)
    lunch = (_is("luca", "eat_lunch"), lunch_at, 25)
    trace, alone = _executions(_placed(run, {"lunch": lunch}))
    opened, closed = _door_visits(trace, alone["lunch"])[0]
    due = opened + (closed - opened) / 2

    trace, executions = _executions(
        _placed(run, {"lunch": lunch, "toilet": (_is("luca", "use_toilet"), due, 6)})
    )
    toilet = executions["toilet"]

    assert toilet.status != "dropped"
    assert toilet.actual_start - toilet.planned_start < timedelta(minutes=2)
    assert all(
        shut <= toilet.actual_start or toilet.actual_end <= open_
        for open_, shut in _door_visits(trace, executions["lunch"])
    )


def test_from_the_sofa_she_comes_back_to_the_sofa(run: Path) -> None:
    """An errand from a seated block ends where it began, and the block goes on from there.

    The sensors see her go too: the reading's own motion stops while she is out of the room.
    """
    midnight = _midnight(run)
    bundle, ids = _placed(
        run,
        {
            "read": (_is("luca", "read_and_rest"), midnight + timedelta(hours=10), 60),
            "toilet": (_is("luca", "use_toilet"), midnight + timedelta(hours=10, minutes=25), 6),
        },
    )
    trace, executions = _executions((bundle, ids))
    read, toilet = executions["read"], executions["toilet"]
    after = toilet.actual_end + timedelta(minutes=5)
    reading = {
        item.action_execution_id
        for item in trace.action_executions
        if item.activity_execution_id == read.activity_execution_id
    }

    assert toilet.actual_start - toilet.planned_start < timedelta(minutes=1)
    assert read.actual_start < toilet.actual_start
    assert toilet.actual_end < read.actual_end
    assert _region_at(trace, "luca", after) == _region_at(trace, "luca", toilet.planned_start)
    assert _posture_at(trace, "luca", after) == "sitting"
    assert not [
        pulse
        for pulse in _motion_pulses(trace, bundle)
        if set(pulse.action_ids) & reading and toilet.actual_start < pulse.at < toilet.actual_end
    ]


def _door_visits(
    trace: ExecutionTrace, execution: ActivityExecution
) -> list[tuple[datetime, datetime]]:
    """From the start of each `open` the activity does to the end of the `close` after it."""
    actions = sorted(
        (
            item
            for item in trace.action_executions
            if item.activity_execution_id == execution.activity_execution_id
            and item.action_type in {"open", "close"}
        ),
        key=lambda item: item.started_at,
    )
    return [
        (opened.started_at, closed.ended_at)
        for opened, closed in zip(actions[::2], actions[1::2], strict=True)
    ]


def test_a_resident_who_finds_the_refrigerator_open_waits_for_it_to_be_closed(run: Path) -> None:
    """Nothing in the plan keeps two residents from the refrigerator in the same minute.

    A breakfast is placed against the stove, not the refrigerator it takes the food from, and on the
    Verdi month one resident reached for it while the other had it open: `open` requires it closed,
    and the run stopped. Luca is sent to lunch so that he reaches it halfway through marco's visit.
    """
    trace, alone = _executions(_evening(run, {_TELEVISION: (0, 15), _LUCA_LUNCH: (30, 25)}))
    lead = _door_visits(trace, alone[_LUCA_LUNCH])[0][0] - alone[_LUCA_LUNCH].actual_start
    trace, alone = _executions(_evening(run, {_TELEVISION: (0, 15), _MARCO_LUNCH: (30, 25)}))
    opened, closed = _door_visits(trace, alone[_MARCO_LUNCH])[0]

    bundle, ids = _evening(
        run, {_TELEVISION: (0, 15), _MARCO_LUNCH: (30, 25), _LUCA_LUNCH: (30, 25)}
    )
    day = bundle.canonical_plan.days[0]
    due = opened + (closed - opened) / 2 - lead
    moved = [
        item.model_copy(
            update={
                "scheduled_start": due,
                "scheduled_end": due + (item.scheduled_end - item.scheduled_start),
            }
        )
        if item.source_activity_id == ids[_LUCA_LUNCH]
        else item
        for item in day.activities
    ]
    plan = bundle.canonical_plan.model_copy(
        update={"days": [day.model_copy(update={"activities": moved})]}
    )
    trace, executions = _executions((bundle.model_copy(update={"canonical_plan": plan}), ids))
    marco = _door_visits(trace, executions[_MARCO_LUNCH])
    luca = _door_visits(trace, executions[_LUCA_LUNCH])
    waited = luca[0][0] - executions[_LUCA_LUNCH].actual_start - lead

    assert executions[_LUCA_LUNCH].status != "dropped"
    assert timedelta(0) < waited < timedelta(seconds=OPENABLE_WAIT_LIMIT_SECONDS)
    assert all(
        luca_close <= marco_open or marco_close <= luca_open
        for luca_open, luca_close in luca
        for marco_open, marco_close in marco
    )


def _written_standing(bundle: SimulationBundle, activity_id: str) -> SimulationBundle:
    """The bundle with every posture change of this activity's model written as `standing`, the way
    the Ferri package wrote its meals."""
    model_id = next(
        item.process_model_id
        for item in bundle.action_bindings
        if item.source_activity_id == activity_id
    )
    model = next(
        item for item in bundle.behavior_package.process_models if item.process_model_id == model_id
    )
    changed = {node.node_id for node in model.nodes if node.action_type == "change_posture"}

    def standing(node: ProcessNode) -> ProcessNode:
        if node.node_id not in changed:
            return node
        posture = node.arguments["posture"].model_copy(update={"value": "standing"})
        return node.model_copy(update={"arguments": {**node.arguments, "posture": posture}})

    models = [
        item.model_copy(update={"nodes": [standing(node) for node in item.nodes]})
        if item.process_model_id == model_id
        else item
        for item in bundle.behavior_package.process_models
    ]
    bindings = [
        item.model_copy(
            update={"resolved_arguments": {**item.resolved_arguments, "posture": "standing"}}
        )
        if item.process_model_id == model_id and item.node_id in changed
        else item
        for item in bundle.action_bindings
    ]
    package = bundle.behavior_package.model_copy(update={"process_models": models})
    return bundle.model_copy(update={"behavior_package": package, "action_bindings": bindings})


def test_a_stand_up_written_before_a_meal_is_how_the_meal_sits_down(run: Path) -> None:
    """A stand-up immediately before eating says nothing about standing, and is the sit-down."""
    bundle, ids = _evening(run, {_TELEVISION: (0, 15), _LUCA_LUNCH: (30, 25)})
    trace, executions = _executions((_written_standing(bundle, ids[_LUCA_LUNCH]), ids))
    postures = [
        item.resolved_arguments["posture"]
        for item in sorted(trace.action_executions, key=lambda row: row.started_at)
        if item.activity_execution_id == executions[_LUCA_LUNCH].activity_execution_id
        and item.action_type == "change_posture"
    ]

    assert postures[0] == "sitting"
    assert postures[-1] == "standing"


# --- what the trace says about itself ------------------------------------------------------------


def test_every_deviation_is_listed_by_the_activity_it_belongs_to(trace: ExecutionTrace) -> None:
    """A dropped activity lists the shift it waited through as well as the drop itself."""
    listed = {item for activity in trace.activity_executions for item in activity.deviation_ids}
    assert {item.deviation_id for item in trace.plan_deviations} == listed


def test_state_transitions_are_recorded_in_the_order_they_happened(trace: ExecutionTrace) -> None:
    """Each transition's previous value is the value the one before it set, read in file order."""
    last: dict[tuple[str, str], Any] = {}
    for transition in trace.state_transitions:
        key = (transition.subject_id, transition.fact)
        if key in last and transition.operation == "set":
            assert transition.previous_value == last[key], (transition.at, key)
        last[key] = transition.value


def test_nothing_runs_past_the_end_of_the_window(run: Path, trace: ExecutionTrace) -> None:
    """The last evening is cut at midnight, and so is everything the sensors saw."""
    scenario = Scenario.model_validate_json((run / "scenario.json").read_text(encoding="utf-8"))
    end = scenario.simulation_window.end
    # A gesture already begun is finished rather than cut mid-movement, so a few seconds may pass.
    grace = timedelta(minutes=1)
    assert trace.ended_at <= end + grace
    assert all(item.actual_end <= end + grace for item in trace.activity_executions)
    log = json.loads((run / "observable-sensor-log.json").read_text(encoding="utf-8"))
    assert all(
        datetime.fromisoformat(record["observedAt"]) <= end + grace for record in log["records"]
    )


def test_the_horizon_opens_with_everyone_asleep(run: Path) -> None:
    """The first night is planned too, instead of a silent bedroom until the first wake."""
    scenario = Scenario.model_validate_json((run / "scenario.json").read_text(encoding="utf-8"))
    first = scenario.days[0]
    for resident in _RESIDENTS:
        mine = sorted(
            (item for item in first.activities if item.actor_id == resident),
            key=lambda item: str(item.start_window.preferred) if item.start_window else "",
        )
        assert mine[0].intent == "sleep", resident
        assert mine[0].start_window is not None
        assert mine[0].start_window.earliest >= scenario.simulation_window.start


def test_an_empty_participant_list_hashes_like_no_field_at_all() -> None:
    """A trace written before `participantIds` existed has to keep verifying against its digest."""
    before = [{"activityExecutionId": "a", "actorId": "r1"}]
    after = [{"activityExecutionId": "a", "actorId": "r1", "participantIds": []}]
    shared = [{"activityExecutionId": "a", "actorId": "r1", "participantIds": ["r2"]}]

    assert semantic_activity_executions(after) == before
    assert semantic_activity_executions(shared) == shared


# --- the published ground truth, measured on the run ---------------------------------------------


@pytest.fixture(scope="module")
def scenario(run: Path) -> Scenario:
    return Scenario.model_validate_json((run / "scenario.json").read_text(encoding="utf-8"))


def test_the_published_ground_truth_is_measured_on_the_run(
    scenario: Scenario, trace: ExecutionTrace
) -> None:
    """Bands from the declaration, everything inside them from the trace, and it says which."""
    measured = ground_truth_of_run(scenario, trace, run_id="run_1")
    assert measured is not None
    habits, household = measured

    assert [item.resident_id for item in habits] == list(_RESIDENTS)
    for document in (*habits, household):
        assert document.measured_on == "execution_trace"
        assert document.trace_id == trace.trace_id
        assert document.source_trace_semantic_digest == trace.semantic_digest
        assert document.run_id == "run_1"


def test_the_realised_sharing_is_counted_on_the_days_the_run_shared(
    scenario: Scenario, trace: ExecutionTrace
) -> None:
    """Declared against realised, on the run: a shared day is a day an execution named them both.

    Both activities are `joint`, which declares no propensity — shared whenever the day allows —
    so what is published beside nothing is what the day allowed.
    """
    measured = ground_truth_of_run(scenario, trace)
    assert measured is not None
    household = measured[1]
    zone = ZoneInfo(scenario.time_zone)
    first_day = trace.started_at.astimezone(zone).date()

    rows = {(item.recurring_activity_id, item.day_class): item for item in household.sharing}
    for activity_id, intent in (("dinner", "eat_dinner"), ("television", "watch_television")):
        row = rows[(activity_id, "weekend" if first_day.weekday() >= 5 else "weekday")]
        shared_days = {
            item.actual_start.astimezone(zone).date()
            for item in _shared(trace)
            if item.intent == intent and item.actual_start.astimezone(zone).date() >= first_day
        }
        assert row.declared_propensity is None
        assert row.days_shared == len(shared_days)
        assert row.realised_share == round(row.days_shared / row.days_with_occurrence, 3)


def test_the_composition_is_what_the_trace_says_happened(
    scenario: Scenario, trace: ExecutionTrace
) -> None:
    """The acceptance criterion: the answer sheet agrees with an independent reading of the trace.

    Recomputed the plain way an experiment would do it from `activities.csv` — every executed
    activity a resident took part in, on its actual times, clipped to each day of the band — and it
    has to match the published minutes to the rounding of the published rows. A toilet trip that
    interrupted an activity lies inside that activity's times, and its minutes are counted once:
    the file says so by the nesting, and so does the answer sheet.
    """
    measured = ground_truth_of_run(scenario, trace)
    assert measured is not None
    zone = ZoneInfo(scenario.time_zone)
    for document in measured[0]:
        who = document.resident_id
        for band in document.habits:
            if band.crosses_midnight:
                continue
            opens = time.fromisoformat(band.window_start)
            closes = time.fromisoformat(band.window_end)
            expected = 0.0
            day = trace.started_at.astimezone(zone).date()
            while datetime.combine(day, time.min, zone) < trace.ended_at:
                begin = max(datetime.combine(day, opens, zone), trace.started_at)
                end = min(datetime.combine(day, closes, zone), trace.ended_at)
                mine = [
                    execution
                    for execution in trace.activity_executions
                    if execution.status in OCCUPYING_STATUSES
                    and who in (execution.actor_id, *execution.participant_ids)
                ]
                for execution in mine:
                    low = max(execution.actual_start, begin)
                    high = min(execution.actual_end, end)
                    if high > low:
                        expected += (high - low).total_seconds() / 60
                        expected -= sum(
                            (min(other.actual_end, high) - max(other.actual_start, low))
                            / timedelta(minutes=1)
                            for other in mine
                            if other is not execution
                            and execution.actual_start <= other.actual_start
                            and other.actual_end <= execution.actual_end
                            and min(other.actual_end, high) > max(other.actual_start, low)
                        )
                day += timedelta(days=1)
            published = sum(row.minutes for row in band.composition)
            assert abs(published - expected) <= 0.1 * max(1, len(band.composition)), (
                who,
                band.habit_id,
                published,
                expected,
            )


def test_the_participant_band_holds_the_dinner_she_did_not_cook(
    scenario: Scenario, trace: ExecutionTrace
) -> None:
    """Her evening is measured with her at the table."""
    measured = ground_truth_of_run(scenario, trace)
    assert measured is not None
    dinners = [item for item in _shared(trace) if item.intent == "eat_dinner"]
    participant = dinners[0].participant_ids[0]
    evening = next(
        band
        for document in measured[0]
        if document.resident_id == participant
        for band in document.habits
        if band.habit_id == f"evening_{participant}"
    )

    assert "eat_dinner" in {row.intent for row in evening.composition}


def test_the_household_sheet_shows_them_together_at_dinner(
    scenario: Scenario, trace: ExecutionTrace
) -> None:
    """Co-presence from where the bodies were, and each shared meal listed once."""
    measured = ground_truth_of_run(scenario, trace)
    assert measured is not None
    household = measured[1]
    dinners = [item for item in _shared(trace) if item.intent == "eat_dinner"]

    assert household.co_presence
    assert [item.intent for item in household.shared_episodes].count("eat_dinner") == len(dinners)
    assert all(item.participant_ids == list(_RESIDENTS) for item in household.shared_episodes)
    assert sum(value for day in household.days for value in day.shared_minutes.values()) > 0


def test_measure_habits_writes_one_sheet_per_resident_and_one_for_the_house(
    run: Path, tmp_path: Path
) -> None:
    output = tmp_path / "habit-ground-truth.json"

    result = CliRunner().invoke(
        app,
        [
            "measure-habits",
            str(run / "execution-trace.json"),
            "--scenario",
            str(run / "scenario.json"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text(encoding="utf-8"))["measuredOn"] == "execution_trace"
    assert (tmp_path / "habit-ground-truth-marco.json").exists()
    assert (tmp_path / "habit-ground-truth-household.json").exists()
