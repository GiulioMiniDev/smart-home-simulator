"""Local worker that runs the hybrid generation pipeline as a workspace job.

The job lifecycle (progress, cancellation, failure) lives in ``run_generation_job``, which runs
in-process and accepts an injectable LM Studio client so it is fully testable without a live model.
``_generation_worker`` is the thin subprocess entry point spawned by the JobManager. Generation
never simulates; it writes every artifact (batch manifest and planned ground truth included) under
the job's run directory for the researcher to review before running ``simulate-batch`` separately.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobStatus
from smart_home_sim.hybrid_planning.lmstudio import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LMStudioClient,
    LMStudioConfig,
)
from smart_home_sim.hybrid_planning.pipeline import run_generation

# Files the pipeline writes into the job run directory; the API serves these for review.
GENERATION_ARTIFACTS: frozenset[str] = frozenset(
    {
        "persona.json",
        "behavioral-profile.json",
        "planning-world.json",
        "personal-process-package.json",
        "cadence-calendar.json",
        "batch-manifest.json",
        "planned-habit-trace.json",
    }
)


def generation_run_dir(workspace: WorkspaceService, job_id: str) -> Path:
    """Where a generation job writes its artifacts.

    Deliberately NOT under ``runs/`` (which ``reconcile`` guards as catalogued run artifacts); a
    generation produces many uncatalogued files, so it uses its own ``generations/`` area that the
    integrity check ignores. The batch manifest and its bundles live here for ``simulate-batch``.
    """
    return workspace.root / "generations" / job_id


def _client_from_request(request: dict) -> LMStudioClient:
    return LMStudioClient(
        LMStudioConfig(
            base_url=request.get("baseUrl") or DEFAULT_BASE_URL,
            model=request.get("model") or DEFAULT_MODEL,
            temperature=request.get("temperature", 0.6),
            seed=request.get("seed"),
        )
    )


def _fail(workspace: WorkspaceService, job_id: str, code: str, message: str) -> None:
    current = workspace.get_job(job_id)
    if current.status is JobStatus.cancelled:
        return
    workspace.update_job(
        job_id,
        JobStatus.failed,
        JobProgress(phase="failed", percent=current.progress.percent, message=message),
        process_id=os.getpid(),
        error_code=code,
        error_message=message,
    )


def run_generation_job(
    workspace: WorkspaceService, job_id: str, *, client: LMStudioClient | None = None
) -> None:
    """Run the generation pipeline for one job, updating its status/progress in the workspace."""
    request = workspace.job_request(job_id)
    output = generation_run_dir(workspace, job_id)

    def progress(stage: str, percent: float, message: str) -> None:
        if workspace.get_job(job_id).status is JobStatus.cancelled:
            raise InterruptedError("job was cancelled")
        workspace.update_job(
            job_id,
            JobStatus.running,
            JobProgress(phase=stage, percent=percent, message=message),
            process_id=os.getpid(),
        )

    try:
        workspace.update_job(
            job_id,
            JobStatus.running,
            JobProgress(phase="starting", percent=1, message="Started a local worker"),
            process_id=os.getpid(),
        )
        result = run_generation(
            request["brief"],
            output,
            client or _client_from_request(request),
            start_date=date.fromisoformat(request["startDate"]),
            months=request.get("months", 1),
            use_llm_package=request.get("useLlmPackage", False),
            use_llm_days=request.get("useLlmDays", False),
            seed=request.get("seed"),
            days=request.get("days"),
            progress=progress,
        )
        workspace.update_job(
            job_id,
            JobStatus.completed,
            JobProgress(
                phase="completed",
                percent=100,
                message=f"Generated {result.day_count} simulatable days",
            ),
            process_id=os.getpid(),
            result_reference=job_id,
        )
    except InterruptedError:
        current = workspace.get_job(job_id)
        if current.status is not JobStatus.cancelled:
            workspace.update_job(
                job_id,
                JobStatus.cancelled,
                JobProgress(
                    phase="cancelled", percent=current.progress.percent, message="Cancelled"
                ),
            )
    except Exception as error:  # noqa: BLE001 - any pipeline failure becomes a failed job
        _fail(workspace, job_id, type(error).__name__.upper(), str(error))


def _generation_worker(root: str, job_id: str) -> None:
    workspace = WorkspaceService.open(Path(root), reconcile=False, recover_jobs=False)
    run_generation_job(workspace, job_id)
