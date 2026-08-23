"""Measure bounded replay queries against complete weekly, monthly, and yearly fixtures."""

from __future__ import annotations

import json
import os
import random
import statistics
import tempfile
import time
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from smart_home_sim.application.replay import ReplayService
from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobStatus
from smart_home_sim.domain.sensors import OracleObservationLink
from smart_home_sim.simulation import trace_semantic_digest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEEKLY_SOURCE = PROJECT_ROOT / "examples" / "materialization" / "mario_rossi_2026_10_30"
FRAME_COUNT = 100
WINDOW_COUNT = 100
WINDOW_LIMIT = 37
WEEKLY_PERIODS = 2
MONTHLY_PERIODS = 8
YEARLY_PERIODS = 104

_TRACE_FAMILIES = (
    "activityExecutions",
    "actionExecutions",
    "movements",
    "stateTransitions",
    "resourceEvents",
    "runtimeEvents",
    "planDeviations",
    "dailySummaries",
)
_IDENTIFIER_FIELDS = (
    "activityExecutionId",
    "sourceActivityId",
    "actionExecutionId",
    "movementId",
    "transitionId",
    "resourceEventId",
    "eventExecutionId",
    "deviationId",
)
_REFERENCE_FIELDS = set(_IDENTIFIER_FIELDS) | {
    "activityExecutionIds",
    "actionExecutionIds",
    "deviationIds",
    "causeId",
    "causeIds",
    "triggerActivityId",
}


