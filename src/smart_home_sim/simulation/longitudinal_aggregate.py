from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

from smart_home_sim.domain.execution import DailyExecutionSummary, ExecutionTrace
from smart_home_sim.domain.sensors import (
    ObservableSensorLog,
    ObservableSensorRecord,
    OracleMapping,
    OracleObservationLink,
)


def _canonical_json_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _trace_semantic_digest(payload: dict[str, Any]) -> str:
    semantic = {
        key: payload[key]
        for key in (
            "sourceBundleId",
            "seed",
            "activityExecutions",
            "actionExecutions",
            "movements",
            "stateTransitions",
            "resourceEvents",
            "runtimeEvents",
            "planDeviations",
            "finalState",
        )
    }
    return _canonical_json_digest(semantic)


def aggregate_execution_traces(
    run_id: str,
    seed: int,
    traces: Sequence[ExecutionTrace],
) -> ExecutionTrace:
    if not traces:
        raise ValueError("traces sequence must not be empty")

    source_bundle_id = f"longitudinal_{run_id}"
    concat_bundle_shas = b":".join(t.source_bundle_sha256.encode("utf-8") for t in traces)
    source_bundle_sha256 = hashlib.sha256(concat_bundle_shas).hexdigest()

    started_at = traces[0].started_at
    ended_at = traces[-1].ended_at
    final_state = traces[-1].final_state

    # Check chronological ordering
    for i in range(len(traces) - 1):
        if traces[i + 1].started_at < traces[i].ended_at:
            raise ValueError(
                f"trace chunk {i + 2} started_at ({traces[i + 1].started_at}) "
                f"is before chunk {i + 1} ended_at ({traces[i].ended_at})"
            )

    activity_executions = [act for t in traces for act in t.activity_executions]
    action_executions = [act for t in traces for act in t.action_executions]
    movements = [mov for t in traces for mov in t.movements]
    state_transitions = [tr for t in traces for tr in t.state_transitions]
    resource_events = [res for t in traces for res in t.resource_events]
    runtime_events = [ev for t in traces for ev in t.runtime_events]
    plan_deviations = [dev for t in traces for dev in t.plan_deviations]

    # Validate global ID uniqueness across aggregated items
    act_ids = [a.activity_execution_id for a in activity_executions]
    if len(act_ids) != len(set(act_ids)):
        raise ValueError("duplicate activityExecutionId found across trace chunks")

    action_ids = [a.action_execution_id for a in action_executions]
    if len(action_ids) != len(set(action_ids)):
        raise ValueError("duplicate actionExecutionId found across trace chunks")

    mov_ids = [m.movement_id for m in movements]
    if len(mov_ids) != len(set(mov_ids)):
        raise ValueError("duplicate movementId found across trace chunks")

    tr_ids = [t.transition_id for t in state_transitions]
    if len(tr_ids) != len(set(tr_ids)):
        raise ValueError("duplicate transitionId found across trace chunks")

    # Combine daily summaries by date
    daily_by_date: dict[Any, DailyExecutionSummary] = {}
    for t in traces:
        for ds in t.daily_summaries:
            if ds.date in daily_by_date:
                existing = daily_by_date[ds.date]
                daily_by_date[ds.date] = DailyExecutionSummary(
                    date=ds.date,
                    completed_activity_count=existing.completed_activity_count + ds.completed_activity_count,
                    deviated_activity_count=existing.deviated_activity_count + ds.deviated_activity_count,
                    failed_activity_count=existing.failed_activity_count + ds.failed_activity_count,
                    dropped_activity_count=existing.dropped_activity_count + ds.dropped_activity_count,
                )
            else:
                daily_by_date[ds.date] = ds
    daily_summaries = [daily_by_date[d] for d in sorted(daily_by_date)]

    # Compute trace ID and semantic digest
    raw_trace = ExecutionTrace(
        trace_id=f"trace_{run_id}",
        source_bundle_id=source_bundle_id,
        source_bundle_sha256=source_bundle_sha256,
        seed=seed,
        started_at=started_at,
        ended_at=ended_at,
        activity_executions=activity_executions,
        action_executions=action_executions,
        movements=movements,
        state_transitions=state_transitions,
        resource_events=resource_events,
        runtime_events=runtime_events,
        plan_deviations=plan_deviations,
        daily_summaries=daily_summaries,
        final_state=final_state,
        semantic_digest="0" * 64,
    )
    payload = raw_trace.model_dump(mode="json", by_alias=True)
    semantic_digest = _trace_semantic_digest(payload)
    trace_id = f"trace_{semantic_digest[:16]}"

    return raw_trace.model_copy(
        update={
            "trace_id": trace_id,
            "semantic_digest": semantic_digest,
        }
    )


def aggregate_sensor_logs(
    logs: Sequence[ObservableSensorLog],
) -> ObservableSensorLog:
    if not logs:
        raise ValueError("sensor logs sequence must not be empty")

    first_log = logs[0]
    for i, log in enumerate(logs):
        if log.sensor_model_id != first_log.sensor_model_id:
            raise ValueError(
                f"sensor log chunk {i + 1} has mismatched sensorModelId ({log.sensor_model_id} vs {first_log.sensor_model_id})"
            )

    all_records: list[ObservableSensorRecord] = [rec for log in logs for rec in log.records]
    all_records.sort(key=lambda item: (item.observed_at, item.sensor_id, item.observation_id))

    record_ids = [r.observation_id for r in all_records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("duplicate observationId found across sensor log chunks")

    started_at = logs[0].started_at
    ended_at = max([logs[-1].ended_at, *(r.observed_at for r in all_records)])

    semantic = {
        "sensorModelId": first_log.sensor_model_id,
        "sensorModelVersion": first_log.sensor_model_version,
        "records": [item.model_dump(mode="json", by_alias=True) for item in all_records],
    }
    semantic_digest = _canonical_json_digest(semantic)
    log_id = f"sensor_log_{semantic_digest[:16]}"

    return ObservableSensorLog(
        log_id=log_id,
        sensor_model_id=first_log.sensor_model_id,
        sensor_model_version=first_log.sensor_model_version,
        started_at=started_at,
        ended_at=ended_at,
        records=all_records,
        semantic_digest=semantic_digest,
    )


def aggregate_oracle_mappings(
    trace: ExecutionTrace,
    log: ObservableSensorLog,
    mappings: Sequence[OracleMapping],
) -> OracleMapping:
    if not mappings:
        raise ValueError("oracle mappings sequence must not be empty")

    all_links: list[OracleObservationLink] = [link for m in mappings for link in m.links]
    link_by_id = {item.observation_id: item for item in all_links}

    # Match order of records in aggregated log
    ordered_links = [
        link_by_id[r.observation_id] for r in log.records if r.observation_id in link_by_id
    ]

    oracle_digest = _canonical_json_digest([item.model_dump(mode="json") for item in ordered_links])
    mapping_id = f"oracle_{oracle_digest[:16]}"

    return OracleMapping(
        mapping_id=mapping_id,
        observable_log_id=log.log_id,
        source_trace_id=trace.trace_id,
        source_trace_semantic_digest=trace.semantic_digest,
        links=ordered_links,
    )
