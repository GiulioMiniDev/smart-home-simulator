"""Build the disposable, real-artifact workspace used by replay browser tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = PROJECT_ROOT / "reports"
WORKSPACE_ROOT = REPORTS_ROOT / "e2e-workspace"
RUN_METADATA = REPORTS_ROOT / "e2e-replay-run.json"
SOURCE = PROJECT_ROOT / "examples" / "materialization" / "mario_rossi_2026_10_30"


def _fixture_workspace() -> Path:
    """Resolve the one fixture directory that this builder is permitted to replace."""
    reports = REPORTS_ROOT.resolve()
    workspace = WORKSPACE_ROOT.resolve()
    try:
        workspace.relative_to(reports)
    except ValueError as error:
        raise RuntimeError(
            "the E2E workspace must stay under the repository reports directory"
        ) from error
    if workspace == reports:
        raise RuntimeError("refusing to use the reports directory itself as an E2E workspace")
    return workspace


def build() -> str:
    workspace_root = _fixture_workspace()
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)

    workspace = WorkspaceService.create(workspace_root, "Replay E2E")
    home = workspace.create_home("Mario")
    job = workspace.create_job("simulation", home_id=home.home_id, seed=123)
    workspace.update_job(
        job.job_id,
        JobStatus.running,
        JobProgress(phase="execution", percent=50, message="Executing"),
    )
    destination = workspace.runs_path / job.job_id
    shutil.copytree(SOURCE, destination)
    workspace.import_run_directory(job.job_id, destination)
    workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Done"),
        result_reference=job.job_id,
    )
    RUN_METADATA.write_text(
        json.dumps({"runId": job.job_id}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return job.job_id


if __name__ == "__main__":
    print(build())
