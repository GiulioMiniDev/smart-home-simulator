"""Measure the properties of an observable log that give away a generated dataset.

`compare_sensor_density.py` answers "how much data", against CASAS. This answers "what shape",
against itself: the two are complementary and this one needs no external dataset, so it can gate a
change before and after.

The measures are the ones that identified the defects in `dataset_realism_gap.md`:

- whether the observable half carries `quality`, which is the noise model leaking into the data a
  researcher is supposed to receive blind;
- how temperature reporting is distributed, since a threshold that never trips leaves a heartbeat
  whose interval standard deviation is a fraction of a second — the single cheapest way to tell this
  dataset from a real one;
- the density and concentration of the motion channel, and how often the door is used.

Reads either a `run-synthetic` workspace (`observable-sensor-log.json`) or an application export
directory (`observable.csv`).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

# Interval band counted as a heartbeat rather than a threshold crossing, as a fraction of the
# configured heartbeat.
HEARTBEAT_TOLERANCE = 0.02


def _read(source: Path) -> list[dict[str, Any]]:
    workspace_log = source / "observable-sensor-log.json"
    export_log = source / "observable.csv"
    if workspace_log.is_file():
        records = json.loads(workspace_log.read_text(encoding="utf-8"))["records"]
    elif export_log.is_file():
        with export_log.open(encoding="utf-8", newline="") as handle:
            records = list(csv.DictReader(handle))
    else:
        raise SystemExit(f"no observable log in {source}")
    for record in records:
        record["ts"] = datetime.fromisoformat(record["observedAt"])
    records.sort(key=lambda item: item["ts"])
    return records


def _quantile(values: list[float], q: float) -> float:
    return values[min(len(values) - 1, int(q * len(values)))]


def _per_sensor_intervals(records: list[dict[str, Any]], sensor_type: str) -> list[float]:
    gaps: list[float] = []
    last: dict[str, datetime] = {}
    for record in records:
        if record["sensorType"] != sensor_type:
            continue
        sensor = record["sensorId"]
        if sensor in last:
            gaps.append((record["ts"] - last[sensor]).total_seconds())
        last[sensor] = record["ts"]
    gaps.sort()
    return gaps


def measure(source: Path, heartbeat_seconds: float) -> dict[str, Any]:
    records = _read(source)
    span = (records[-1]["ts"] - records[0]["ts"]).total_seconds() / 86_400
    by_type = Counter(record["sensorType"] for record in records)
    by_sensor = Counter(record["sensorId"] for record in records)

    concentration = sorted((count / len(records) for count in by_sensor.values()), reverse=True)
    running = 0.0
    sensors_for_half = 0
    for value in concentration:
        running += value
        sensors_for_half += 1
        if running >= 0.5:
            break

    result: dict[str, Any] = {
        "source": str(source),
        "days": round(span, 2),
        "records": len(records),
        "recordsPerDay": round(len(records) / span, 1),
        "sensors": len(by_sensor),
        "sensorsHoldingHalfTheEvents": sensors_for_half,
        # A real log has no such column. Its presence is a defect regardless of its value.
        "qualityLeak": "quality" in records[0],
        "byType": {
            kind: {
                "records": count,
                "share": round(count / len(records), 4),
                "perDay": round(count / span, 2),
            }
            for kind, count in by_type.most_common()
        },
    }

    temperature = _per_sensor_intervals(records, "temperature")
    if temperature:
        low = heartbeat_seconds * (1 - HEARTBEAT_TOLERANCE)
        high = heartbeat_seconds * (1 + HEARTBEAT_TOLERANCE)
        heartbeats = sum(1 for gap in temperature if low <= gap <= high)
        result["temperature"] = {
            "intervals": len(temperature),
            "medianSeconds": round(_quantile(temperature, 0.5), 1),
            "p10Seconds": round(_quantile(temperature, 0.1), 1),
            "p90Seconds": round(_quantile(temperature, 0.9), 1),
            "standardDeviationSeconds": round(statistics.pstdev(temperature), 2),
            # The headline number: a threshold that never trips leaves this near 1.0.
            "heartbeatShare": round(heartbeats / len(temperature), 4),
            "thresholdCrossingShare": round(
                sum(1 for gap in temperature if gap < heartbeat_seconds / 2) / len(temperature), 4
            ),
        }

    motion = [record for record in records if record["sensorType"] == "pir"]
    if motion:
        gaps = sorted(
            (motion[index + 1]["ts"] - motion[index]["ts"]).total_seconds()
            for index in range(len(motion) - 1)
        )
        per_room = Counter(record["sensorId"] for record in motion)
        night = sum(1 for record in motion if record["ts"].hour < 6)
        result["motion"] = {
            "records": len(motion),
            "perDay": round(len(motion) / span, 1),
            "medianGapSeconds": round(_quantile(gaps, 0.5), 1),
            "p90GapSeconds": round(_quantile(gaps, 0.9), 1),
            "gapsOverOneHour": sum(1 for gap in gaps if gap > 3600),
            "nightSharePerNight": round(night / span, 1),
            "busiestSensorShare": round(per_room.most_common(1)[0][1] / len(motion), 4),
            "quietestSensorPerDay": round(min(per_room.values()) / span, 2),
        }

    contact = [record for record in records if record["sensorType"] == "contact"]
    result["contact"] = {"records": len(contact), "perDay": round(len(contact) / span, 2)}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="run-synthetic workspace or export directory")
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=3600.0,
        help="configured temperature heartbeat, used to classify intervals",
    )
    arguments = parser.parse_args()
    print(json.dumps(measure(arguments.source, arguments.heartbeat_seconds), indent=2))


if __name__ == "__main__":
    main()
