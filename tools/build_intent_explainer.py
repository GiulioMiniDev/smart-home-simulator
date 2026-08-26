"""Render the intent explainer: every reference process model, step by step, in plain English.

The audience is a researcher who wants to change what an activity *is* and has no reason to read
Python. So the page states, for each step, three things a JSON file alone does not: what the
resident is doing in a sentence, which real object the role resolves to, and what the sensors see.
The last one is the point — a step that no sensor witnesses contributes nothing to the dataset,
and today that fact is only discoverable by reading `PIR_ACTIVITY_ACTION_TYPES`.

Everything is read from the catalogs and from the engine's own tables at build time. There is no
second copy of any of them here, for the reason `build_authoring_artifacts._render_container_roles`
already gives: a hand-kept copy can only drift from the set that matters. What this module *does*
own is the English phrasing — a verb per action type and a noun per role — because that reading
exists nowhere else in the system.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_home_sim.domain.models import resource_types_for_role  # noqa: E402
from smart_home_sim.domain.sensors import CONTACT_INSTRUMENTED_TYPES  # noqa: E402
from smart_home_sim.hybrid_planning.intents import (  # noqa: E402
    INTENT_CATALOG,
    REFERENCE_FILE,
    IntentCategory,
)
from smart_home_sim.sensors.service import PIR_ACTIVITY_ACTION_TYPES  # noqa: E402
from smart_home_sim.simulation.service import PUNCTUAL_ACTION_SECONDS  # noqa: E402

# Travel is what `behavior.service` treats as travel, and its sensor evidence is the walk it
# plans rather than the action type — no PIR table lists these.
TRAVEL_ACTION_TYPES = frozenset({"move_to", "move_to_capability", "travel_to"})

CATALOG_DIR = ROOT / "src" / "smart_home_sim" / "catalogs"
ACTION_CATALOG = CATALOG_DIR / "action-catalog-1.1.0.json"
ACTIVITY_CATALOG = CATALOG_DIR / "activity-catalog-1.4.0.json"
REFERENCE_MODELS = CATALOG_DIR / REFERENCE_FILE

# How each action reads as something a person does. `{0}` is the action's own argument, already
# turned into a noun by ROLE_NOUNS. A tuple is (template, template_without_argument).
ACTION_PHRASES: dict[str, str] = {
    "move_to": "Walks to where the activity happens",
    "move_to_capability": "Walks over to {0}",
    "change_posture": "{0}",
    "open": "Opens {0}",
    "close": "Closes {0}",
    "take_item": "Picks up {0}",
    "put_item": "Puts {0} down",
    "activate": "Switches on {0}",
    "deactivate": "Switches off {0}",
    "wait": "Waits — {0}",
    "inspect": "Checks {0}",
    "consume": "Eats or drinks {0}",
    "personal_care": "{0}",
    "clean": "Cleans {0}",
    "laundry_step": "Laundry: {0}",
    "organize": "Tidies {0}",
    "dress": "Gets dressed",
    "manage_medication": "Medication: {0}",
    "leave_home": "Leaves the flat",
    "enter_home": "Comes back into the flat",
    "travel_to": "Travels to {0}",
    "shop": "Does the shopping",
    "communicate": "Talks over {0}",
    "perform_work": "Works",
    "exercise": "Exercises — {0}",
    "leisure": "Relaxes — {0}",
    "prepare_food": "Cooks {0}",
}

# Argument values that read as a phrase rather than as a noun, so the template above reads as a
# sentence. Anything absent falls back to ROLE_NOUNS and then to the raw identifier.
VALUE_PHRASES: dict[str, str] = {
    "sitting": "Sits down",
    "standing": "Stands up",
    "lying": "Lies down",
    "evening_hygiene": "Washes and brushes her teeth for the night",
    "use_toilet": "Uses the toilet",
    "shower": "Showers",
    "wash_face": "Washes her face",
    "wash_hands": "Washes her hands",
    "take": "takes the dose",
    "hang": "hangs it out to dry",
    "collect": "gathers the washing",
    "load": "loads the drum",
    "start": "starts the cycle",
    "rest": "resting",
    "nap": "napping",
    "sleep": "asleep",
    "walking": "a walk",
    "indoor_light_exercise": "light exercise indoors",
    "read": "reading",
    "focused_work": "at her desk",
    "phone": "the phone",
    "hot_drink": "a hot drink",
    "kitchen_surfaces": "the kitchen surfaces",
}

# What a role is, said the way someone describes their own flat. Roles the binder cannot answer
# with furniture are still listed: the page says so explicitly rather than leaving a bare id.
ROLE_NOUNS: dict[str, str] = {
    "food_storage": "the fridge",
    "coffee_and_breakfast_storage": "the breakfast cupboard",
    "cleaning_product_storage": "the cleaning cupboard",
    "household_storage": "the household cupboard",
    "medication_cabinet": "the medicine cabinet",
    "medication_storage": "the medicine cabinet",
    "laundry_storage": "the laundry basket",
    "laundry_equipment": "the washing machine",
    "washing_machine": "the washing machine",
    "cooking_appliance": "the hob",
    "food_preparation_area": "the worktop",
    "coffee_equipment": "the moka pot",
    "consumption_area": "the table",
    "table": "the table",
    "washing_area": "the sink",
    "sink": "the sink",
    "sink_faucet": "the tap",
    "drinking_water_source": "the tap",
    "personal_care_fixture": "the basin",
    "toilet": "the toilet",
    "shower": "the shower",
    "shower_water": "the shower",
    "television": "the television",
    "ingredients": "the ingredients",
    "prepared_meal": "the meal",
    "prepared_food_portions": "the portions",
    "drink": "the drink",
    "drinking_glass": "a glass",
    "drinking_water": "some water",
    "medication_dose_container": "the pill box",
    "cleaning_tool": "the cloth",
    "purchases": "the shopping",
    "walking_area": "the front door",
    "drying_area": "the drying rack",
    "exercise_area": "a clear bit of floor",
    "tidying_area": "the room",
    "retail_area": "the shop",
    "communication_area": "the armchair",
}

ENTITY_NOUNS: dict[str, str] = {
    "refrigerator": "fridge",
    "storage_cabinet": "storage cabinet",
    "wardrobe": "wardrobe",
    "washing_machine": "washing machine",
    "stove": "hob",
    "sink": "kitchen sink",
    "washbasin": "washbasin",
    "shower": "shower",
    "toilet": "toilet",
    "bed": "bed",
    "chair": "chair",
    "table": "table",
    "sofa": "sofa",
    "moka_coffee_maker": "moka pot",
    "television": "television",
    "radio": "radio",
}

# Two actions are nothing but their argument — `change_posture` reads as "Sits down", not as
# "Changes posture to sitting". That is right in a step and useless in the reference table,
# where there is no argument to stand in, so the table gets its own reading of them.
APPENDIX_PHRASES: dict[str, str] = {
    "change_posture": "Sits, stands or lies down",
    "personal_care": "Washes, showers or uses the toilet",
}

CATEGORY_BLURBS: dict[str, str] = {
    "sleep_wake": "Getting up and going to bed",
    "hygiene": "Washing and the bathroom",
    "medication": "Taking medicine",
    "meal": "Sitting down to eat",
    "cooking": "Making food and drink",
    "chores": "Tidying and cleaning",
    "laundry": "Washing clothes",
    "exercise": "Moving on purpose",
    "outdoor": "Time outside the flat",
    "errand": "Going out to fetch something",
    "leisure": "Free time at home",
    "social": "Contact with other people",
    "home_work": "Paid work done indoors",
}


# The enum declares its categories roughly in the order a day runs through them, which reads
# better in a list than the alphabet does.
_CATEGORY_ORDER = {str(item): index for index, item in enumerate(IntentCategory)}


def _argument_value(argument: Any) -> tuple[str | None, str]:
    """The literal an argument carries, plus where it comes from."""
    if not isinstance(argument, dict):
        return None, "literal"
    source = argument.get("source") or "literal"
    value = argument.get("value")
    if source != "literal":
        return None, source
    return (value if isinstance(value, str) else None), source


def _phrase(action_type: str, arguments: dict[str, Any]) -> str:
    template = ACTION_PHRASES.get(action_type)
    if template is None:
        return f"Performs {action_type.replace('_', ' ')}"
    if "{0}" not in template:
        return template
    # A literal reads as itself; `activity_intent` and `activity_location` are only filled in per
    # activity at run time, so prefer any literal sibling before falling back to naming the source.
    # `prepare_food(mealKind: activity_intent, outputRole: prepared_meal)` is the case that matters:
    # taking the first argument gave "Cooks whatever this activity is" where the second says "the
    # meal".
    fallback: str | None = None
    for argument in arguments.values():
        value, source = _argument_value(argument)
        if value is not None:
            return template.format(VALUE_PHRASES.get(value) or ROLE_NOUNS.get(value) or value)
        if fallback is None:
            fallback = (
                "the room" if source == "activity_location" else "what this activity calls for"
            )
    return template.format(fallback or "it")


# The parameter kinds that name something in the flat. `none` marks a mode or procedure string —
# `load`, `wash_face`, `sitting` — which is part of the sentence but binds to no furniture, and
# reading it as a role is what made the page report the posture `sitting` as an unfurnished room.
BINDING_REFERENCE_KINDS = frozenset({"capability", "environment_entity"})


def _resolves_to(
    action_type: str, arguments: dict[str, Any], reference_kinds: dict[str, dict[str, str]]
) -> tuple[list[str], str | None]:
    """The furniture a step's role can bind to, and the role that asked for it."""
    kinds = reference_kinds.get(action_type, {})
    for name, argument in arguments.items():
        if kinds.get(name) not in BINDING_REFERENCE_KINDS:
            continue
        value, source = _argument_value(argument)
        if value is None or source != "literal":
            continue
        types = sorted(resource_types_for_role(value))
        if types:
            return [ENTITY_NOUNS.get(item, item.replace("_", " ")) for item in types], value
        return [], value
    return [], None


