from __future__ import annotations

import time
from pathlib import Path

from smart_home_sim.simulation import simulate_file

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json"
TARGET_SECONDS = 15.0


def main() -> None:
    started = time.perf_counter()
    result = simulate_file(BUNDLE)
    elapsed = time.perf_counter() - started
    if result.trace is None:
        raise SystemExit("simulation benchmark failed to produce a trace")
    if elapsed >= TARGET_SECONDS:
        raise SystemExit(
            f"simulation benchmark took {elapsed:.3f}s; target is < {TARGET_SECONDS:.1f}s"
        )
    print(
        f"M5 weekly benchmark: {elapsed:.3f}s, "
        f"{len(result.trace.activity_executions)} activities, "
        f"{len(result.trace.action_executions)} actions, "
        f"{len(result.trace.movements)} movements"
    )


if __name__ == "__main__":
    main()
