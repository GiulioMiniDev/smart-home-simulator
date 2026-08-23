"""Measure bounded replay queries against weekly, monthly, and yearly fixtures."""

from __future__ import annotations

import json
import os
import random
import shutil
import statistics
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from smart_home_sim.application.replay import ReplayService
from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEEKLY_SOURCE = PROJECT_ROOT / "examples" / "materialization" / "mario_rossi_2026_10_30"
MONTHLY_SOURCE = PROJECT_ROOT / "generated" / "lucia_rossi_august_2026" / "simulation-1.1.0"
FRAME_COUNT = 100
WINDOW_COUNT = 100
WINDOW_LIMIT = 37
YEARLY_SAMPLE_STRIDE = 100
MONTHLY_SAMPLE_STRIDE = 14


def _shift_timestamps(value: Any, delta: timedelta) -> Any:
    if isinstance(value, list):
        return [_shift_timestamps(item, delta) for item in value]
    if isinstance(value, dict):
        return {key: _shift_timestamps(item, delta) for key, item in value.items()}
    if isinstance(value, str) and "T" in value:
        try:
            return (datetime.fromisoformat(value.replace("Z", "+00:00")) + delta).isoformat()
        except ValueError:
            return value
    return value


def _finalize_observable_log(payload: dict[str, Any]) -> None:
    semantic = {
        "sensorModelId": payload["sensorModelId"],
        "sensorModelVersion": payload["sensorModelVersion"],
        "records": payload["records"],
    }
    digest = sha256(
        json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload["semanticDigest"] = digest
    payload["logId"] = f"sensor_log_{digest[:16]}"


def _yearly_fixture(target: Path) -> None:
    """Expand the checked-in week into timestamp-shifted, deterministic calendar-year data."""
    target.mkdir(parents=True)
    trace = json.loads((WEEKLY_SOURCE / "execution-trace.json").read_text(encoding="utf-8"))
    observations = json.loads(
        (WEEKLY_SOURCE / "observable-sensor-log.json").read_text(encoding="utf-8")
    )
    trace_year = deepcopy(trace)
    trace_lists = [
        "activityExecutions",
        "actionExecutions",
        "movements",
        "stateTransitions",
        "resourceEvents",
        "runtimeEvents",
        "planDeviations",
    ]
    for name in trace_lists:
        # Preserve an annual timestamp span without multiplying a browser-scale benchmark into
        # hundreds of megabytes. The sample is deterministic and still includes every trace family.
        records = [] if name == "planDeviations" else trace[name][::YEARLY_SAMPLE_STRIDE]
        trace_year[name] = [
            item
            for week in range(52)
            for item in _shift_timestamps(records, timedelta(days=7 * week))
        ]
    trace_year["endedAt"] = _shift_timestamps(trace["endedAt"], timedelta(days=7 * 51))
    observation_year = deepcopy(observations)
    observation_year["records"] = []
    for week in range(52):
        for item in _shift_timestamps(
            observations["records"][::YEARLY_SAMPLE_STRIDE], timedelta(days=7 * week)
        ):
            item["observationId"] = f"{item['observationId']}_week_{week:02d}"
            observation_year["records"].append(item)
    observation_year["endedAt"] = _shift_timestamps(observations["endedAt"], timedelta(days=7 * 51))
    _finalize_observable_log(observation_year)
    (target / "execution-trace.json").write_text(
        json.dumps(trace_year, separators=(",", ":")), encoding="utf-8"
    )
    (target / "observable-sensor-log.json").write_text(
        json.dumps(observation_year, separators=(",", ":")), encoding="utf-8"
    )


def _sampled_fixture(source: Path, target: Path, stride: int) -> None:
    """Keep the real fixture's calendar span while making repeatable local benchmarks bounded."""
    target.mkdir(parents=True)
    trace = json.loads((source / "execution-trace.json").read_text(encoding="utf-8"))
    for name in (
        "activityExecutions",
        "actionExecutions",
        "movements",
        "stateTransitions",
        "resourceEvents",
        "runtimeEvents",
    ):
        trace[name] = trace[name][::stride]
    trace["planDeviations"] = []
    observations = json.loads((source / "observable-sensor-log.json").read_text(encoding="utf-8"))
    observations["records"] = observations["records"][::stride]
    _finalize_observable_log(observations)
    (target / "execution-trace.json").write_text(
        json.dumps(trace, separators=(",", ":")), encoding="utf-8"
    )
    (target / "observable-sensor-log.json").write_text(
        json.dumps(observations, separators=(",", ":")), encoding="utf-8"
    )


def _completed_workspace(
    root: Path,
    source: Path | None,
    *,
    yearly: bool = False,
    sample_stride: int | None = None,
) -> tuple[WorkspaceService, str]:
    workspace = WorkspaceService.create(root, "Replay benchmark")
    home = workspace.create_home("Benchmark home")
    job = workspace.create_job("simulation", home_id=home.home_id, seed=123)
    workspace.update_job(
        job.job_id,
        JobStatus.running,
        JobProgress(phase="execution", percent=50, message="Executing"),
    )
    destination = workspace.runs_path / job.job_id
    if yearly:
        _yearly_fixture(destination)
    else:
        assert source is not None
        if sample_stride is None:
            shutil.copytree(source, destination)
        else:
            _sampled_fixture(source, destination, sample_stride)
    workspace.import_run_directory(job.job_id, destination)
    workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Done"),
        result_reference=job.job_id,
    )
    return workspace, job.job_id


