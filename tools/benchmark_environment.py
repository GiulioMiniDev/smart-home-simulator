from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from smart_home_sim.environment import build_bundle_files

ROOT = Path(__file__).parents[1]
TARGET_SECONDS = 15.0


def main() -> None:
    warmup_started = perf_counter()
    first = build_bundle_files(
        ROOT / "examples/valid/mario_week.json",
        ROOT / "examples/compiled/mario_week.plan.json",
        ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior.json",
        ROOT / "examples/environment/mario_monteverde.home.json",
    )
    warmup_elapsed = perf_counter() - warmup_started
    if first.bundle is None:
        raise RuntimeError(first.report.model_dump_json(by_alias=True))

    # The first build exercises every upstream correctness gate, including deterministic
    # M2 recompilation. The timed build reuses only that process-local digest cache and
    # therefore isolates the M4 validation, routing and binding workload owned by this
    # benchmark. `make check` measures M2 separately through its explicit compile target.
    started = perf_counter()
    second = build_bundle_files(
        ROOT / "examples/valid/mario_week.json",
        ROOT / "examples/compiled/mario_week.plan.json",
        ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior.json",
        ROOT / "examples/environment/mario_monteverde.home.json",
    )
    elapsed = perf_counter() - started
    if second.bundle is None:
        raise RuntimeError(second.report.model_dump_json(by_alias=True))
    deterministic = second.bundle == first.bundle and second.report == first.report
    passed = elapsed <= TARGET_SECONDS and deterministic
    print(
        json.dumps(
            {
                "benchmarkVersion": "environment-binding-1.0.0",
                "warmupSeconds": round(warmup_elapsed, 6),
                "elapsedSeconds": round(elapsed, 6),
                "targetSeconds": TARGET_SECONDS,
                "actionBindings": second.report.summary.action_binding_count,
                "routeChecks": second.report.summary.route_check_count,
                "deterministic": deterministic,
                "passed": passed,
            },
            sort_keys=True,
        )
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
