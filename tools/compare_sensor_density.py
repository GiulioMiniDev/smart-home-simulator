from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASAS = ROOT.parents[1] / "03_datasets/raw/casas-11-aruba/data"
DEFAULT_WORKSPACE = ROOT / "examples/materialization/mario_rossi_2026_10_30"
CASAS_TYPES = {"M": "pir", "T": "temperature", "D": "contact"}


def _metrics(
    counts: Counter[str], sensor_counts: Counter[str], days: float
) -> dict[str, dict[str, float | int]]:
    return {
        sensor_type: {
            "records": count,
            "sensors": sensor_counts[sensor_type],
            "recordsPerDay": round(count / days, 6),
            "recordsPerSensorDay": round(count / days / sensor_counts[sensor_type], 6),
        }
        for sensor_type, count in sorted(counts.items())
        if sensor_counts[sensor_type]
    }


def casas_metrics(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    sensor_ids: dict[str, set[str]] = {sensor_type: set() for sensor_type in CASAS_TYPES.values()}
    first: datetime | None = None
    last: datetime | None = None
    total_records = 0
    with path.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            total_records += 1
            fields = line.split()
            if len(fields) < 4 or not fields[2]:
                continue
            sensor_type = CASAS_TYPES.get(fields[2][0])
            if sensor_type is None:
                continue
            try:
                at = datetime.fromisoformat(f"{fields[0]}T{fields[1]}")
            except ValueError:
                continue
            first = at if first is None or at < first else first
            last = at if last is None or at > last else last
            counts[sensor_type] += 1
            sensor_ids[sensor_type].add(fields[2])
    if first is None or last is None or first == last:
        raise ValueError(f"CASAS file has no measurable time span: {path}")
    days = (last - first).total_seconds() / 86_400
    return {
        "source": str(path),
        "days": round(days, 6),
        "totalRecords": total_records,
        "supportedSensorRecords": sum(counts.values()),
        "types": _metrics(
            counts,
            Counter({name: len(values) for name, values in sensor_ids.items()}),
            days,
        ),
    }


def synthetic_metrics(workspace: Path) -> dict[str, Any]:
    log = json.loads((workspace / "observable-sensor-log.json").read_text(encoding="utf-8"))
    trace = json.loads((workspace / "execution-trace.json").read_text(encoding="utf-8"))
    model = json.loads((workspace / "sensor-model.json").read_text(encoding="utf-8"))
    days = (
        datetime.fromisoformat(trace["endedAt"]) - datetime.fromisoformat(trace["startedAt"])
    ).total_seconds() / 86_400
    counts = Counter(record["sensorType"] for record in log["records"])
    sensor_counts = Counter(sensor["sensorType"] for sensor in model["sensors"])
    return {
        "source": str(workspace),
        "days": round(days, 6),
        "totalRecords": len(log["records"]),
        "types": _metrics(counts, sensor_counts, days),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare CASAS Aruba and generated sensor volume per device/day."
    )
    parser.add_argument("--casas", type=Path, default=DEFAULT_CASAS)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    arguments = parser.parse_args()
    print(
        json.dumps(
            {
                "casasAruba": casas_metrics(arguments.casas),
                "synthetic": synthetic_metrics(arguments.workspace),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