def _sensor_effects(action_type: str, arguments: dict[str, Any]) -> list[dict[str, str]]:
    """What a step leaves behind in the sensor log.

    Three kinds, and the distinction is the whole reason this page exists. Working at an object
    pulses the detector that watches it. Walking pulses every detector along the path, which is the
    richest evidence in the log and belongs to no action type at all — `_pir_candidates` reads the
    movement, not the action. Everything else leaves only the presence pulses a still body produces
    anyway, so the step is real but adds nothing a miner can key on.
    """
    effects: list[dict[str, str]] = []
    if action_type in TRAVEL_ACTION_TYPES:
        effects.append({"kind": "walk", "label": "motion along the way"})
    if action_type in PIR_ACTIVITY_ACTION_TYPES:
        effects.append({"kind": "pir", "label": "motion at the object"})
    if action_type in {"open", "close"}:
        for argument in arguments.values():
            value, source = _argument_value(argument)
            if value is None or source != "literal":
                continue
            instrumented = sorted(resource_types_for_role(value) & CONTACT_INSTRUMENTED_TYPES)
            if instrumented:
                noun = ENTITY_NOUNS.get(instrumented[0], instrumented[0])
                effects.append({"kind": "contact", "label": f"{noun} door"})
    if not effects:
        effects.append({"kind": "presence", "label": "presence only"})
    return effects


