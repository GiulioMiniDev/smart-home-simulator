"""Where a generation job keeps its artifacts, and which of them the API may serve.

Kept in its own leaf module so the generation worker, the ingest step and the web layer can share it
without importing each other.
"""

from __future__ import annotations

from pathlib import Path

from smart_home_sim.application.workspace import WorkspaceService

# Files the pipeline writes into the job run directory; the API serves these for review.
GENERATION_ARTIFACTS: frozenset[str] = frozenset(
    {
        "persona.json",
        "behavioral-profile.json",
        "planning-world.json",
        "personal-process-package.json",
        "cadence-calendar.json",
        "batch-manifest.json",
        "planned-activity-trace.json",
        "horizon-scenario.json",
    }
)


def generation_run_dir(workspace: WorkspaceService, job_id: str) -> Path:
    """Where a generation job writes its artifacts.

    Deliberately NOT under ``runs/`` (which ``reconcile`` guards as catalogued run artifacts); a
    generation produces many uncatalogued files, so it uses its own ``generations/`` area that the
    integrity check ignores. The per-day bundles live here and stay the source the horizon run
    simulates from after the generation has been published as a home input.
    """
    return workspace.root / "generations" / job_id
