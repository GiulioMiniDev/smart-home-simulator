from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import (
    DiaryAction,
    DiaryEntry,
    ObservationCause,
    ObservationView,
    ReplayVerification,
    utc_now,
)
from smart_home_sim.domain.execution import ExecutionTrace
from smart_home_sim.domain.sensors import ObservableSensorLog, OracleMapping
from smart_home_sim.simulation import replay_files


@lru_cache(maxsize=8)
def _trace(path: str, digest: str) -> ExecutionTrace:
    del digest
    return ExecutionTrace.model_validate_json(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _observations(path: str, digest: str) -> ObservableSensorLog:
    del digest
    return ObservableSensorLog.model_validate_json(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _oracle(path: str, digest: str) -> OracleMapping:
    del digest
    return OracleMapping.model_validate_json(Path(path).read_text(encoding="utf-8"))


class ReplayService:
    def __init__(self, workspace: WorkspaceService) -> None:
        self.workspace = workspace

    def _artifact(self, run_id: str, role: str) -> tuple[Path, str]:
        artifact = self.workspace.run_artifacts(run_id).get(role)
        if artifact is None:
            raise WorkspaceError(f"run '{run_id}' has no '{role}' artifact")
        return self.workspace.artifact_path(artifact.artifact_id), artifact.sha256

    def verify(self, run_id: str) -> ReplayVerification:
        bundle_path, _ = self._artifact(run_id, "simulation_bundle")
        trace_path, _ = self._artifact(run_id, "execution_trace")
        report = replay_files(bundle_path, trace_path)
        verification = ReplayVerification(
            run_id=run_id,
            verified_at=utc_now(),
            matches=report.matches,
            expected_semantic_digest=report.expected_semantic_digest,
            actual_semantic_digest=report.actual_semantic_digest,
        )
        if verification.matches and not self.workspace.diagnostic_mode:
            self.workspace.save_replay_session(
                run_id,
                verified_digest=verification.actual_semantic_digest,
            )
        return verification

    def diary(
        self,
        run_id: str,
        *,
        actor_id: str | None = None,
        status: str | None = None,
        query: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[DiaryEntry], int]:
        trace_path, trace_sha = self._artifact(run_id, "execution_trace")
        trace = _trace(str(trace_path), trace_sha)
        actions = {item.action_execution_id: item for item in trace.action_executions}
        movement_by_action: dict[str, list[str]] = {}
        for movement in trace.movements:
            movement_by_action.setdefault(movement.action_execution_id, []).append(
                movement.movement_id
            )
        entries: list[DiaryEntry] = []
        normalized_query = query.casefold().strip()
        for activity in trace.activity_executions:
            if actor_id and activity.actor_id != actor_id:
                continue
            if status and activity.status != status:
                continue
            if normalized_query and normalized_query not in (
                f"{activity.intent} {activity.actor_id} {activity.source_activity_id}".casefold()
            ):
                continue
            activity_actions = [actions[item] for item in activity.action_execution_ids]
            entries.append(
                DiaryEntry(
                    activity_execution_id=activity.activity_execution_id,
                    source_activity_id=activity.source_activity_id,
                    actor_id=activity.actor_id,
                    intent=activity.intent,
                    process_model_id=activity.process_model_id,
                    planned_start=activity.planned_start,
                    planned_end=activity.planned_end,
                    actual_start=activity.actual_start,
                    actual_end=activity.actual_end,
                    status=activity.status,
                    actions=[
                        DiaryAction(
                            action_execution_id=action.action_execution_id,
                            node_id=action.node_id,
                            action_type=action.action_type,
                            started_at=action.started_at,
                            ended_at=action.ended_at,
                            status=action.status,
                            provider_ids=action.provider_ids,
                        )
                        for action in activity_actions
                    ],
                    movement_ids=[
                        movement_id
                        for action in activity_actions
                        for movement_id in movement_by_action.get(action.action_execution_id, [])
                    ],
                    deviation_ids=activity.deviation_ids,
                    trace_id=trace.trace_id,
                    trace_semantic_digest=trace.semantic_digest,
                )
            )
        entries.sort(key=lambda item: (item.actual_start, item.activity_execution_id))
        total = len(entries)
        offset = max(offset, 0)
        limit = max(1, min(limit, 500))
        return entries[offset : offset + limit], total

    def observations(
        self,
        run_id: str,
        *,
        include_oracle: bool = False,
        sensor_id: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[ObservationView], int]:
        log_path, log_sha = self._artifact(run_id, "observable_sensor_log")
        log = _observations(str(log_path), log_sha)
        links = {}
        if include_oracle:
            oracle_path, oracle_sha = self._artifact(run_id, "oracle_mapping")
            mapping = _oracle(str(oracle_path), oracle_sha)
            links = {item.observation_id: item for item in mapping.links}
        records = [item for item in log.records if sensor_id is None or item.sensor_id == sensor_id]
        total = len(records)
        offset = max(offset, 0)
        limit = max(1, min(limit, 1000))
        result = []
        for record in records[offset : offset + limit]:
            link = links.get(record.observation_id)
            cause = None
            if link is not None:
                cause = ObservationCause(
                    origin=link.origin,
                    cause_type=link.cause_type,
                    cause_ids=link.cause_ids,
                    resident_ids=link.resident_ids,
                    activity_execution_ids=link.activity_execution_ids,
                    action_execution_ids=link.action_execution_ids,
                )
            result.append(
                ObservationView(
                    observation_id=record.observation_id,
                    sensor_id=record.sensor_id,
                    sensor_type=record.sensor_type,
                    observed_at=record.observed_at,
                    measurement=record.measurement,
                    value=record.value,
                    unit=record.unit,
                    quality=record.quality,
                    oracle_cause=cause,
                )
            )
        return result, total

    def timeline(
        self,
        run_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        trace_path, trace_sha = self._artifact(run_id, "execution_trace")
        trace = _trace(str(trace_path), trace_sha)
        events: list[dict[str, Any]] = []

        def accepted(at: datetime) -> bool:
            return (start is None or at >= start) and (end is None or at <= end)

        for activity in trace.activity_executions:
            if accepted(activity.actual_start):
                events.append(
                    {
                        "at": activity.actual_start.isoformat(),
                        "kind": "activity",
                        "id": activity.activity_execution_id,
                        "actorId": activity.actor_id,
                        "label": activity.intent,
                        "status": activity.status,
                        "end": activity.actual_end.isoformat(),
                    }
                )
        for action in trace.action_executions:
            if accepted(action.started_at):
                events.append(
                    {
                        "at": action.started_at.isoformat(),
                        "kind": "action",
                        "id": action.action_execution_id,
                        "actorId": action.actor_id,
                        "label": action.action_type,
                        "status": action.status,
                        "end": action.ended_at.isoformat(),
                    }
                )
        for movement in trace.movements:
            if accepted(movement.started_at):
                events.append(
                    {
                        "at": movement.started_at.isoformat(),
                        "kind": "movement",
                        "id": movement.movement_id,
                        "actorId": movement.actor_id,
                        "label": f"{movement.origin_region_id} → {movement.destination_region_id}",
                        "status": "completed",
                        "end": movement.ended_at.isoformat(),
                        "waypoints": [
                            item.model_dump(mode="json", by_alias=True)
                            for item in movement.waypoints
                        ],
                    }
                )
        events.sort(key=lambda item: (item["at"], item["kind"], item["id"]))
        return events[: max(1, min(limit, 10_000))]
