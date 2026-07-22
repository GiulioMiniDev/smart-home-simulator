from __future__ import annotations

import multiprocessing
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobRecord, JobStatus
from smart_home_sim.domain.materialization import HomeGenerationPolicy, SensorDeploymentPolicy
from smart_home_sim.domain.models import Scenario
from smart_home_sim.materialization import materialize_workspace
from smart_home_sim.materialization.service import MaterializationFailure


def _sensor_policy_from_request(payload: dict[str, Any] | None) -> SensorDeploymentPolicy:
    """Apply partial UI overrides to the research default, not the legacy model default."""
    if not payload:
        return SensorDeploymentPolicy.realistic()
    version = payload.get("policyVersion", payload.get("policy_version"))
    profile = payload.get("observationProfile", payload.get("observation_profile"))
    if version == "1.1.0" or profile == "ideal":
        return SensorDeploymentPolicy.model_validate(payload)
    base = (
        SensorDeploymentPolicy.adverse()
        if profile == "adverse"
        else SensorDeploymentPolicy.realistic()
    )
    return SensorDeploymentPolicy.model_validate(
        {**base.model_dump(by_alias=True), **payload}
    )


def _materialization_worker(root: str, job_id: str) -> None:
    workspace = WorkspaceService.open(Path(root), reconcile=False, recover_jobs=False)
    request = workspace.job_request(job_id)

    def progress(phase: str, percent: float, message: str, counters: dict[str, int]) -> None:
        current = workspace.get_job(job_id)
        if current.status is JobStatus.cancelled:
            raise InterruptedError("job was cancelled")
        total = sum(counters.values()) or None
        workspace.update_job(
            job_id,
            JobStatus.running,
            JobProgress(
                phase=phase,
                percent=percent,
                completed_units=sum(counters.values()),
                total_units=total,
                message=message,
            ),
            process_id=os.getpid(),
        )

    try:
        workspace.update_job(
            job_id,
            JobStatus.running,
            JobProgress(phase="starting", percent=1, message="Started a local worker"),
            process_id=os.getpid(),
        )
        scenario = workspace.artifact_path(request["scenarioArtifactId"])
        behavior = workspace.artifact_path(request["behaviorArtifactId"])
        output = workspace.runs_path / job_id
        home_policy = HomeGenerationPolicy.model_validate(request.get("homePolicy") or {})
        sensor_policy = _sensor_policy_from_request(request.get("sensorPolicy"))
        materialize_workspace(
            scenario,
            behavior,
            output,
            home_policy=home_policy,
            sensor_policy=sensor_policy,
            progress=progress,
            cancelled=lambda: workspace.get_job(job_id).status is JobStatus.cancelled,
        )
        descriptors = workspace.import_run_directory(job_id, output)
        by_role = {item.role: item for item in descriptors}
        if "home_model" in by_role:
            workspace.create_revision(
                workspace.get_job(job_id).home_id or "",
                "home",
                by_role["home_model"].artifact_id,
                status="valid",
                provenance={"jobId": job_id, "source": "scenario-first-1.0.0"},
            )
        if "sensor_model" in by_role:
            workspace.create_revision(
                workspace.get_job(job_id).home_id or "",
                "sensor",
                by_role["sensor_model"].artifact_id,
                status="valid",
                provenance={"jobId": job_id, "source": "scenario-first-1.0.0"},
            )
        workspace.update_job(
            job_id,
            JobStatus.completed,
            JobProgress(
                phase="completed",
                percent=100,
                message="Simulation and sensor projection completed",
            ),
            process_id=os.getpid(),
            result_reference=job_id,
        )
    except InterruptedError:
        if workspace.get_job(job_id).status is not JobStatus.cancelled:
            workspace.update_job(
                job_id,
                JobStatus.cancelled,
                JobProgress(
                    phase="cancelled",
                    percent=workspace.get_job(job_id).progress.percent,
                    message="Cancelled before publication",
                ),
            )
    except MaterializationFailure as error:
        current = workspace.get_job(job_id)
        if current.status is not JobStatus.cancelled:
            for issue in error.issues:
                payload = {"phase": error.phase, **issue}
                workspace.append_event(
                    job_id,
                    "issue",
                    str(issue.get("message") or error.message),
                    level="error",
                    payload=payload,
                )
            workspace.update_job(
                job_id,
                JobStatus.failed,
                JobProgress(
                    phase=error.phase,
                    percent=current.progress.percent,
                    message=error.message,
                ),
                process_id=os.getpid(),
                error_code=error.code,
                error_message=error.message,
            )
    except Exception as error:
        current = workspace.get_job(job_id)
        if current.status is not JobStatus.cancelled:
            workspace.update_job(
                job_id,
                JobStatus.failed,
                JobProgress(
                    phase="failed",
                    percent=current.progress.percent,
                    message="The local worker failed",
                ),
                process_id=os.getpid(),
                error_code=type(error).__name__.upper(),
                error_message=str(error),
            )