def _milliseconds(seconds: float) -> float:
    return round(seconds * 1_000, 3)


def _measure(label: str, workspace: WorkspaceService, run_id: str) -> dict[str, float | int | str]:
    replay = ReplayService(workspace)
    started = time.perf_counter()
    index = replay._index(run_id)
    index_seconds = time.perf_counter() - started
    rng = random.Random(f"replay-benchmark-v1:{label}")
    instants = [
        index.event_times[rng.randrange(len(index.event_times))] for _ in range(FRAME_COUNT)
    ]

    frame_seconds: list[float] = []
    for instant in instants:
        started = time.perf_counter()
        first = replay.frame(run_id, at=instant)
        frame_seconds.append(time.perf_counter() - started)
        assert first == replay.frame(run_id, at=instant), "repeated replay frames must be equal"

    window_seconds: list[float] = []
    for instant in instants[:WINDOW_COUNT]:
        started = time.perf_counter()
        first = replay.events(
            run_id,
            start=instant - timedelta(minutes=30),
            end=instant + timedelta(minutes=30),
            limit=WINDOW_LIMIT,
        )
        window_seconds.append(time.perf_counter() - started)
        assert len(first.items) <= WINDOW_LIMIT, "event windows must remain bounded"
        assert first == replay.events(
            run_id,
            start=instant - timedelta(minutes=30),
            end=instant + timedelta(minutes=30),
            limit=WINDOW_LIMIT,
        ), "repeated bounded windows must be equal"

    median_frame = statistics.median(frame_seconds)
    return {
        "fixture": label,
        "events": len(index.events),
        "indexMs": _milliseconds(index_seconds),
        "medianFrameMs": _milliseconds(median_frame),
        "medianWindowMs": _milliseconds(statistics.median(window_seconds)),
        "frameSamples": FRAME_COUNT,
        "windowSamples": WINDOW_COUNT,
    }


def main() -> None:
    fixtures = [
        ("weekly", WEEKLY_SOURCE, False, None),
        ("monthly", MONTHLY_SOURCE, False, MONTHLY_SAMPLE_STRIDE),
        ("yearly", None, True, None),
    ]
    with tempfile.TemporaryDirectory(prefix="smart-home-replay-benchmark-") as temporary:
        results = []
        for label, source, yearly, sample_stride in fixtures:
            workspace, run_id = _completed_workspace(
                Path(temporary) / label, source, yearly=yearly, sample_stride=sample_stride
            )
            results.append(_measure(label, workspace, run_id))
    result = {
        "acceptance": {
            "frameMedianMs": "< 100 after index construction",
            "invariants": ["bounded windows", "equal repeated frames", "no unbounded response"],
            "timingsFailOnlyInCi": True,
        },
        "fixtures": results,
    }
    print(json.dumps(result, sort_keys=True))
    if os.environ.get("CI") and any(item["medianFrameMs"] >= 100 for item in results):
        raise SystemExit("replay benchmark exceeded the 100 ms median frame acceptance target")


if __name__ == "__main__":
    main()
