"""Derive activity catalog 1.4.0 and reference process models 1.4.0 from their 1.3.0 originals.

1.4.0 adds one intent: `night_toilet_visit`, the trip to the bathroom the drive layer already
emitted but had no vocabulary for. Until now those trips borrowed `morning_toilet_and_wash` — the
only executable toilet intent when the drive layer was written — which put a *morning* routine in
the ground truth at two in the morning, 73 times out of 75 on a generated year.

Borrowing the label was only half the damage. A process for a daytime toilet trip ends where the
last action left the resident, which for a nocturnal trip is standing at the washbasin; nothing
then returned her to bed, so `wake_up` began by walking her there from the bathroom on every night
the drives gave her a visit. A day is compiled as its own bundle, so there is no containing `sleep`
to resume: the return has to be part of the visit, which is what this intent's process model does
and what the `return_to_bed` component records.

It carries one more repair, of the same kind and found by the same audit: three resting processes
that put the resident down and never stood her back up. See `stand_up_after_resting`.

And a second intent, grounded rather than added: `prepare_breakfast`. See
`ground_breakfast_preparation`.

The 1.3.0 files stay frozen. Horizons already generated name the catalog version they were authored
against, and their provenance has to keep meaning what it said.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOGS = Path(__file__).parents[1] / "src/smart_home_sim/catalogs"

NIGHT_INTENT = "night_toilet_visit"
RETURN_COMPONENT = "return_to_bed"


def _read(name: str) -> Any:
    return json.loads((CATALOGS / name).read_text(encoding="utf-8"))


def _write(name: str, payload: Any) -> None:
    (CATALOGS / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _action(node_id: str, action_type: str, arguments: dict[str, Any], weight: float) -> Any:
    return {
        "nodeId": node_id,
        "kind": "action",
        "actionType": action_type,
        "arguments": arguments,
        "duration": None,
        "durationWeight": weight,
        "preconditions": [],
        "effects": [],
        "maxIterations": None,
    }


def _literal(value: str) -> dict[str, Any]:
    return {"source": "literal", "value": value, "variableId": None, "index": None}


def _location(index: int) -> dict[str, Any]:
    return {"source": "activity_location", "value": None, "variableId": None, "index": index}


def _from_intent() -> dict[str, Any]:
    """`prepare_food` reads which meal it is making from the activity, not from a constant."""
    return {"source": "activity_intent", "value": None, "variableId": None, "index": None}


def build_activity_catalog() -> None:
    catalog = _read("activity-catalog-1.3.0.json")
    catalog["catalogVersion"] = "1.4.0"

    components = catalog["components"]
    assert not any(item["componentId"] == RETURN_COMPONENT for item in components)
    components.append(
        {
            "componentId": RETURN_COMPONENT,
            "description": (
                f"Semantic component {RETURN_COMPONENT!r} implemented at the project trace "
                "granularity by its ordered required actions."
            ),
            "requiredActionTypes": ["change_posture"],
        }
    )
    components.sort(key=lambda item: item["componentId"])

    toilet = next(item for item in catalog["activities"] if item["intent"] == "use_toilet")
    # `Bed_to_Toilet` in CASAS Aruba is the nocturnal trip specifically — the resident leaves the
    # bed and comes back to it. That is this intent, not a toilet break in the middle of an
    # afternoon, so the mapping moves with the meaning.
    toilet.pop("externalMappings", None)
    catalog["activities"].append(
        {
            "intent": NIGHT_INTENT,
            "displayName": "Night Toilet Visit",
            "description": (
                f"Project-specific activity intent {NIGHT_INTENT!r}. A trip to the bathroom during "
                "the night, ending back in bed."
            ),
            "category": "hygiene",
            "components": ["use_toilet", RETURN_COMPONENT],
            "relevantVariableIds": list(toilet["relevantVariableIds"]),
            "externalMappings": {"casas_aruba": "Bed_to_Toilet"},
        }
    )
    catalog["activities"].sort(key=lambda item: item["intent"])
    _write("activity-catalog-1.4.0.json", catalog)


def build_reference_models() -> None:
    models = _read("reference-process-models-1.3.0.json")
    models["sourcePackage"] = (
        "mario_rossi 1.1.0 (neutralized 1.2.0, home work added 1.3.0, night toilet visit 1.4.0)"
    )
    assert NIGHT_INTENT not in models["models"]
    models["models"][NIGHT_INTENT] = {
        "processModelId": f"reference__{NIGHT_INTENT}",
        "processModelVersion": "1.4.0",
        "residentId": "reference_resident",
        "title": "reference night toilet visit process",
        "description": (
            "Resident-specific executable decomposition: use_toilet, return_to_bed. Out of bed, "
            "to the toilet, hands washed, and back under the covers."
        ),
        "implementedComponents": ["use_toilet", RETURN_COMPONENT],
        "nodes": [
            {
                "nodeId": "start",
                "kind": "start",
                "actionType": None,
                "arguments": {},
                "duration": None,
                "durationWeight": None,
                "preconditions": [],
                "effects": [],
                "maxIterations": None,
            },
            # She is in bed when this starts — the day bundle seeds her `lying` — so the first
            # thing a nocturnal trip involves is getting up. Without it the trace has her covering
            # ten metres to the bathroom, using the toilet and washing her hands while lying down,
            # and the `lying` at the end is a no-op on a posture that never changed.
            _action("step_1", "change_posture", {"posture": _literal("standing")}, 1.0),
            _action("step_2", "move_to", {"destination": _location(0)}, 1.6),
            _action("step_3", "move_to_capability", {"targetRole": _literal("toilet")}, 1.2),
            _action("step_4", "personal_care", {"procedure": _literal("use_toilet")}, 3.0),
            _action("step_5", "move_to_capability", {"targetRole": _literal("washing_area")}, 1.2),
            _action("step_6", "personal_care", {"procedure": _literal("wash_hands")}, 1.5),
            # The step the borrowed daytime process never had. `activity_location[1]` is the
            # bedroom the night visit declares alongside the bathroom; without it the resident is
            # left standing at the washbasin until whatever the plan holds next comes to fetch her.
            _action("step_7", "move_to", {"destination": _location(1)}, 1.6),
            _action("step_8", "change_posture", {"posture": _literal("lying")}, 1.0),
            {
                "nodeId": "end",
                "kind": "end",
                "actionType": None,
                "arguments": {},
                "duration": None,
                "durationWeight": None,
                "preconditions": [],
                "effects": [],
                "maxIterations": None,
            },
        ],
        "edges": [
            {"sourceNodeId": source, "targetNodeId": target, "condition": None, "isDefault": False}
            for source, target in (
                ("start", "step_1"),
                ("step_1", "step_2"),
                ("step_2", "step_3"),
                ("step_3", "step_4"),
                ("step_4", "step_5"),
                ("step_5", "step_6"),
                ("step_6", "step_7"),
                ("step_7", "step_8"),
                ("step_8", "end"),
            )
        ],
    }
    stand_up_after_resting(models["models"])
    ground_breakfast_preparation(models["models"])
    models["models"] = dict(sorted(models["models"].items()))
    _write("reference-process-models-1.4.0.json", models)


def stand_up_after_resting(models: dict[str, Any]) -> None:
    """Get the resident off the sofa when a resting activity ends.

    `rest_or_nap`, `read_and_rest` and `watch_television` sit or lie the resident down and never say
    anything more about her body, so the posture stayed whatever they left. Nothing inside those
    activities is wrong; the damage lands on the next one, which walks her across the flat still
    recorded as sitting. On a generated horizon that was every `eat_dinner` after an afternoon nap —
    8.8 metres from the bedroom to the kitchen, seated.

    `sleep` and `night_toilet_visit` are deliberately not in this list. They end in bed because that
    is where the resident is, and `wake_up` is what stands her up.

    The components are untouched: a trailing `change_posture` adds a statement about the body after
    the component's own ordered actions, so `nap` is still `change_posture, wait` and the models go
    on matching the intents they implement.
    """
    for intent in ("rest_or_nap", "read_and_rest", "watch_television"):
        model = models[intent]
        assert not any(node["nodeId"] == "stand_up" for node in model["nodes"])
        ends = {node["nodeId"] for node in model["nodes"] if node["kind"] == "end"}
        node = _action("stand_up", "change_posture", {"posture": _literal("standing")}, 1.0)
        model["nodes"].insert(len(model["nodes"]) - len(ends), node)
        for edge in model["edges"]:
            if edge["targetNodeId"] in ends:
                edge["targetNodeId"] = "stand_up"
        model["edges"].append(
            {
                "sourceNodeId": "stand_up",
                "targetNodeId": sorted(ends)[0],
                "condition": None,
                "isDefault": False,
            }
        )


BREAKFAST_INTENT = "prepare_breakfast"
# (actionType, arguments, durationWeight), in order.
_BREAKFAST_PREPARATION: tuple[tuple[str, dict[str, Any], float], ...] = (
    ("move_to", {"destination": _location(0)}, 1.6),
    ("move_to_capability", {"targetRole": _literal("coffee_and_breakfast_storage")}, 1.2),
    ("open", {"target": _literal("coffee_and_breakfast_storage")}, 1.0),
    ("take_item", {"itemRole": _literal("ingredients")}, 1.0),
    ("close", {"target": _literal("coffee_and_breakfast_storage")}, 1.0),
    # The appliance itself, not `food_preparation_area`. That role answers for the sink as well as
    # the stove and the binder takes the sink, so the cooking models have the resident standing at
    # the sink while she lights a hob on the other side of the kitchen. Naming the thing she is
    # about to switch on puts her in front of it, and `prepare_food` inherits the same provider.
    ("move_to_capability", {"targetRole": _literal("cooking_appliance")}, 1.2),
    ("activate", {"target": _literal("cooking_appliance")}, 1.0),
    ("prepare_food", {"mealKind": _from_intent(), "outputRole": _literal("prepared_meal")}, 3.0),
    ("deactivate", {"target": _literal("cooking_appliance")}, 1.0),
    ("move_to_capability", {"targetRole": _literal("coffee_and_breakfast_storage")}, 1.2),
    ("open", {"target": _literal("coffee_and_breakfast_storage")}, 1.0),
    ("put_item", {"itemRole": _literal("ingredients")}, 1.0),
    ("close", {"target": _literal("coffee_and_breakfast_storage")}, 1.0),
    ("move_to_capability", {"targetRole": _literal("consumption_area")}, 1.2),
    ("put_item", {"itemRole": _literal("prepared_meal")}, 1.0),
)


def ground_breakfast_preparation(models: dict[str, Any]) -> None:
    """Give the one meal of the day nobody could say was made a process that makes it.

    `prepare_breakfast` has been in the activity catalog since 1.0.0 and has never had a reference
    model, so it never reached `INTENT_CATALOG` and never reached the authoring prompt, whose
    in-home list *is* the intents that have one. Lunch and dinner each have a preparation an author
    can declare; breakfast had none, and the two horizons authored against 1.3.0 declared none —
    30 breakfasts on one and 132 on the other, not one of them preceded by anything. What the
    replay showed was a woman crossing the kitchen to a chair and eating a meal that no action in
    the horizon had ever made.

    The shape follows `prepare_simple_lunch` and `prepare_light_dinner`, with the two differences
    breakfast actually has. It fetches once rather than twice, because a breakfast is assembled
    rather than cooked in courses; and it names `coffee_and_breakfast_storage` rather than
    `food_storage` — the same fridge, under the role the vocabulary keeps for exactly this — then
    puts back what it took, which is where the second contact event of the morning comes from.

    It ends by setting the meal down at the `consumption_area`, not at the `washing_area` the
    cooking models use. That is where `eat_breakfast` then sits, and it is the difference between
    a breakfast made and left on the table and one made and put in the sink. It also leaves
    `resident.carrying.prepared_meal` false, which the cooking models do not.
    """
    assert BREAKFAST_INTENT not in models
    steps = _BREAKFAST_PREPARATION
    node_ids = ["start", *(f"step_{index}" for index in range(1, len(steps) + 1)), "end"]
    terminal = {
        "kind": "start",
        "actionType": None,
        "arguments": {},
        "duration": None,
        "durationWeight": None,
        "preconditions": [],
        "effects": [],
        "maxIterations": None,
    }
    models[BREAKFAST_INTENT] = {
        "processModelId": f"reference__{BREAKFAST_INTENT}",
        "processModelVersion": "1.4.0",
        "residentId": "reference_resident",
        "title": "reference prepare breakfast process",
        "description": (
            "Resident-specific executable decomposition: prepare_food. Coffee and breakfast come "
            "out of the storage they are kept in and go back into it, and what is made is left on "
            "the table rather than in the sink."
        ),
        "implementedComponents": ["prepare_food"],
        "nodes": [
            {**terminal, "nodeId": "start"},
            *(
                _action(f"step_{index}", action_type, arguments, weight)
                for index, (action_type, arguments, weight) in enumerate(steps, start=1)
            ),
            {**terminal, "nodeId": "end", "kind": "end"},
        ],
        "edges": [
            {"sourceNodeId": source, "targetNodeId": target, "condition": None, "isDefault": False}
            for source, target in zip(node_ids, node_ids[1:], strict=False)
        ],
    }


if __name__ == "__main__":
    build_activity_catalog()
    build_reference_models()
