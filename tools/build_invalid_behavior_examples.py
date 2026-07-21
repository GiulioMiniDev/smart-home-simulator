"""Build readable invalid process packages from the minimal accepted package."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "examples/behavior/minimal_valid_scenario.behavior.json"
TARGET = ROOT / "examples/behavior/invalid"


def write(name: str, value: dict[str, Any]) -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / name).write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))

    unknown_action = copy.deepcopy(source)
    unknown_action["packageId"] = "invalid_unknown_action"
    unknown_action["processModels"][0]["nodes"][1]["actionType"] = "teleport"
    write("unknown_action.json", unknown_action)

    missing_binding = copy.deepcopy(source)
    missing_binding["packageId"] = "invalid_missing_binding"
    missing_binding["bindings"] = missing_binding["bindings"][1:]
    write("missing_binding.json", missing_binding)

    unbounded_cycle = copy.deepcopy(source)
    unbounded_cycle["packageId"] = "invalid_unbounded_cycle"
    unbounded_cycle["processModels"][0]["edges"].append(
        {"sourceNodeId": "step_3", "targetNodeId": "step_1"}
    )
    write("unbounded_cycle.json", unbounded_cycle)


if __name__ == "__main__":
    main()
