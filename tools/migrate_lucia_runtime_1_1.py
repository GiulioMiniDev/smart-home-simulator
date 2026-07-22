"""Migrate Lucia's accepted prompt-1.2.1 output to strict runtime semantics 1.1.0."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "generated/lucia_rossi_august_2026/canonical-inputs"
TARGET_DIR = ROOT / "generated/lucia_rossi_august_2026/runtime-inputs-1.1.0"
RUNTIME_SCENARIO_ID = "lucia_rossi_august_2026__runtime_1.1.0"


def literal(value: Any) -> dict[str, Any]:
    return {"source": "literal", "value": value}


def activity_location(index: int = 0) -> dict[str, Any]:
    return {"source": "activity_location", "index": index}


def action(node_id: str, action_type: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "kind": "action",
        "actionType": action_type,
        "arguments": arguments,
        "durationWeight": 1,
    }


def set_linear_flow(model: dict[str, Any], actions: list[dict[str, Any]]) -> None:
    model["nodes"] = [
        {"nodeId": "start", "kind": "start"},
        *actions,
        {"nodeId": "end", "kind": "end"},
    ]
    node_ids = [node["nodeId"] for node in model["nodes"]]
    model["edges"] = [
        {"sourceNodeId": source, "targetNodeId": target}
        for source, target in zip(node_ids, node_ids[1:], strict=False)
    ]


def action_nodes(model: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in model["nodes"] if node.get("kind") == "action"]


def migrate_scenario(source: dict[str, Any], source_sha256: str) -> dict[str, Any]:
    scenario = copy.deepcopy(source)
    scenario["scenarioId"] = RUNTIME_SCENARIO_ID
    scenario["title"] = f"{scenario['title']} — runtime semantics 1.1.0"
    scenario["modelReferences"]["activityCatalog"]["version"] = "1.1.0"
    parameters = dict(scenario["provenance"].get("parameters", {}))
    parameters["runtimeMigration"] = {
        "generator": "migrate_lucia_runtime_1_1",
        "sourceScenarioSha256": source_sha256,
        "policy": "strict-runtime-semantics-1.1.0",
    }
    scenario["provenance"]["parameters"] = parameters
    return scenario


def migrate_package(source: dict[str, Any], source_sha256: str) -> dict[str, Any]:
    package = copy.deepcopy(source)
    package["packageVersion"] = "1.1.0"
    package["sourceScenarioId"] = RUNTIME_SCENARIO_ID
    package["catalogs"]["activityCatalog"]["version"] = "1.1.0"
    package["catalogs"]["actionCatalog"]["version"] = "1.1.0"
    package["provenance"] = {
        "authorType": "rule_generator",
        "generatorName": "migrate_lucia_runtime_1_1",
        "generatorVersion": "1.0.0",
        "promptTemplateVersion": None,
        "generatedAt": datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds"),
        "humanReviewed": False,
        "parameters": {
            "sourcePackageSha256": source_sha256,
            "correctionPolicy": "strict-runtime-semantics-1.1.0",
        },
    }

    intents_by_model: dict[str, set[str]] = {}
    for binding in package["bindings"]:
        intents_by_model.setdefault(binding["processModelId"], set()).add(binding["intent"])

    for model in package["processModels"]:
        intents = intents_by_model.get(model["processModelId"], set())
        components = model["implementedComponents"]
        nodes = action_nodes(model)

        if components == ["travel"]:
            set_linear_flow(
                model,
                [
                    action(
                        "home_exit",
                        "move_to_capability",
                        {"targetRole": literal("home_exit")},
                    ),
                    action("leave_home", "leave_home", {}),
                    action(
                        "travel",
                        "travel_to",
                        {"destination": activity_location()},
                    ),
                ],
            )
        elif components[:2] == ["travel", "enter_home"]:
            retained = [
                copy.deepcopy(node)
                for node in nodes
                if node["actionType"] not in {"move_to", "leave_home", "travel_to", "enter_home"}
            ]
            set_linear_flow(
                model,
                [
                    action(
                        "travel_home",
                        "travel_to",
                        {"destination": activity_location()},
                    ),
                    action(
                        "home_entrance",
                        "move_to_capability",
                        {"targetRole": literal("home_entrance")},
                    ),
                    action("enter_home", "enter_home", {}),
                    *retained,
                ],
            )
        elif components == ["walk"]:
            exercise = next(node for node in nodes if node["actionType"] == "exercise")
            set_linear_flow(
                model,
                [
                    action(
                        "home_exit",
                        "move_to_capability",
                        {"targetRole": literal("home_exit")},
                    ),
                    action("leave_home", "leave_home", {}),
                    action(
                        "travel_outside",
                        "travel_to",
                        {"destination": activity_location()},
                    ),
                    copy.deepcopy(exercise) | {"nodeId": "exercise"},
                    action("travel_home", "travel_to", {"destination": literal("home")}),
                    action(
                        "home_entrance",
                        "move_to_capability",
                        {"targetRole": literal("home_entrance")},
                    ),
                    action("enter_home", "enter_home", {}),
                ],
            )
        elif components == ["carry_recycling", "leave_home", "discard_recycling"]:
            set_linear_flow(
                model,
                [
                    action(
                        "move_to_recycling",
                        "move_to",
                        {"destination": activity_location(0)},
                    ),
                    action(
                        "take_recycling",
                        "take_item",
                        {"itemRole": literal("utensils")},
                    ),
                    action("leave_home", "leave_home", {}),
                    action(
                        "travel_outside",
                        "travel_to",
                        {"destination": activity_location(1)},
                    ),
                    action(
                        "discard_recycling",
                        "put_item",
                        {"itemRole": literal("utensils")},
                    ),
                    action("travel_home", "travel_to", {"destination": literal("home")}),
                    action(
                        "home_entrance",
                        "move_to_capability",
                        {"targetRole": literal("home_entrance")},
                    ),
                    action("enter_home", "enter_home", {}),
                ],
            )

        for node in action_nodes(model):
            if node["actionType"] == "prepare_food":
                output_role = (
                    "prepared_food_portions"
                    if "weekly_meal_preparation" in intents
                    else "prepared_meal"
                )
                node["arguments"]["outputRole"] = literal(output_role)
            if node["actionType"] == "organize" and "weekly_meal_preparation" in intents:
                node["arguments"]["targetRole"] = literal("prepared_food_portions")
            if node["actionType"] == "put_item" and "store_purchases" in components:
                node["arguments"]["itemRole"] = literal("purchases")
        if "store_food" in components:
            put_nodes = [node for node in action_nodes(model) if node["actionType"] == "put_item"]
            put_nodes[-1]["arguments"]["itemRole"] = literal("prepared_food_portions")
        model["processModelVersion"] = "1.1.0"
    return package


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    scenario_bytes = (SOURCE_DIR / "scenario.json").read_bytes()
    package_bytes = (SOURCE_DIR / "personal-process-package.json").read_bytes()
    scenario = json.loads(scenario_bytes)
    package = json.loads(package_bytes)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    write_json(
        TARGET_DIR / "scenario.json",
        migrate_scenario(scenario, hashlib.sha256(scenario_bytes).hexdigest()),
    )
    write_json(
        TARGET_DIR / "personal-process-package.json",
        migrate_package(package, hashlib.sha256(package_bytes).hexdigest()),
    )
    print(TARGET_DIR)


if __name__ == "__main__":
    main()
