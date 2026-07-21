from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from smart_home_sim.environment import build_bundle_files

ROOT = Path(__file__).parents[1]
TARGET_SECONDS = 15.0


def main() -> None:
    started = perf_counter()
    result = build_bundle_files(
        ROOT / "examples/valid/mario_week.json",
        ROOT / "examples/compiled/mario_week.plan.json",
        ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior.json",
        ROOT / "examples/environment/mario_monteverde.home.json",
    )
    elapsed = perf_counter() - started
    if result.bundle is None:
        raise RuntimeError(result.report.model_dump_json(by_alias=True))
    print(
        json.dumps(
            {
                "benchmarkVersion": "environment-binding-1.0.0",
                "elapsedSeconds": round(elapsed, 6),
                "targetSeconds": TARGET_SECONDS,
                "actionBindings": result.report.summary.action_binding_count,
                "routeChecks": result.report.summary.route_check_count,
                "passed": elapsed <= TARGET_SECONDS,
            },
            sort_keys=True,
        )
    )
    if elapsed > TARGET_SECONDS:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
