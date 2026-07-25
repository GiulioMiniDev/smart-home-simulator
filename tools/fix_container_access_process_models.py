"""Make the shared process models open the container they reach into.

`take_item` is gated on the item being available, never on the cupboard being open, so a recipe that
forgets the `open`/`close` still simulates cleanly and simply never fires the contact sensor. That
is how `eat_breakfast` came to consume a meal it never fetched (fixed separately) and how
`clean_kitchen` still takes a cloth out of a closed cabinet and puts it back through the door.

These are the shared reference models: the deterministic path retargets them to every persona, so a
defect here is a defect in every dataset the generator has ever produced.

Run with: uv run python tools/fix_container_access_process_models.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG = (
    Path(__file__).resolve().parents[1]
    / "src/smart_home_sim/catalogs/reference-process-models-1.1.0.json"
)


def literal(value: str) -> dict[str, Any]:
    return {"source": "literal", "value": value, "variableId": None, "index": None}


def action(
    node_id: str, action_type: str, arguments: dict[str, Any], weight: float
) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "kind": "action",
        "actionType": action_type,
        "arguments": {
            name: value if isinstance(value, dict) else literal(value)
            for name, value in arguments.items()
        },
        "duration": None,
        "durationWeight": weight,
        "preconditions": [],
        "effects": [],
        "maxIterations": None,
    }


# `move_to` takes its destination from the activity's own location list, not from a constant; a
# literal expression carrying a null value fails contract validation.
ACTIVITY_LOCATION: dict[str, Any] = {
    "source": "activity_location",
    "value": None,
    "variableId": None,
    "index": 0,
}

Step = tuple[str, dict[str, Any], float]

# The cloth lives in the cabinet, so getting it out and putting it back opens the door twice.
_CLEAN_KITCHEN: list[Step] = [
    ("move_to_capability", {"targetRole": "cleaning_product_storage"}, 1.4),
    ("open", {"target": "cleaning_product_storage"}, 1.0),
    ("take_item", {"itemRole": "cleaning_tool"}, 1.0),
    ("close", {"target": "cleaning_product_storage"}, 1.0),
    ("move_to", {"destination": ACTIVITY_LOCATION}, 1.0),
    ("clean", {"targetRole": "kitchen_surfaces"}, 5.0),
    ("move_to_capability", {"targetRole": "cleaning_product_storage"}, 1.2),
    ("open", {"target": "cleaning_product_storage"}, 1.0),
    ("put_item", {"itemRole": "cleaning_tool"}, 1.0),
    ("close", {"target": "cleaning_product_storage"}, 1.0),
]

# The dose container was taken from the cabinet; it has to go back into it, not vanish at the sink.
_MEDICATION: list[Step] = [
    ("move_to_capability", {"targetRole": "medication_storage"}, 1.4),
    ("open", {"target": "medication_cabinet"}, 1.0),
    ("take_item", {"itemRole": "medication_dose_container"}, 1.0),
    ("close", {"target": "medication_cabinet"}, 1.0),
    ("move_to_capability", {"targetRole": "drinking_water_source"}, 1.2),
    ("take_item", {"itemRole": "drinking_glass"}, 1.0),
    ("manage_medication", {"operation": "take"}, 2.0),
    ("consume", {"itemRole": "drinking_water"}, 1.5),
    ("put_item", {"itemRole": "drinking_glass"}, 1.0),
    ("move_to_capability", {"targetRole": "medication_storage"}, 1.2),
    ("open", {"target": "medication_cabinet"}, 1.0),
    ("put_item", {"itemRole": "medication_dose_container"}, 1.0),
    ("close", {"target": "medication_cabinet"}, 1.0),
]

# Dirty clothes are collected out of the wardrobe, which is a door like any other.
_START_LAUNDRY: list[Step] = [
    ("move_to_capability", {"targetRole": "laundry_storage"}, 1.4),
    ("open", {"target": "laundry_storage"}, 1.0),
    ("laundry_step", {"operation": "collect"}, 2.0),
    ("close", {"target": "laundry_storage"}, 1.0),
    ("move_to_capability", {"targetRole": "washing_machine"}, 1.2),
    ("open", {"target": "laundry_equipment"}, 1.0),
    ("laundry_step", {"operation": "load"}, 2.0),
    ("close", {"target": "laundry_equipment"}, 1.0),
    ("laundry_step", {"operation": "start"}, 1.0),
]

REWRITES: dict[str, list[Step]] = {
    "clean_kitchen": _CLEAN_KITCHEN,
    "take_morning_medication": _MEDICATION,
    "start_laundry": _START_LAUNDRY,
}


def rewrite(model: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
    nodes = [node for node in model["nodes"] if node["kind"] == "start"]
    for index, (action_type, arguments, weight) in enumerate(steps, start=1):
        nodes.append(action(f"step_{index}", action_type, arguments, weight))
    nodes.extend(node for node in model["nodes"] if node["kind"] == "end")
    sequence = ["start", *(f"step_{index}" for index in range(1, len(steps) + 1)), "end"]
    edges = [
        {"sourceNodeId": source, "targetNodeId": target, "condition": None, "isDefault": False}
        for source, target in zip(sequence, sequence[1:], strict=False)
    ]
    return {**model, "nodes": nodes, "edges": edges}


def main() -> None:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    for intent, steps in REWRITES.items():
        before = sum(1 for node in document["models"][intent]["nodes"] if node["kind"] == "action")
        document["models"][intent] = rewrite(document["models"][intent], steps)
        opens = sum(1 for action_type, _, _ in steps if action_type == "open")
        print(f"{intent:26s} {before:2d} -> {len(steps):2d} azioni, {opens} aperture")
    CATALOG.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