def _canonical_sha256(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _shift_and_remap(
    value: Any, delta: timedelta, identifiers: dict[str, str], key: str = ""
) -> Any:
    if isinstance(value, list):
        return [_shift_and_remap(item, delta, identifiers, key) for item in value]
    if isinstance(value, dict):
        return {
            item_key: _shift_and_remap(item, delta, identifiers, item_key)
            for item_key, item in value.items()
        }
    if not isinstance(value, str):
        return value
    if key in _REFERENCE_FIELDS:
        return identifiers.get(value, value)
    if "T" in value:
        try:
            return (datetime.fromisoformat(value.replace("Z", "+00:00")) + delta).isoformat()
        except ValueError:
            return value
    if key == "date":
        try:
            return (date.fromisoformat(value) + delta).isoformat()
        except ValueError:
            return value
    return value


def _normalize_time_span(
    value: Any, *, start: datetime, raw_span: timedelta, target_span: timedelta, key: str = ""
) -> Any:
    """Affine-normalize a contiguous synthetic span without gaps or record removal."""
    if isinstance(value, list):
        return [
            _normalize_time_span(
                item, start=start, raw_span=raw_span, target_span=target_span, key=key
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            item_key: _normalize_time_span(
                item,
                start=start,
                raw_span=raw_span,
                target_span=target_span,
                key=item_key,
            )
            for item_key, item in value.items()
        }
    if not isinstance(value, str):
        return value
    scale = target_span / raw_span
    if "T" in value:
        try:
            at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return (start + (at - start) * scale).isoformat()
    if key == "date":
        try:
            at = datetime.combine(date.fromisoformat(value), datetime.min.time(), start.tzinfo)
        except ValueError:
            return value
        return (start + (at - start) * scale).date().isoformat()
    return value


def _period_identifiers(trace: dict[str, Any], period: int) -> dict[str, str]:
    suffix = f"__benchmark_period_{period:02d}"
    identifiers: dict[str, str] = {}
    for family in _TRACE_FAMILIES:
        for record in trace[family]:
            for field in _IDENTIFIER_FIELDS:
                value = record.get(field)
                if isinstance(value, str):
                    identifiers[value] = f"{value}{suffix}"
    return identifiers


def _with_runtime_coverage_sentinel(trace: dict[str, Any]) -> dict[str, Any]:
    """Add the documented fixture-only runtime family sentinel to an otherwise complete source."""
    result = json.loads(json.dumps(trace))
    result["runtimeEvents"].append(
        {
            "eventExecutionId": "runtime_coverage_sentinel",
            "eventId": "benchmark_runtime_coverage_sentinel",
            "sampled": False,
            "occurred": False,
            "evaluatedAt": result["startedAt"],
            "triggerActivityId": None,
            "sampledAmounts": [],
            "outcome": "not_sampled",
        }
    )
    return result


def _finalize_observable_log(payload: dict[str, Any]) -> None:
    semantic = {
        "sensorModelId": payload["sensorModelId"],
        "sensorModelVersion": payload["sensorModelVersion"],
        "records": payload["records"],
    }
    digest = _canonical_sha256(semantic)
    payload["semanticDigest"] = digest
    payload["logId"] = f"sensor_log_{digest[:16]}"


def _finalize_oracle_mapping(payload: dict[str, Any]) -> None:
    semantic_links = [
        OracleObservationLink.model_validate(item).model_dump(mode="json")
        for item in payload["links"]
    ]
    payload["mappingId"] = f"oracle_{_canonical_sha256(semantic_links)[:16]}"


def _benchmark_fixture(source: Path, target: Path, *, periods: int, duration_days: int) -> None:
    """Build a contiguous, full-density fixture with an exact canonical duration."""
    if periods < 1:
        raise ValueError("expanded replay fixture needs at least one period")
    if duration_days < 1:
        raise ValueError("benchmark fixture duration must be at least one day")
    target.mkdir(parents=True)
    trace = _with_runtime_coverage_sentinel(
        json.loads((source / "execution-trace.json").read_text(encoding="utf-8"))
    )
    observations = json.loads((source / "observable-sensor-log.json").read_text(encoding="utf-8"))
    oracle = json.loads((source / "oracle-mapping.json").read_text(encoding="utf-8"))
    source_digest = _canonical_sha256(trace["semanticDigest"])
    trace_id = f"trace_benchmark_{duration_days}d_{periods}p_{source_digest[:12]}"
    source_links = {item["observationId"]: item for item in oracle["links"]}
    trace_year = {key: value for key, value in trace.items() if key not in _TRACE_FAMILIES}
    trace_year.update({family: [] for family in _TRACE_FAMILIES})
    observation_year = {key: value for key, value in observations.items() if key != "records"}
    observation_year["records"] = []
    oracle_year = {key: value for key, value in oracle.items() if key != "links"}
    oracle_year["links"] = []
    source_start = datetime.fromisoformat(trace["startedAt"].replace("Z", "+00:00"))
    source_end = datetime.fromisoformat(trace["endedAt"].replace("Z", "+00:00"))
    source_span = source_end - source_start
    for period in range(periods):
        delta = source_span * period
        identifiers = _period_identifiers(trace, period)
        identifiers[trace["traceId"]] = trace_id
        for family in _TRACE_FAMILIES:
            trace_year[family].extend(
                _shift_and_remap(record, delta, identifiers) for record in trace[family]
            )
        for record in observations["records"]:
            item = _shift_and_remap(record, delta, identifiers)
            observation_id = record["observationId"]
            remapped_id = f"{observation_id}__benchmark_period_{period:02d}"
            item["observationId"] = remapped_id
            observation_year["records"].append(item)
            link = _shift_and_remap(source_links[observation_id], delta, identifiers)
            link["observationId"] = remapped_id
            oracle_year["links"].append(link)
    raw_span = source_span * periods
    target_span = timedelta(days=duration_days)
    trace_year["traceId"] = trace_id
    trace_year["sourceBundleId"] = f"benchmark-fixture-{duration_days}d-{periods}p"
    trace_year["sourceBundleSha256"] = _canonical_sha256(
        {"source": trace["sourceBundleSha256"], "periods": periods}
    )
    trace_year = _normalize_time_span(
        trace_year, start=source_start, raw_span=raw_span, target_span=target_span
    )
    trace_year["endedAt"] = (source_start + target_span).isoformat()
    trace_year["semanticDigest"] = trace_semantic_digest(trace_year)
    observation_year = _normalize_time_span(
        observation_year, start=source_start, raw_span=raw_span, target_span=target_span
    )
    observation_year["endedAt"] = (source_start + target_span).isoformat()
    observation_year["records"].sort(
        key=lambda item: (item["observedAt"], item["sensorId"], item["observationId"])
    )
    _finalize_observable_log(observation_year)
    oracle_year["observableLogId"] = observation_year["logId"]
    oracle_year["sourceTraceId"] = trace_id
    oracle_year["sourceTraceSemanticDigest"] = trace_year["semanticDigest"]
    _finalize_oracle_mapping(oracle_year)
    for filename, payload in (
        ("execution-trace.json", trace_year),
        ("observable-sensor-log.json", observation_year),
        ("oracle-mapping.json", oracle_year),
    ):
        (target / filename).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def _completed_workspace(
    root: Path,
    *,
    periods: int,
    duration_days: int,
    observable_only: bool = False,
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
    _benchmark_fixture(WEEKLY_SOURCE, destination, periods=periods, duration_days=duration_days)
    if observable_only:
        # Frame/window timings are Observable-only. Keeping typed Oracle links resident
        # would measure optional disclosure metadata rather than replay reconstruction.
        (destination / "oracle-mapping.json").unlink()
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


def _measure(label: str, workspace: WorkspaceService, run_id: str) -> dict[str, Any]:
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
    trace = index.trace
    return {
        "fixture": label,
        "construction": (
            "contiguous full-density source periods with affine-normalized timestamps, "
            "remapped IDs, causality, and a fixture-only runtime coverage sentinel"
        ),
        "durationDays": round((index.trace_end - index.trace_start).total_seconds() / 86_400, 3),
        "activities": len(trace.activity_executions),
        "actions": len(trace.action_executions),
        "movements": len(trace.movements),
        "transitions": len(trace.state_transitions),
        "resources": len(trace.resource_events),
        "runtimeEvents": len(trace.runtime_events),
        "planDeviations": len(trace.plan_deviations),
        "observations": len(index.observations.records),
        "events": len(index.events),
        "indexMs": _milliseconds(index_seconds),
        "medianFrameMs": _milliseconds(median_frame),
        "medianWindowMs": _milliseconds(statistics.median(window_seconds)),
        "frameSamples": FRAME_COUNT,
        "windowSamples": WINDOW_COUNT,
    }


def main() -> None:
    fixtures = [
        ("weekly", WEEKLY_PERIODS, 7, False),
        ("four-week-month-scale", MONTHLY_PERIODS, 28, False),
        ("yearly", YEARLY_PERIODS, 364, True),
    ]
    with tempfile.TemporaryDirectory(prefix="smart-home-replay-benchmark-") as temporary:
        results = []
        for label, periods, duration_days, observable_only in fixtures:
            workspace, run_id = _completed_workspace(
                Path(temporary) / label,
                periods=periods,
                duration_days=duration_days,
                observable_only=observable_only,
            )
            results.append(_measure(label, workspace, run_id))
    result = {
        "acceptance": {
            "frameMedianMs": "< 100 after index construction",
            "invariants": [
                "all trace families retained",
                "bounded windows",
                "equal repeated frames",
            ],
            "timingsFailOnlyInCi": True,
        },
        "fixtures": results,
    }
    print(json.dumps(result, sort_keys=True))
    if os.environ.get("CI") and any(item["medianFrameMs"] >= 100 for item in results):
        raise SystemExit("replay benchmark exceeded the 100 ms median frame acceptance target")


if __name__ == "__main__":
    main()
