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
    validate_rooms_are_furnished,
    validate_the_resident_goes_out,
)
from smart_home_sim.compiler.service import compile_payload
from smart_home_sim.domain.behavior import (
    EffectOperation,
    PersonalProcessPackage,
    ProcessNode,
)
from smart_home_sim.domain.models import Scenario

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
