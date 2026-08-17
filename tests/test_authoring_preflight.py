from __future__ import annotations

import json
from pathlib import Path

from smart_home_sim.authoring.preflight import (
    _ABSENT,
    _UNKNOWN,
    _actual_detail,
    _apply_effect,
    _is_definitely_false,
    _join,
    _resolve_arguments,
    validate_activities_do_not_park_the_resident,
    validate_away_round_trips,
    validate_declared_objects_are_reachable,
    validate_home_work_is_fragmented,
    validate_instrumented_objects_are_opened,
    validate_rooms_are_furnished,
    validate_the_resident_goes_out,
)
from smart_home_sim.behavior.service import default_action_catalog_path
from smart_home_sim.compiler.service import compile_payload
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    EffectOperation,
    PersonalProcessPackage,
    ProcessNode,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.sensors import CONTACT_INSTRUMENTED_TYPES
from smart_home_sim.hybrid_planning.intents import load_reference_models

ROOT = Path(__file__).parents[1]


def test_abstract_state_join_effects_and_precondition_operators() -> None:
    joined = _join(
        {"resident.at_home": True, "resident.location": "home"},
        {"resident.at_home": False, "resident.location": "home"},
    )
    assert joined["resident.at_home"] is _UNKNOWN
    assert joined["resident.location"] == "home"

    state = _apply_effect({"count": 2}, "count", EffectOperation.increment, 3)
    assert state["count"] == 5
    state = _apply_effect(state, "count", EffectOperation.decrement, 1)
    assert state["count"] == 4
    state = _apply_effect({"items": ["a"]}, "items", EffectOperation.append, "b")
    assert state["items"] == ["a", "b"]
    state = _apply_effect(state, "items", EffectOperation.remove, "a")
    assert state["items"] == ["b"]

    assert _is_definitely_false(_ABSENT, "exists", None)
    assert _is_definitely_false(True, "not_exists", None)
    assert _is_definitely_false("same", "ne", "same")
    assert not _is_definitely_false("same", "unsupported", "same")
    assert _actual_detail(_UNKNOWN) == "unknown"


