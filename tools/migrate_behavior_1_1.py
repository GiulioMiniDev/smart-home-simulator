from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCENARIO_ID = "mario_rossi_week_2026_10_12__runtime_1.1.0"
SOURCE_ACTIVITY_CATALOG = ROOT / "src/smart_home_sim/catalogs/activity-catalog-1.0.0.json"
TARGET_ACTIVITY_CATALOG = ROOT / "src/smart_home_sim/catalogs/activity-catalog-1.1.0.json"
SOURCE_CATALOG = ROOT / "src/smart_home_sim/catalogs/action-catalog-1.0.0.json"
TARGET_CATALOG = ROOT / "src/smart_home_sim/catalogs/action-catalog-1.1.0.json"
SOURCE_PACKAGE = ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior.json"
TARGET_PACKAGE = ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior-1.1.0.json"

DEPARTURE_ALREADY_MODELED = {
    "resident_mario_rossi__commute_home",
    "resident_mario_rossi__commute_to_work",
    "resident_mario_rossi__return_home_and_store_purchases",
    "resident_mario_rossi__travel_home",
    "resident_mario_rossi__travel_to_pharmacy",
    "resident_mario_rossi__travel_to_supermarket",
}
ROUND_TRIP_WALKS = {
    "resident_mario_rossi__evening_walk",
    "resident_mario_rossi__long_sunday_walk",
    "resident_mario_rossi__short_evening_walk",
}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _literal(value: str) -> dict[str, Any]:
    return {"source": "literal", "value": value}


def _action(node_id: str, action_type: str, **arguments: str) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "kind": "action",
        "actionType": action_type,
        "arguments": {key: _literal(value) for key, value in arguments.items()},
        "durationWeight": 1.0,
    }


def _linear_edges(node_ids: list[str]) -> list[dict[str, str]]:
    return [
        {"sourceNodeId": source, "targetNodeId": target}
        for source, target in zip(node_ids, node_ids[1:], strict=False)
    ]


def _remove_action(model: dict[str, Any], action_type: str) -> None:
    matches = [
        node
        for node in model["nodes"]
        if node.get("kind") == "action" and node.get("actionType") == action_type
    ]
    if len(matches) != 1:
        raise ValueError(f"{model['processModelId']} must contain one {action_type} node")
    node_id = matches[0]["nodeId"]
    incoming = [edge for edge in model["edges"] if edge["targetNodeId"] == node_id]
    outgoing = [edge for edge in model["edges"] if edge["sourceNodeId"] == node_id]
    if len(incoming) != 1 or len(outgoing) != 1:
        raise ValueError(f"cannot remove non-linear node {node_id}")
    model["nodes"] = [node for node in model["nodes"] if node["nodeId"] != node_id]
    model["edges"] = [
        edge
        for edge in model["edges"]
        if edge["sourceNodeId"] != node_id and edge["targetNodeId"] != node_id
    ]
    model["edges"].append(
        {
            "sourceNodeId": incoming[0]["sourceNodeId"],
            "targetNodeId": outgoing[0]["targetNodeId"],
        }
    )


def _build_catalog() -> dict[str, Any]:
    catalog = copy.deepcopy(_read(SOURCE_CATALOG))
    catalog["catalogVersion"] = "1.1.0"
    actions = {item["actionType"]: item for item in catalog["actions"]}
    actions["prepare_food"]["parameters"].append(
        {
            "parameterName": "outputRole",
            "description": "Role of the prepared item made available to subsequent actions.",
            "valueType": "string",
            "required": True,
            "referenceKind": "none",
            "allowedValues": [
                "drink",
                "prepared_food_portions",
                "prepared_meal",
                "prepared_salad",
            ],
        }
    )
    actions["prepare_food"]["effects"] = [
        {
            "factTemplate": "resident.carrying.{outputRole}",
            "operation": "set",
            "value": True,
        }
    ]
    actions["shop"]["effects"] = [
        {
            "factTemplate": "resident.carrying.purchases",
            "operation": "set",
            "value": True,
        }
    ]
    actions["dress"]["effects"] = [
        {
            "factTemplate": "resident.carrying.used_clothing",
            "operation": "set",
            "value": True,
        }
    ]
    return catalog


def _build_activity_catalog() -> dict[str, Any]:
    catalog = copy.deepcopy(_read(SOURCE_ACTIVITY_CATALOG))
    catalog["catalogVersion"] = "1.1.0"
    travel = next(item for item in catalog["components"] if item["componentId"] == "travel")
    travel["description"] = (
        "Movement between locations. Crossing the home boundary is modeled separately "
        "by leave_home and enter_home actions when applicable."
    )
    travel["requiredActionTypes"] = ["travel_to"]
    return catalog


