from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from smart_home_sim.application.jobs import JobManager, _materialization_worker
from smart_home_sim.application.service import ApplicationService
from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import JobStatus

PROJECT_ROOT = Path(__file__).parents[1]


def test_process_isolated_materialization_reports_real_phases(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Workers")
    home = workspace.create_home("Minimal")
    payload = json.loads(
        (PROJECT_ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text(
            encoding="utf-8"
        )
    )
    imported = ApplicationService(workspace).import_authoring(
        home.home_id, payload["scenario"], payload["personalProcessPackage"]
    )
    manager = JobManager(workspace, max_workers=1)
    try:
        job = manager.start_materialization(
            home.home_id,
            imported["scenarioArtifact"]["artifactId"],
            imported["behaviorArtifact"]["artifactId"],
            seed=payload["scenario"]["seed"],
            sensor_policy={"preset": "minimal"},
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            job = workspace.get_job(job.job_id)
            if job.status in {
                JobStatus.completed,
                JobStatus.failed,
                JobStatus.cancelled,
                JobStatus.interrupted,
            }:
                break
            time.sleep(0.1)
        assert job.status is JobStatus.completed, job.error_message
        artifacts = workspace.run_artifacts(job.job_id)
        assert {
            "simulation_bundle",
            "execution_trace",
            "observable_sensor_log",
            "oracle_mapping",
        } <= set(artifacts)
        phases = {
            event.payload.get("phase")
            for event in workspace.list_events(job.job_id)
            if event.event_type in {"progress", "status"}
        }
        assert {"compilation", "home", "binding", "sensors", "simulation", "projection"} <= phases
        assert workspace.get_home(home.home_id).current_home_artifact_id
        assert workspace.get_home(home.home_id).current_sensor_artifact_id
    finally:
        manager.shutdown()


def test_job_manager_rejects_seed_changes_and_cancel_is_idempotent(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Cancellation")
    home = workspace.create_home("Minimal")
    payload = json.loads(
        (PROJECT_ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text(
            encoding="utf-8"
        )
    )
    imported = ApplicationService(workspace).import_authoring(
        home.home_id, payload["scenario"], payload["personalProcessPackage"]
    )
    manager = JobManager(workspace, max_workers=1)
    with pytest.raises(WorkspaceError, match="must match"):
        manager.start_materialization(
            home.home_id,
            imported["scenarioArtifact"]["artifactId"],
            imported["behaviorArtifact"]["artifactId"],
            seed=999,
        )
    queued = workspace.create_job("simulation", home_id=home.home_id)
    cancelled = manager.cancel(queued.job_id)
    assert cancelled.status is JobStatus.cancelled
    assert manager.cancel(queued.job_id) == cancelled


def test_worker_entry_point_is_covered_in_process_and_records_failures(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Direct worker")
    home = workspace.create_home("Minimal")
    payload = json.loads(
        (PROJECT_ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text(
            encoding="utf-8"
        )
    )
    imported = ApplicationService(workspace).import_authoring(
        home.home_id, payload["scenario"], payload["personalProcessPackage"]
    )
    job = workspace.create_job(
        "materialization",
        home_id=home.home_id,
        seed=payload["scenario"]["seed"],
        request={
            "scenarioArtifactId": imported["scenarioArtifact"]["artifactId"],
            "behaviorArtifactId": imported["behaviorArtifact"]["artifactId"],
            "homePolicy": {},
            "sensorPolicy": {"preset": "minimal"},
        },
    )
    _materialization_worker(str(workspace.root), job.job_id)
    assert workspace.get_job(job.job_id).status is JobStatus.completed

    failed = workspace.create_job(
        "materialization",
        home_id=home.home_id,
        request={"scenarioArtifactId": "missing", "behaviorArtifactId": "missing"},
    )
    _materialization_worker(str(workspace.root), failed.job_id)
    failed = workspace.get_job(failed.job_id)
    assert failed.status is JobStatus.failed
    assert failed.error_code == "WORKSPACEERROR"
