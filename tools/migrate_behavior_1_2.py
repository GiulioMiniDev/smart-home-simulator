"""Derive activity catalog 1.2.0 and reference process models 1.2.0 from the 1.1.0 instances.

Catalog 1.1.0 inherited its vocabulary from the Mario Rossi acceptance case, so seven intents name
private individuals: `call_mother`, `call_sister_lucia`, `call_friend_paolo`, `aperitivo_with_paolo`
and the three `..._mother` visit intents. Because an intent id *is* the ground-truth label published
in the dataset, a generated persona with no sister had to reuse `call_sister_lucia` to express
"phones a relative", and the label then asserted something untrue about the simulated resident.

This migration makes the vocabulary neutral. The three phone intents were already byte-identical in
semantics — same `phone_call` component, same `relevantVariableIds` — so they collapse into a single
`phone_call`; the remaining four are renamed. Identity of the person on the other end belongs in the
scenario, which already models it through `externalPeople` and an activity's `participantIds`.

Catalogs 1.0.0 and 1.1.0 are untouched, so every artifact pinned to them keeps validating and
replaying exactly as before.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "src/smart_home_sim/catalogs"

SOURCE_ACTIVITY_CATALOG = CATALOG_DIR / "activity-catalog-1.1.0.json"
TARGET_ACTIVITY_CATALOG = CATALOG_DIR / "activity-catalog-1.2.0.json"
SOURCE_REFERENCE_MODELS = CATALOG_DIR / "reference-process-models-1.1.0.json"
TARGET_REFERENCE_MODELS = CATALOG_DIR / "reference-process-models-1.2.0.json"

TARGET_VERSION = "1.2.0"

# Several source intents may map to one target intent: the three phone calls differ only by who is
# called, which the scenario expresses through participants rather than through the label.
INTENT_RENAMES: dict[str, str] = {
    "call_mother": "phone_call",
    "call_sister_lucia": "phone_call",
    "call_friend_paolo": "phone_call",
    "aperitivo_with_paolo": "social_drink_out",
    "prepare_to_visit_mother": "prepare_to_visit_relative",
    "travel_to_mothers_home": "travel_to_relatives_home",
    "visit_mother_and_have_dinner": "visit_relative_and_have_dinner",
}

DISPLAY_NAMES: dict[str, str] = {
    "phone_call": "Phone call",
    "social_drink_out": "Social drink out",
    "prepare_to_visit_relative": "Prepare to visit relative",
    "travel_to_relatives_home": "Travel to relative's home",
    "visit_relative_and_have_dinner": "Visit relative and have dinner",
}

# The reference models were extracted from one resident, so their prose carries his name and his
# health condition. A shared reference must not describe a specific person: the models are
# retargeted to whatever persona is being authored, and a persona with healthy knees would inherit
# a description asserting osteoarthritis.
RESIDENT_PROSE = re.compile(r"resident_mario_rossi|Mario Rossi|\bMario\b", flags=re.IGNORECASE)
RESIDENT_CONDITION = re.compile(
    r",? ?(avoiding abrupt changes )?because of mild right-knee osteoarthritis", flags=re.IGNORECASE
)


def _neutral_model_prose(text: str) -> str:
    text = RESIDENT_CONDITION.sub("", text)
    text = RESIDENT_PROSE.sub("the resident", text)
    # "his usual medication" reads oddly once the subject is generic, and gender is persona data.
    text = re.sub(r"\bhis\b", "their", text)
    text = re.sub(r"\s+", " ", text).strip()
    # The name could sit mid-sentence, so capitalize only where a sentence actually starts.
    return re.sub(r"(^|(?<=\. ))the resident", "The resident", text)


def _neutral_description(intent: str, source: str) -> str:
    """Rewrite the generated per-intent prose so it no longer quotes the old intent id."""
    tail = source.split(". ", 1)
    suffix = tail[1] if len(tail) == 2 else ""
    head = f"Project-specific activity intent '{intent}'."
    return f"{head} {suffix}".strip()


def activity_catalog() -> dict[str, Any]:
    source = json.loads(SOURCE_ACTIVITY_CATALOG.read_text(encoding="utf-8"))
    merged: dict[str, dict[str, Any]] = {}

    for activity in source["activities"]:
        old_intent = activity["intent"]
        new_intent = INTENT_RENAMES.get(old_intent, old_intent)
        entry = dict(activity)
        entry["intent"] = new_intent

        if old_intent != new_intent:
            entry["displayName"] = DISPLAY_NAMES[new_intent]
            entry["description"] = _neutral_description(new_intent, activity["description"])

        if new_intent in merged:
            # A collapse target: the sources must agree, or the merge would silently pick one.
            existing = merged[new_intent]
            for field in ("components", "category"):
                if existing[field] != entry[field]:
                    raise ValueError(
                        f"cannot merge '{old_intent}' into '{new_intent}': "
                        f"{field} differs ({existing[field]!r} vs {entry[field]!r})"
                    )
            existing["relevantVariableIds"] = sorted(
                set(existing["relevantVariableIds"]) | set(entry["relevantVariableIds"])
            )
            continue

        merged[new_intent] = entry

    return {
        **source,
        "catalogVersion": TARGET_VERSION,
        "activities": [merged[key] for key in sorted(merged)],
    }


def reference_models() -> dict[str, Any]:
    source = json.loads(SOURCE_REFERENCE_MODELS.read_text(encoding="utf-8"))
    models: dict[str, Any] = {}

    for intent, model in source["models"].items():
        new_intent = INTENT_RENAMES.get(intent, intent)
        if new_intent in models:
            raise ValueError(
                f"two reference models would collapse onto '{new_intent}'; "
                "the reduced alphabet must keep exactly one model per intent"
            )
        entry = dict(model)
        entry["processModelId"] = f"reference__{new_intent}"
        entry["processModelVersion"] = TARGET_VERSION
        entry["title"] = f"reference {new_intent.replace('_', ' ')} process"
        entry["description"] = _neutral_model_prose(entry.get("description", ""))
        models[new_intent] = entry

    return {
        **source,
        "schemaVersion": source.get("schemaVersion", "1.0.0"),
        "sourcePackage": f"{source['sourcePackage']} (neutralized {TARGET_VERSION})",
        "models": {key: models[key] for key in sorted(models)},
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    source = json.loads(SOURCE_ACTIVITY_CATALOG.read_text(encoding="utf-8"))
    catalog = activity_catalog()
    write_json(TARGET_ACTIVITY_CATALOG, catalog)
    models = reference_models()
    write_json(TARGET_REFERENCE_MODELS, models)
    print(
        f"activity catalog {TARGET_VERSION}: {len(catalog['activities'])} intents "
        f"(from {len(source['activities'])})"
    )
    print(f"reference process models {TARGET_VERSION}: {len(models['models'])}")


if __name__ == "__main__":
    main()