class JobManager:
    def __init__(self, workspace: WorkspaceService, *, max_workers: int = 2) -> None:
        self.workspace = workspace
        self.max_workers = max(1, min(max_workers, 8))
        self._context = multiprocessing.get_context("spawn")
        self._processes: dict[str, multiprocessing.Process] = {}
        self._lock = threading.Lock()

    def start_materialization(
        self,
        home_id: str,
        scenario_artifact_id: str,
        behavior_artifact_id: str,
        *,
        seed: int | None = None,
        home_policy: dict[str, Any] | None = None,
        sensor_policy: dict[str, Any] | None = None,
    ) -> JobRecord:
        self.workspace.artifact_path(scenario_artifact_id)
        self.workspace.artifact_path(behavior_artifact_id)
        scenario = Scenario.model_validate_json(self.workspace.read_artifact(scenario_artifact_id))
        if seed is not None and seed != scenario.seed:
            raise WorkspaceError(
                "a run seed must match the published scenario; create a new scenario revision "
                "to change deterministic input"
            )
        seed = scenario.seed
        with self._lock:
            self._prune()
            running = sum(process.is_alive() for process in self._processes.values())
            if running >= self.max_workers:
                raise WorkspaceError("all local workers are busy")
            job = self.workspace.create_job(
                "materialization",
                home_id=home_id,
                seed=seed,
                request={
                    "scenarioArtifactId": scenario_artifact_id,
                    "behaviorArtifactId": behavior_artifact_id,
                    "homePolicy": home_policy or {},
                    "sensorPolicy": sensor_policy or {},
                },
            )
            process = self._context.Process(
                target=_materialization_worker,
                args=(str(self.workspace.root), job.job_id),
                name=f"smart-home-sim-{job.job_id}",
            )
            process.start()
            self._processes[job.job_id] = process
        return self.workspace.get_job(job.job_id)

    def cancel(self, job_id: str) -> JobRecord:
        job = self.workspace.get_job(job_id)
        if job.status in {
            JobStatus.completed,
            JobStatus.failed,
            JobStatus.cancelled,
            JobStatus.interrupted,
        }:
            return job
        cancelled = self.workspace.update_job(
            job_id,
            JobStatus.cancelled,
            JobProgress(
                phase="cancelled",
                percent=job.progress.percent,
                message="Cancelled safely; staged artifacts were discarded",
            ),
        )
        with self._lock:
            process = self._processes.pop(job_id, None)
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        output = self.workspace.runs_path / job_id
        if output.exists() and not self.workspace.run_artifacts(job_id):
            shutil.rmtree(output, ignore_errors=True)
        self.workspace.remove_staging_for(job_id)
        return cancelled

    def shutdown(self) -> None:
        with self._lock:
            identifiers = list(self._processes)
        for job_id in identifiers:
            process = self._processes.get(job_id)
            if process is not None and process.is_alive():
                self.cancel(job_id)
        self._prune()

    def _prune(self) -> None:
        for job_id, process in list(self._processes.items()):
            if not process.is_alive():
                process.join(timeout=0)
                self._processes.pop(job_id, None)
