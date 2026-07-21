from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "generated/mario_rossi_2026_10_30_verified/personal-process-package.json"
TARGET = ROOT / "generated/mario_rossi_2026_10_30_ingested/personal-process-package.json"


def _remove_linear_node(model: dict[str, Any], node_id: str) -> None:
    incoming = [edge for edge in model["edges"] if edge["targetNodeId"] == node_id]
    outgoing = [edge for edge in model["edges"] if edge["sourceNodeId"] == node_id]
    if len(incoming) != 1 or len(outgoing) != 1:
        raise ValueError(f"cannot remove non-linear node {model['processModelId']}:{node_id}")
    model["nodes"] = [node for node in model["nodes"] if node["nodeId"] != node_id]
    model["edges"] = [
        edge
        for edge in model["edges"]
        if edge["sourceNodeId"] != node_id and edge["targetNodeId"] != node_id
    ]
    replacement = copy.deepcopy(incoming[0])
    replacement["targetNodeId"] = outgoing[0]["targetNodeId"]
    model["edges"].insert(0, replacement)


def migrate(payload: dict[str, Any], source_sha256: str) -> dict[str, Any]:
    package = copy.deepcopy(payload)
    package["packageVersion"] = "1.1.0"
    package["catalogs"]["activityCatalog"]["version"] = "1.1.0"
    package["catalogs"]["actionCatalog"]["version"] = "1.1.0"
    package["provenance"] = {
        "authorType": "rule_generator",
        "generatorName": "migrate_ingested_behavior_1_1",
        "generatorVersion": "1.0.0",
        "promptTemplateVersion": None,
        "generatedAt": "2026-07-21T12:00:00+02:00",
        "humanReviewed": True,
        "parameters": {
            "sourcePackageSha256": source_sha256,
            "correctionPolicy": "strict-runtime-semantics-1.1.0",
        },
    }
    for model in package["processModels"]:
        if model["processModelId"] == "resident_mario_rossi__travel_home":
            _remove_linear_node(model, "step_1")
        for node in model["nodes"]:
            if node.get("actionType") == "prepare_food":
                node["arguments"]["outputRole"] = {
                    "source": "literal",
                    "value": "prepared_meal",
                    "variableId": None,
                    "index": None,
                }
            if node.get("actionType") == "manage_medication":
                operation = node.get("arguments", {}).get("operation", {}).get("value")
                if operation in {"take", "refill"}:
                    node["effects"] = [
                        {
                            "fact": "resident.medicationAvailableDoses",
                            "operation": "decrement" if operation == "take" else "increment",
                            "value": 1 if operation == "take" else 30,
                        }
                    ]
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
        model["processModelVersion"] = "1.1.0"
    return package


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    payload = json.loads(source_bytes)
    migrated = migrate(payload, hashlib.sha256(source_bytes).hexdigest())
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
