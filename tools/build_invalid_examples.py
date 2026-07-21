"""Build readable invalid examples from the canonical minimal valid scenario."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "examples/valid/minimal.json"
TARGET_DIR = PROJECT_ROOT / "examples/invalid"


def write(name: str, payload: dict[str, Any]) -> None:
    (TARGET_DIR / name).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))

    unknown = copy.deepcopy(source)
    unknown["scenarioId"] = "unknown_references"
    activity = unknown["days"][0]["activities"][1]
    activity["actorId"] = "missing_resident"
    activity["locationIds"] = ["missing_location"]
    activity["requiredResources"] = [{"resourceId": "missing_resource", "units": 1}]
    activity["dependencyGroups"] = [{"mode": "all", "activityIds": ["missing_activity"]}]
    activity["commitmentId"] = "missing_commitment"
    write("unknown_references.json", unknown)

    cycle = copy.deepcopy(source)
    cycle["scenarioId"] = "dependency_cycle"
    cycle["days"][0]["activities"][0]["dependencyGroups"] = [
        {"mode": "all", "activityIds": ["activity_2"]}
    ]
    write("dependency_cycle.json", cycle)

    overlap = copy.deepcopy(source)
    overlap["scenarioId"] = "fixed_overlap"
    second = overlap["days"][0]["activities"][1]
    second["mandatory"] = True
    second["startWindow"] = {
        "earliest": "2026-10-12T08:15:00+02:00",
        "preferred": "2026-10-12T08:15:00+02:00",
        "latest": "2026-10-12T08:15:00+02:00",
    }
    second["duration"] = {
        "minimumMinutes": 30.0,
        "preferredMinutes": 30.0,
        "maximumMinutes": 30.0,
    }
    second["dependencyGroups"] = []
    write("fixed_overlap.json", overlap)


if __name__ == "__main__":
    main()
