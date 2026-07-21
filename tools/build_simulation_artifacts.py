from __future__ import annotations

from pathlib import Path

from smart_home_sim.simulation import replay_files, simulate_file

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json"
OUTPUT = ROOT / "examples/execution"


def main() -> None:
    result = simulate_file(BUNDLE)
    if result.trace is None:
        raise SystemExit(result.report.model_dump_json(by_alias=True, indent=2))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    trace_path = OUTPUT / "mario_week.execution-trace.json"
    trace_path.write_text(
        result.trace.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT / "mario_week.simulation-report.json").write_text(
        result.report.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    replay = replay_files(BUNDLE, trace_path)
    if not replay.matches:
        raise SystemExit("generated execution trace did not replay deterministically")
    (OUTPUT / "mario_week.replay-report.json").write_text(
        replay.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
