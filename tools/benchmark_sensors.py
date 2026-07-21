from __future__ import annotations

import time
from pathlib import Path

from smart_home_sim.sensors import project_sensor_files

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "examples/execution/mario_week.execution-trace.json"
BUNDLE = ROOT / "examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json"
MODEL = ROOT / "examples/sensors/mario_monteverde.sensor-model.json"
TARGET_SECONDS = 5.0


def main() -> None:
    started = time.perf_counter()
    result = project_sensor_files(TRACE, BUNDLE, MODEL)
    elapsed = time.perf_counter() - started
    if result.observable_log is None:
        raise SystemExit("sensor benchmark failed to produce an observable log")
    if elapsed >= TARGET_SECONDS:
        raise SystemExit(
            f"sensor projection took {elapsed:.3f}s; target is < {TARGET_SECONDS:.1f}s"
        )
    print(
        f"M6 weekly benchmark: {elapsed:.3f}s, "
        f"{result.report.summary.sensor_count} sensors, "
        f"{result.report.summary.observation_count} observations"
    )


if __name__ == "__main__":
    main()