def test_activity_location_argument_is_resolved_from_canonical_activity() -> None:
    payload = json.loads(
        (ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text(encoding="utf-8")
    )
    scenario = Scenario.model_validate_json(json.dumps(payload["scenario"]))
    compilation = compile_payload(payload["scenario"])
    assert compilation.plan is not None
    activity = compilation.plan.days[0].activities[0]
    node = ProcessNode.model_validate_json(
        json.dumps(
            {
                "nodeId": "move",
                "kind": "action",
                "actionType": "move_to",
                "arguments": {"destination": {"source": "activity_location", "index": 0}},
                "durationWeight": 1,
            }
        )
    )

    resolved = _resolve_arguments(node, activity, scenario, scenario.days[0], {})

    assert resolved is not None
    assert activity.location_ids[0] in resolved.values()


def _package_with(model_nodes: list[dict[str, object]], intent: str) -> PersonalProcessPackage:
    """Smallest package that binds one intent to one model with the given actions."""
    nodes: list[dict[str, object]] = [{"nodeId": "start", "kind": "start"}]
    nodes.extend({**node, "durationWeight": 1.0} for node in model_nodes)
    nodes.append({"nodeId": "end", "kind": "end"})
    identifiers = [node["nodeId"] for node in nodes]
    # Strict mode: on a dict the enums are not coerced, so the payload goes through JSON.
    return PersonalProcessPackage.model_validate_json(
        json.dumps(
            {
                "packageId": "package",
                "packageVersion": "1.0.0",
                "sourceScenarioId": "scenario",
                "sourceScenarioVersion": "1.0.0",
                "language": "en",
                "provenance": {"authorType": "human", "generatedAt": "2026-08-04T10:00:00+00:00"},
                "catalogs": {
                    "activityCatalog": {"catalogId": "a", "version": "1.2.0"},
                    "variableCatalog": {"catalogId": "v", "version": "1.0.0"},
                    "actionCatalog": {"catalogId": "c", "version": "1.1.0"},
                },
                "processModels": [
                    {
                        "processModelId": "pm",
                        "processModelVersion": "1.0.0",
                        "residentId": "resident",
                        "title": "Model",
                        "description": "Model",
                        "implementedComponents": ["travel"],
                        "nodes": nodes,
                        "edges": [
                            {"sourceNodeId": left, "targetNodeId": right}
                            for left, right in zip(identifiers, identifiers[1:], strict=False)
                        ],
                    }
                ],
                "bindings": [
                    {
                        "bindingId": "binding",
                        "residentId": "resident",
                        "intent": intent,
                        "processModelId": "pm",
                    }
                ],
            }
        )
    )


def test_an_away_activity_that_never_opens_the_door_is_reported() -> None:
    """`work_shift` implemented as sitting at a desk passes every other gate.

    The resident then spends the horizon indoors: one generated eight-month run produced zero
    `leave_home` actions and 74 door events against roughly 3.9 a day in CASAS Aruba, and nothing
    reported it.
    """
    package = _package_with(
        [
            {"nodeId": "a1", "kind": "action", "actionType": "change_posture"},
            {"nodeId": "a2", "kind": "action", "actionType": "perform_work"},
        ],
        "work_shift",
    )

    findings = validate_away_round_trips(package)

    assert len(findings) == 1
    assert "without ever leaving the home" in findings[0].message
    assert findings[0].details["leaveHome"] == 0


def test_leaving_without_returning_is_reported_where_it_happens() -> None:
    """Unbalanced, the model leaves `resident.at_home` stuck.

    Every later outing then fails a precondition that is deterministically false, which is
    reported against those later activities rather than against the model that broke the state.
    """
    package = _package_with(
        [
            {"nodeId": "a1", "kind": "action", "actionType": "move_to"},
            {"nodeId": "a2", "kind": "action", "actionType": "leave_home"},
        ],
        "leave_home",
    )

    findings = validate_away_round_trips(package)

    assert len(findings) == 1
    assert "round trip" in findings[0].message
    assert (findings[0].details["leaveHome"], findings[0].details["enterHome"]) == (1, 0)


def test_a_balanced_round_trip_and_a_home_intent_are_left_alone() -> None:
    round_trip = _package_with(
        [
            {"nodeId": "a1", "kind": "action", "actionType": "leave_home"},
            {"nodeId": "a2", "kind": "action", "actionType": "travel_to"},
            {"nodeId": "a3", "kind": "action", "actionType": "enter_home"},
        ],
        "work_shift",
    )
    indoors = _package_with(
        [{"nodeId": "a1", "kind": "action", "actionType": "prepare_food"}],
        "eat_breakfast",
    )

    assert validate_away_round_trips(round_trip) == []
    assert validate_away_round_trips(indoors) == []


def _scenario_with_outings(count: int) -> Scenario:
    """The frozen week with `count` of its activities moved outdoors."""
    payload = json.loads((ROOT / "examples/valid/mario_week.json").read_text(encoding="utf-8"))
    moved = 0
    for day in payload["days"]:
        for activity in day["activities"]:
            activity["intent"] = "evening_walk" if moved < count else "read_and_rest"
            moved += 1
    return Scenario.model_validate_json(json.dumps(payload))


def test_a_horizon_whose_resident_never_goes_out_is_flagged() -> None:
    """The door is the most informative sensor in the home, and it was observing nothing.

    An outline declaring no outdoor recurring activity produced sixteen crossings across eight
    months, all of them from events. A warning rather than a rejection: a housebound resident is a
    legitimate subject, producing one by accident is not.
    """
    findings = validate_the_resident_goes_out(_scenario_with_outings(0))

    assert len(findings) == 1
    assert findings[0].details["outings"] == 0
    assert "housebound" in findings[0].message


def test_a_resident_who_goes_out_weekly_is_left_alone() -> None:
    scenario = _scenario_with_outings(7)

    assert validate_the_resident_goes_out(scenario) == []


def test_a_furnished_scenario_passes_and_a_stripped_one_does_not() -> None:
    """The repo's own hand-authored week declares a fridge, a sink, a stove and a kettle.

    Outline-generated homes have been arriving with a single object per room, and nothing said so:
    the generator quietly substitutes a placeholder with no footprint and no contact sensor, so a
    kitchen holding seven intents put its entire signal on one point.
    """
    payload = json.loads((ROOT / "examples/valid/mario_week.json").read_text(encoding="utf-8"))
    furnished = Scenario.model_validate_json(json.dumps(payload))
    assert [
        finding.details["room"]
        for finding in validate_rooms_are_furnished(furnished)
        if finding.details["room"] == "kitchen"
    ] == []

    stripped = json.loads(json.dumps(payload))
    stripped["resources"] = [
        resource for resource in stripped["resources"] if resource["locationId"] != "kitchen"
    ]
    findings = validate_rooms_are_furnished(Scenario.model_validate_json(json.dumps(stripped)))

    kitchen = [item for item in findings if item.details["room"] == "kitchen"]
    assert len(kitchen) == 1
    assert kitchen[0].details["declaredResources"] == []
    assert "placeholder" in kitchen[0].message


def test_a_model_that_ends_in_a_bare_corridor_is_flagged() -> None:
    """Where a process model stops is where the resident stays until something moves her.

    On one authored horizon eight of twenty-two models ended with `move_to hallway`, and the
    resident spent 4.1 hours a day standing in a corridor furnished with a shoe cabinet. It went
    unnoticed for as long as standing still emitted nothing; once motion registered presence, those
    two corridor sensors carried 23% of the dataset.

    The repo's own hand-authored week is the negative control: its models leave the resident in
    rooms she can actually occupy, and must stay silent.
    """
    payload = json.loads((ROOT / "examples/valid/mario_week.json").read_text(encoding="utf-8"))
    scenario = Scenario.model_validate_json(json.dumps(payload))
    behavior = json.loads(
        (ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior-1.1.0.json").read_text(
            encoding="utf-8"
        )
    )
    package = PersonalProcessPackage.model_validate_json(json.dumps(behavior))
    assert validate_activities_do_not_park_the_resident(scenario, package) == []

    # A corridor holding only a cabinet, and a model that ends by walking into it.
    parked = json.loads(json.dumps(payload))
    parked["locations"].append({"locationId": "hallway", "kind": "room", "memberLocationIds": []})
    parked["resources"].append(
        {
            "resourceId": "hall_storage",
            "resourceType": "storage_cabinet",
            "locationId": "hallway",
            "capacity": 1,
            "attributes": {},
        }
    )
    stranded = json.loads(json.dumps(behavior))
    model = stranded["processModels"][0]
    terminal = next(
        edge["sourceNodeId"] for edge in model["edges"] if edge["targetNodeId"] == "end"
    )
    node = next(item for item in model["nodes"] if item["nodeId"] == terminal)
    node["kind"] = "action"
    node["actionType"] = "move_to"
    node["arguments"] = {
        "destination": {"source": "literal", "value": "hallway", "index": None, "variableId": None}
    }

    findings = validate_activities_do_not_park_the_resident(
        Scenario.model_validate_json(json.dumps(parked)),
        PersonalProcessPackage.model_validate_json(json.dumps(stranded)),
    )
    assert len(findings) == 1
    assert findings[0].details["destination"] == "hallway"
    assert findings[0].details["processModelId"] == model["processModelId"]


def _scenario_with_resources(*types: str) -> Scenario:
    """The frozen week, refurnished with the given resource types in the kitchen."""
    payload = json.loads((ROOT / "examples/valid/mario_week.json").read_text(encoding="utf-8"))
    room = payload["resources"][0]["locationId"]
    payload["resources"] = [
        {
            "resourceId": f"{resource_type}_main",
            "resourceType": resource_type,
            "locationId": room,
        }
        for resource_type in types
    ]
    return Scenario.model_validate_json(json.dumps(payload))


def _package_opening(*targets: str) -> PersonalProcessPackage:
    return _package_with(
        [
            {
                "nodeId": f"open_{index}",
                "kind": "action",
                "actionType": "open",
                "arguments": {"target": {"source": "literal", "value": target}},
            }
            for index, target in enumerate(targets)
        ],
        intent="read_and_rest",
    )


def test_an_instrumented_object_the_behaviour_never_opens_is_reported() -> None:
    """The washing machine got a reed switch and 104 laundry runs, and never once opened.

    Its contact reported 53 openings across a generated year against 54.8 expected from the noise
    model's false-positive rate alone, so the sensor published nothing but noise.
    """
    findings = validate_instrumented_objects_are_opened(
        _scenario_with_resources("refrigerator", "washing_machine", "wardrobe"),
        _package_opening("refrigerator"),
    )

    assert [finding.details["resourceType"] for finding in findings] == [
        "wardrobe",
        "washing_machine",
    ]
    assert findings[0].details["openedTypes"] == ["refrigerator"]


def test_an_object_the_behaviour_does_open_is_left_alone() -> None:
    findings = validate_instrumented_objects_are_opened(
        _scenario_with_resources("refrigerator", "wardrobe"),
        _package_opening("refrigerator", "wardrobe"),
    )

    assert findings == []


def test_a_role_is_credited_to_the_furniture_that_provides_it() -> None:
    """`cleaning_product_storage` is how a model opens a cabinet; the type name is not.

    Every reference model names a role rather than a `resourceType`, so a check reading the literal
    as a bare type reported four instrumented objects as untouched for behaviour that opens them.
    """
    findings = validate_instrumented_objects_are_opened(
        _scenario_with_resources("storage_cabinet", "washing_machine", "wardrobe"),
        _package_opening("cleaning_product_storage", "laundry_equipment", "clothing_storage"),
    )

    assert findings == []


def test_a_literal_naming_one_declared_object_counts_for_its_type() -> None:
    """Materialization binds a resourceId as readily as a role, so the check follows it there."""
    findings = validate_instrumented_objects_are_opened(
        _scenario_with_resources("wardrobe"), _package_opening("wardrobe_main")
    )

    assert findings == []


def test_the_reference_process_models_pass_their_own_rule() -> None:
    """The models the authoring prompt holds up as correct must not be reported as defective.

    `start_laundry` opens `laundry_storage` and `laundry_equipment`, `clean_kitchen` opens
    `cleaning_product_storage`, the meals open `food_storage`: between them the reference set
    touches every contact-instrumented type in the home. Reading those literals as resource types
    made the check flag all four, which is the shape of a rule that had never been run against the
    vocabulary it was judging.
    """
    models = [
        json.loads(model.model_dump_json(by_alias=True))
        for model in load_reference_models().values()
    ]
    package = PersonalProcessPackage.model_validate_json(
        json.dumps(
            {
                "packageId": "reference",
                "packageVersion": "1.0.0",
                "sourceScenarioId": "scenario",
                "sourceScenarioVersion": "1.0.0",
                "language": "en",
                "provenance": {"authorType": "human", "generatedAt": "2026-08-04T10:00:00+00:00"},
                "catalogs": {
                    "activityCatalog": {"catalogId": "a", "version": "1.2.0"},
                    "variableCatalog": {"catalogId": "v", "version": "1.0.0"},
                    "actionCatalog": {"catalogId": "c", "version": "1.1.0"},
                },
                "processModels": models,
                "bindings": [
                    {
                        "bindingId": "binding",
                        "residentId": "reference_resident",
                        "intent": "read_and_rest",
                        "processModelId": models[0]["processModelId"],
                    }
                ],
            }
        )
    )

    findings = validate_instrumented_objects_are_opened(
        _scenario_with_resources(*sorted(CONTACT_INSTRUMENTED_TYPES)), package
    )

    assert findings == []


def test_furniture_that_carries_no_contact_sensor_is_not_the_rule_s_business() -> None:
    """A kettle has no door. Nothing is instrumented, so nothing is expected to be opened."""
    findings = validate_instrumented_objects_are_opened(
        _scenario_with_resources("kettle", "sink"), _package_opening()
    )

    assert findings == []


def _scenario_with_home_work(blocks: tuple[tuple[str, int], ...]) -> Scenario:
    """The frozen week, its first activities rewritten as a day of work at home.

    Each block is (start time, minutes), applied to every day, so the shape of the working day is
    the only thing the check is reading.
    """
    payload = json.loads((ROOT / "examples/valid/mario_week.json").read_text(encoding="utf-8"))
    for day in payload["days"]:
        stamp = day["activities"][0]["startWindow"]["preferred"]
        calendar_day, offset = stamp.split("T")[0], stamp[-6:]
        for activity, (start, minutes) in zip(day["activities"], blocks, strict=False):
            activity["intent"] = "work_from_home"
            activity["locationIds"] = ["living_room"]
            activity["requiredResources"] = []
            moment = f"{calendar_day}T{start}:00{offset}"
            activity["startWindow"] = {
                "earliest": moment,
                "preferred": moment,
                "latest": moment,
            }
            activity["duration"] = {
                "minimumMinutes": float(minutes),
                "preferredMinutes": float(minutes),
                "maximumMinutes": float(minutes),
            }
    return Scenario.model_validate_json(json.dumps(payload))


def test_a_working_day_that_never_leaves_the_desk_is_flagged() -> None:
    """Working from home is observable only through the breaks.

    A resident modelled as one unbroken block is a resident modelled as furniture: one motion
    sensor holds the whole afternoon, every other room falls silent, and the segmentation target
    for the middle of the day is a rectangle. A warning, not a rejection — some people really do
    work that way, and a researcher who wants it keeps the finding.
    """
    findings = validate_home_work_is_fragmented(_scenario_with_home_work((("09:00", 480),)))

    assert len(findings) == 1
    assert findings[0].details["monolithicDays"] == findings[0].details["workingDays"]
    assert findings[0].details["longestStretchMinutes"] == 480.0


def test_a_working_day_split_into_blocks_is_left_alone() -> None:
    scenario = _scenario_with_home_work(
        (("09:15", 105), ("11:30", 90), ("14:30", 120), ("16:45", 75))
    )

    assert validate_home_work_is_fragmented(scenario) == []


def test_blocks_a_quarter_hour_apart_are_one_stretch() -> None:
    """Standing up and sitting straight back down is not a break by any sensor's reckoning."""
    scenario = _scenario_with_home_work((("09:00", 130), ("11:15", 130), ("13:30", 130)))

    findings = validate_home_work_is_fragmented(scenario)

    assert len(findings) == 1
    assert findings[0].details["longestStretchMinutes"] == 400.0


def test_a_horizon_with_no_home_work_at_all_is_not_the_check_s_business() -> None:
    payload = json.loads((ROOT / "examples/valid/mario_week.json").read_text(encoding="utf-8"))

    assert validate_home_work_is_fragmented(Scenario.model_validate_json(json.dumps(payload))) == []


def _action_catalog() -> ActionCatalog:
    return ActionCatalog.model_validate_json(
        default_action_catalog_path("1.1.0").read_text(encoding="utf-8")
    )


def test_furniture_no_activity_can_reach_is_reported() -> None:
    """A five-month horizon furnished a family flat and then wrote a life that used half of it.

    A wardrobe, a washing machine and three cabinets were declared for a father of two who never
    did the laundry, never changed his clothes and never cleaned. Every other gate passed: the
    portfolio held twenty recurring activities and the process models were well formed.
    """
    findings = validate_declared_objects_are_reachable(
        _scenario_with_resources("refrigerator", "wardrobe", "washing_machine"),
        _package_opening("food_storage"),
        _action_catalog(),
    )

    assert [finding.details["resourceType"] for finding in findings] == [
        "wardrobe",
        "washing_machine",
    ]


def test_furniture_the_binder_merely_did_not_choose_is_left_alone() -> None:
    """Reachable is not the same as used, and only the first is the author's business.

    `leisure` asks for `leisure_support` and names no role, so a sofa answers it — even though the
    armchair beside it wins the tie on entity id. Reporting the sofa would ask the author to fix a
    contest the binder decides.
    """
    package = _package_with(
        [
            {
                "nodeId": "read",
                "kind": "action",
                "actionType": "leisure",
                "arguments": {"kind": {"source": "literal", "value": "reading"}},
            }
        ],
        intent="read_and_rest",
    )

    findings = validate_declared_objects_are_reachable(
        _scenario_with_resources("sofa", "chair"), package, _action_catalog()
    )

    assert findings == []


def test_a_resource_type_the_table_does_not_know_answers_any_request_without_a_role() -> None:
    """An unrecognised type offers every capability, so nothing it could serve is denied to it.

    It is still unreachable when every request names a role it does not answer to, and that is the
    honest reading: the binder could not choose it either.
    """
    unknown = _scenario_with_resources("aquarium")
    catalog = _action_catalog()

    roleless = _package_with(
        [
            {
                "nodeId": "read",
                "kind": "action",
                "actionType": "leisure",
                "arguments": {"kind": {"source": "literal", "value": "reading"}},
            }
        ],
        intent="read_and_rest",
    )
    assert validate_declared_objects_are_reachable(unknown, roleless, catalog) == []

    named = validate_declared_objects_are_reachable(
        unknown, _package_opening("food_storage"), catalog
    )
    assert [finding.details["resourceType"] for finding in named] == ["aquarium"]