def _prepared_output(node: dict[str, Any]) -> str:
    expression = node["arguments"]["mealKind"]
    meal_kind = str(expression.get("value", ""))
    if meal_kind == "weekly_meal_preparation":
        return "prepared_food_portions"
    if meal_kind == "hot_drink":
        return "drink"
    if meal_kind == "salad":
        return "prepared_salad"
    return "prepared_meal"


def _build_package() -> dict[str, Any]:
    source_bytes = SOURCE_PACKAGE.read_bytes()
    package = copy.deepcopy(json.loads(source_bytes))
    package["packageVersion"] = "1.1.0"
    package["sourceScenarioId"] = RUNTIME_SCENARIO_ID
    package["catalogs"]["activityCatalog"]["version"] = "1.1.0"
    package["catalogs"]["actionCatalog"]["version"] = "1.1.0"
    package["provenance"] = {
        "authorType": "rule_generator",
        "generatorName": "migrate_behavior_1_1",
        "generatorVersion": "1.1.0",
        "promptTemplateVersion": None,
        "generatedAt": "2026-07-21T12:00:00+02:00",
        "humanReviewed": True,
        "parameters": {
            "sourcePackageSha256": hashlib.sha256(source_bytes).hexdigest(),
            "correctionPolicy": "strict-runtime-semantics-1.1.0",
        },
    }
    for model in package["processModels"]:
        modified = False
        if model["processModelId"] in DEPARTURE_ALREADY_MODELED:
            _remove_action(model, "leave_home")
            modified = True
        if model["processModelId"] in ROUND_TRIP_WALKS:
            exercise = next(
                node
                for node in model["nodes"]
                if node.get("kind") == "action" and node.get("actionType") == "exercise"
            )
            model["nodes"] = [
                {"nodeId": "start", "kind": "start"},
                _action("home_exit", "move_to_capability", targetRole="home_exit"),
                _action("leave_home", "leave_home"),
                _action("walking_area", "move_to_capability", targetRole="walking_area"),
                exercise,
                _action("return_home", "travel_to", destination="home"),
                _action("home_entrance", "move_to_capability", targetRole="home_entrance"),
                _action("enter_home", "enter_home"),
                {"nodeId": "end", "kind": "end"},
            ]
            model["edges"] = _linear_edges([node["nodeId"] for node in model["nodes"]])
            modified = True
        if model["processModelId"] == "resident_mario_rossi__take_recycling_out":
            put_node = next(node for node in model["nodes"] if node.get("actionType") == "put_item")
            put_node["arguments"]["itemRole"]["value"] = "recycling"
            end_edge = next(edge for edge in model["edges"] if edge["targetNodeId"] == "end")
            previous = end_edge["sourceNodeId"]
            model["edges"].remove(end_edge)
            additions = [
                _action("return_home", "travel_to", destination="home"),
                _action("home_entrance", "move_to_capability", targetRole="home_entrance"),
                _action("enter_home", "enter_home"),
            ]
            model["nodes"][-1:-1] = additions
            model["edges"].extend(
                _linear_edges([previous, *[node["nodeId"] for node in additions], "end"])
            )
            modified = True
        for node in model["nodes"]:
            if node.get("actionType") == "prepare_food":
                node["arguments"]["outputRole"] = _literal(_prepared_output(node))
                modified = True
            if (
                node.get("actionType") == "organize"
                and node.get("arguments", {}).get("targetRole", {}).get("value")
                == "prepared_food_portions"
            ):
                node["effects"] = [
                    {
                        "fact": "resident.carrying.prepared_food_portions",
                        "operation": "set",
                        "value": True,
                    }
                ]
                modified = True
            if node.get("actionType") == "manage_medication":
                operation = node.get("arguments", {}).get("operation", {}).get("value")
                if operation == "take":
                    node["effects"] = [
                        {
                            "fact": "resident.medicationAvailableDoses",
                            "operation": "decrement",
                            "value": 1,
                        }
                    ]
                    modified = True
                elif operation == "refill":
                    node["effects"] = [
                        {
                            "fact": "resident.medicationAvailableDoses",
                            "operation": "increment",
                            "value": 30,
                        }
                    ]
                    modified = True
        if modified:
            model["processModelVersion"] = "1.1.0"
    return package


def main() -> None:
    _write(TARGET_ACTIVITY_CATALOG, _build_activity_catalog())
    _write(TARGET_CATALOG, _build_catalog())
    _write(TARGET_PACKAGE, _build_package())


if __name__ == "__main__":
    main()
