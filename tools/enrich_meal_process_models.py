"""Give the meal and cooking process models a realistic object-interaction granularity.

Measured on the 91-day export, the fridge was opened 74 times in total — 0.81 times a day against
the 8-15 of a real household — and the arithmetic pinned the cause exactly: only the three cooking
intents ever opened it, once each, and the three *eating* intents were `move -> sit -> consume ->
stand`. Nobody ever fetched what they ate; the meal simply materialised on the table, so the
contact sensors on the fridge and the cupboard were almost silent and the micro-action rate sat at
44 a day.

This rewrites the affected reference models in place, keeping every action type, role and argument
shape already used elsewhere in the catalog so the bindings, the compiler and the process-model
validator all still accept them.

Run with: uv run python tools/enrich_meal_process_models.py
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


# `prepare_food` reads its meal kind from the activity intent rather than a constant, and a literal
# expression with a null value fails contract validation.
FROM_INTENT: dict[str, Any] = {
    "source": "activity_intent",
    "value": None,
    "variableId": None,
    "index": None,
}


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


# (actionType, arguments, durationWeight) per step, in order.
Step = tuple[str, dict[str, Any], float]

# A meal now starts at the fridge and ends at the sink, which is where the fetch-and-clear traffic
# the contact sensors are supposed to see actually comes from.
_MEAL_STEPS: list[Step] = [
    ("move_to_capability", {"targetRole": "food_storage"}, 1.4),
    ("open", {"target": "food_storage"}, 1.0),
    ("take_item", {"itemRole": "prepared_meal"}, 1.0),
    ("close", {"target": "food_storage"}, 1.0),
    ("move_to_capability", {"targetRole": "consumption_area"}, 1.2),
    ("change_posture", {"posture": "sitting"}, 1.0),
    ("consume", {"itemRole": "prepared_meal"}, 5.0),
    ("change_posture", {"posture": "standing"}, 1.0),
    ("move_to_capability", {"targetRole": "washing_area"}, 1.2),
    ("put_item", {"itemRole": "prepared_meal"}, 1.0),
]

# Breakfast additionally goes back for the drink, which is the second-most frequent fridge visit of
# a real morning.
_BREAKFAST_STEPS: list[Step] = [
    ("move_to_capability", {"targetRole": "food_storage"}, 1.4),
    ("open", {"target": "food_storage"}, 1.0),
    ("take_item", {"itemRole": "prepared_meal"}, 1.0),
    ("close", {"target": "food_storage"}, 1.0),
    ("move_to_capability", {"targetRole": "consumption_area"}, 1.2),
    ("change_posture", {"posture": "sitting"}, 1.0),
    ("consume", {"itemRole": "prepared_meal"}, 4.0),
    ("change_posture", {"posture": "standing"}, 1.0),
    ("move_to_capability", {"targetRole": "food_storage"}, 1.2),
    ("open", {"target": "food_storage"}, 1.0),
    ("take_item", {"itemRole": "ingredients"}, 1.0),
    ("close", {"target": "food_storage"}, 1.0),
    ("move_to_capability", {"targetRole": "washing_area"}, 1.2),
    ("put_item", {"itemRole": "prepared_meal"}, 1.0),
]

# Cooking fetches ingredients in two trips and clears up, instead of one open and one close.
_COOKING_STEPS: list[Step] = [
    ("move_to_capability", {"targetRole": "food_preparation_area"}, 1.6),
    ("open", {"target": "food_storage"}, 1.0),
    ("take_item", {"itemRole": "ingredients"}, 1.0),
    ("close", {"target": "food_storage"}, 1.0),
    ("activate", {"target": "cooking_appliance"}, 1.0),
    ("prepare_food", {"mealKind": FROM_INTENT, "outputRole": "prepared_meal"}, 4.0),
    ("open", {"target": "food_storage"}, 1.0),
    ("take_item", {"itemRole": "ingredients"}, 1.0),
    ("close", {"target": "food_storage"}, 1.0),
    ("prepare_food", {"mealKind": FROM_INTENT, "outputRole": "prepared_meal"}, 3.0),
    ("deactivate", {"target": "cooking_appliance"}, 1.0),
    ("move_to_capability", {"targetRole": "washing_area"}, 1.2),
    ("put_item", {"itemRole": "prepared_meal"}, 1.0),
]

REWRITES: dict[str, list[Step]] = {
    "eat_breakfast": _BREAKFAST_STEPS,
    "eat_lunch": _MEAL_STEPS,
    "eat_dinner": _MEAL_STEPS,
    "prepare_simple_lunch": _COOKING_STEPS,
    "prepare_light_dinner": _COOKING_STEPS,
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
        print(f"{intent:24s} {before:2d} -> {len(steps):2d} azioni, {opens} aperture contenitore")
    CATALOG.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
