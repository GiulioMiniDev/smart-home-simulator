from __future__ import annotations

from pathlib import Path

from smart_home_sim.sensors import project_sensor_files

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "examples/execution/mario_week.execution-trace.json"
BUNDLE = ROOT / "examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json"
MODEL = ROOT / "examples/sensors/mario_monteverde.sensor-model.json"
OUTPUT = ROOT / "examples/sensors"


def _write(path: Path, content: str) -> None:
    path.write_text(content + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    result = project_sensor_files(TRACE, BUNDLE, MODEL)
    if result.observable_log is None or result.oracle_mapping is None:
        raise SystemExit(result.report.model_dump_json(by_alias=True, indent=2))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write(
        OUTPUT / "mario_week.observable-sensor-log.json",
        result.observable_log.model_dump_json(by_alias=True, indent=2),
    )
    _write(
        OUTPUT / "mario_week.oracle-mapping.json",
        result.oracle_mapping.model_dump_json(by_alias=True, indent=2),
    )
    _write(
        OUTPUT / "mario_week.sensor-projection-report.json",
        result.report.model_dump_json(by_alias=True, indent=2),
    )


if __name__ == "__main__":
    main()
