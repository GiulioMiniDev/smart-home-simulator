from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/valid/mario_week.json"
TARGET = ROOT / "examples/valid/mario_week.runtime-1.1.0.json"
SCENARIO_ID = "mario_rossi_week_2026_10_12__runtime_1.1.0"


ACTIVITY_EFFECTS: dict[str, list[dict[str, Any]]] = {
    "d1_a12": [
        {"fact": "dinner_ingredients_available", "operation": "set", "value": True},
        {
            "fact": "resident.pendingTasks",
            "operation": "remove",
            "value": "buy_groceries",
        },
    ],
    "d1_a17": [
        {"fact": "washing_cycle_complete", "operation": "set", "value": True},
        {
            "fact": "resident.pendingTasks",
            "operation": "remove",
            "value": "wash_work_shirts",
        },
    ],
    "d1_a19": [{"fact": "clean_work_shirts_available", "operation": "set", "value": True}],
    "d5_a17": [{"fact": "light_dinner_prepared", "operation": "set", "value": True}],
    "d6_a09": [
        {"fact": "meal_prep_ingredients_available", "operation": "set", "value": True},
        {"fact": "dinner_ingredients_available", "operation": "set", "value": True},
    ],
    "d7_a06": [{"fact": "washing_cycle_complete", "operation": "set", "value": True}],
}


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    scenario = json.loads(source_bytes)
    scenario["scenarioId"] = SCENARIO_ID
    scenario["title"] = f"{scenario.get('title', 'Mario Rossi week')} — runtime semantics 1.1.0"
    scenario["provenance"] = {
        "authorType": "rule_generator",
        "generatorName": "migrate_runtime_scenario_1_1",
        "generatorVersion": "1.1.0",
        "modelName": None,
        "promptTemplateVersion": None,
        "generatedAt": "2026-07-21T12:00:00+02:00",
        "humanReviewed": True,
        "parameters": {
            "sourceScenarioSha256": hashlib.sha256(source_bytes).hexdigest(),
            "factMaterializationPolicy": "explicit-producers-1.1.0",
        },
    }
    scenario["initialState"].setdefault("environmentFacts", {}).update(
        {
            "pending_dirty_breakfast_dishes": True,
            "recycling_bin_near_full": True,
            "refill_available": True,
            "resident_still_hungry": True,
            "snack_food_available": True,
        }
    )
    for day in scenario["days"]:
        for activity in day["activities"]:
            if activity["activityId"] in ACTIVITY_EFFECTS:
                if activity.get("effects"):
                    raise ValueError(
                        f"activity {activity['activityId']} unexpectedly has existing effects"
                    )
                activity["effects"] = ACTIVITY_EFFECTS[activity["activityId"]]
    TARGET.write_text(
        json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