def _count(steps: list[dict[str, Any]], kind: str) -> int:
    return sum(1 for step in steps if any(s["kind"] == kind for s in step["sensors"]))


def _build_steps(
    model: dict[str, Any], reference_kinds: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for node in model["nodes"]:
        if node["kind"] != "action":
            continue
        action_type = node["actionType"]
        arguments = node.get("arguments") or {}
        gesture_seconds = PUNCTUAL_ACTION_SECONDS.get(action_type)
        resolves, role = _resolves_to(action_type, arguments, reference_kinds)
        call_args = ", ".join(
            f"{name}: {(_argument_value(value)[0] or _argument_value(value)[1])}"
            for name, value in arguments.items()
        )
        steps.append(
            {
                "nodeId": node["nodeId"],
                "action": action_type,
                "phrase": _phrase(action_type, arguments),
                "call": f"{action_type}({call_args})" if call_args else f"{action_type}()",
                "role": role,
                "resolvesTo": resolves,
                "weight": node.get("durationWeight") or 1.0,
                "gestureSeconds": gesture_seconds,
                "elastic": gesture_seconds is None,
                # Travel sits in the gesture table at zero because `_execute_action` floors it
                # to the planned path once the walk is known. Reporting "0s" to a reader is
                # therefore true of the table and false of the day, so it gets its own kind.
                "travel": action_type in TRAVEL_ACTION_TYPES,
                "sensors": _sensor_effects(action_type, arguments),
            }
        )
    return steps


def build_payload() -> dict[str, Any]:
    reference = json.loads(REFERENCE_MODELS.read_text(encoding="utf-8"))
    activities = {
        item["intent"]: item
        for item in json.loads(ACTIVITY_CATALOG.read_text(encoding="utf-8"))["activities"]
    }
    action_catalog = json.loads(ACTION_CATALOG.read_text(encoding="utf-8"))
    reference_kinds = {
        item["actionType"]: {
            parameter["parameterName"]: parameter.get("referenceKind") or "none"
            for parameter in item["parameters"]
        }
        for item in action_catalog["actions"]
    }

    intents = []
    for spec in INTENT_CATALOG:
        model = reference["models"].get(spec.intent_id)
        if model is None:
            continue
        activity = activities.get(spec.intent_id, {})
        steps = _build_steps(model, reference_kinds)
        intents.append(
            {
                "id": spec.intent_id,
                "label": spec.label,
                "category": str(spec.category),
                "room": spec.default_location,
                "returnRoom": spec.return_location,
                "description": activity.get("description", ""),
                "components": activity.get("components", []),
                "aruba": (activity.get("externalMappings") or {}).get("casas_aruba"),
                "modelId": model["processModelId"],
                "steps": steps,
                "pirSteps": _count(steps, "pir"),
                "walkSteps": _count(steps, "walk"),
                "contactSteps": _count(steps, "contact"),
                "blindSteps": _count(steps, "presence"),
            }
        )

    actions = [
        {
            "type": item["actionType"],
            "params": [p["parameterName"] for p in item["parameters"]],
            "gestureSeconds": PUNCTUAL_ACTION_SECONDS.get(item["actionType"]),
            "evidence": (
                "walk"
                if item["actionType"] in TRAVEL_ACTION_TYPES
                else "work"
                if item["actionType"] in PIR_ACTIVITY_ACTION_TYPES
                else "presence"
            ),
            "phrase": (
                APPENDIX_PHRASES.get(item["actionType"])
                or ACTION_PHRASES.get(item["actionType"], "")
            ),
        }
        for item in sorted(action_catalog["actions"], key=lambda item: item["actionType"])
    ]

    return {
        "intents": sorted(
            intents, key=lambda item: (_CATEGORY_ORDER[item["category"]], item["id"])
        ),
        "actions": actions,
        "categories": CATEGORY_BLURBS,
        "catalogVersion": REFERENCE_FILE.removeprefix("reference-process-models-").removesuffix(
            ".json"
        ),
        "files": {
            "reference": f"src/smart_home_sim/catalogs/{REFERENCE_FILE}",
            "activity": "src/smart_home_sim/catalogs/activity-catalog-1.4.0.json",
            "action": "src/smart_home_sim/catalogs/action-catalog-1.1.0.json",
            "intents": "src/smart_home_sim/hybrid_planning/intents.py",
            "durations": "src/smart_home_sim/simulation/service.py",
            "pir": "src/smart_home_sim/sensors/service.py",
            "roles": "src/smart_home_sim/domain/models.py",
        },
    }


def render(payload: dict[str, Any], template: Path) -> str:
    body = template.read_text(encoding="utf-8")
    marker = "{{PAYLOAD}}"
    if marker not in body:
        raise RuntimeError(f"template is missing {marker}")
    # The payload rides in a `<script type="application/json">` block, whose content is raw text
    # until the first `</script`. `\/` is a valid JSON escape for `/`, so neutralising `</` keeps
    # the document well-formed without making the JSON unparseable.
    encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return body.replace(marker, encoded)


def main() -> None:
    template = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else ROOT / "tools" / "intent_explainer.template.html"
    )
    output = (
        Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "generated" / "intent-explainer.html"
    )
    payload = build_payload()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(payload, template), encoding="utf-8", newline="\n")
    total_steps = sum(len(item["steps"]) for item in payload["intents"])
    blind = sum(item["blindSteps"] for item in payload["intents"])
    print(f"intents: {len(payload['intents'])}  steps: {total_steps}  presence-only steps: {blind}")
    print(f"written: {output}")


if __name__ == "__main__":
    main()
