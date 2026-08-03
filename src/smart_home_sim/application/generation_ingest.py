"""Publish a completed generation as the INPUT of a workspace home.

Generation is an *authoring* step: it invents a persona, its recurring activities and a horizon of
days. This
module turns that output into exactly the same kind of workspace input a researcher imports by hand
(scenario + personal process package + residents + an executable home and sensor field), so from
that point on the home behaves like any other: run the simulation, replay it, export the dataset.

The one deliberate difference from ``import_authoring_bundle`` is the compilation gate. A horizon of
30-365 days cannot be compiled as a single scenario (CP-SAT does not scale past a handful of days),
so generation compiles and bundles **each day separately** and records the per-day result in the
``horizon`` revision. That is a stronger guarantee than one monolithic compile, not a weaker one:
every published day already produced a valid canonical plan and simulation bundle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smart_home_sim.application.generation_paths import generation_run_dir
from smart_home_sim.application.horizon_run import deploy_horizon_sensors
from smart_home_sim.application.service import ApplicationService
from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.batch import SimulationBatchManifest
from smart_home_sim.domain.models import Scenario, SimulationWindow

HORIZON_REVISION_KIND = "horizon"
BATCH_MANIFEST_ROLE = "simulation_batch_manifest"


class GenerationIngestError(RuntimeError):
    """The generated artifacts could not be published as a home input."""


@dataclass(frozen=True)
class GenerationIngestResult:
    home_id: str
    resident_display_name: str
    day_count: int


def horizon_revision(workspace: WorkspaceService, home_id: str) -> dict[str, Any] | None:
    """The provenance of the home's horizon input, or None for an ordinary authored home."""
    revision = workspace.latest_revision(home_id, HORIZON_REVISION_KIND)
    return None if revision is None else revision["provenance"]


def generation_job_for_home(workspace: WorkspaceService, home_id: str) -> str | None:
    """The generation a home was created from, or None when it was authored by hand."""
    provenance = horizon_revision(workspace, home_id)
    if provenance is None:
        return None
    generation_job_id = provenance.get("generationJobId")
    return str(generation_job_id) if generation_job_id else None


def horizon_home(workspace: WorkspaceService, generation_job_id: str) -> str | None:
    """The home a generation published, if any."""
    job = workspace.get_job(generation_job_id)
    if job.home_id and horizon_revision(workspace, job.home_id) is not None:
        return job.home_id
    return None


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise GenerationIngestError(f"generated artifact is unreadable: {path.name}") from error


def _persona_label(directory: Path) -> tuple[str, str]:
    persona = json.loads(_read(directory / "persona.json"))
    name = str(persona.get("name") or "Generated resident")
    city = str(persona.get("city") or "")
    age = persona.get("age")
    detail = ", ".join(part for part in (f"{age}" if age else "", city) if part)
    return name, detail


def _horizon_scenario_json(directory: Path, manifest: SimulationBatchManifest) -> bytes:
    """The horizon scenario, rebuilt from the per-day scenarios when it predates that artifact.

    Generations produced before the home workflow wrote only per-day scenarios. Their days are
    still on disk, so the same document can be reconstructed exactly and published as an input
    rather than forcing the researcher to pay for the generation again.
    """
    path = directory / "horizon-scenario.json"
    if path.is_file():
        return _read(path)
    days = []
    first: Scenario | None = None
    last: Scenario | None = None
    for run in manifest.runs:
        scenario = Scenario.model_validate_json(
            _read(directory / "scenarios" / f"{run.run_id}.scenario.json")
        )
        days.extend(scenario.days)
        first = first or scenario
        last = scenario
    if first is None or last is None:
        raise GenerationIngestError("the generation recorded no simulatable day")
    window = SimulationWindow(start=first.simulation_window.start, end=last.simulation_window.end)
    merged = first.model_copy(
        update={
            "simulation_window": window,
            "days": days,
            "initial_state": first.initial_state.model_copy(update={"at": window.start}),
        }
    )
    return (merged.model_dump_json(by_alias=True, indent=2) + "\n").encode("utf-8")


def ingest_generation(
    workspace: WorkspaceService, generation_job_id: str
) -> GenerationIngestResult:
    """Create the home whose inputs are the artifacts of one completed generation job."""
    directory = generation_run_dir(workspace, generation_job_id)
    if not directory.is_dir():
        raise GenerationIngestError("the generation produced no artifact directory")
    if horizon_home(workspace, generation_job_id) is not None:
        raise GenerationIngestError("this generation has already published a home")

    manifest_json = _read(directory / "batch-manifest.json")
    manifest = SimulationBatchManifest.model_validate_json(manifest_json)
    scenario_json = _horizon_scenario_json(directory, manifest)
    behavior_json = _read(directory / "personal-process-package.json")
    home_json = _read(directory / "home.json")
    scenario = Scenario.model_validate_json(scenario_json)
    name, detail = _persona_label(directory)

    home = workspace.create_home(
        f"{name} · {len(manifest.runs)} generated days",
        f"Locally generated horizon{f' ({detail})' if detail else ''} "
        f"from {scenario.simulation_window.start.date()} "
        f"to {scenario.simulation_window.end.date()}",
    )
    application = ApplicationService(workspace)

    scenario_artifact = workspace.put_object(
        scenario_json, role="scenario", schema_version="1.0.0", home_id=home.home_id
    )
    behavior_artifact = workspace.put_object(
        behavior_json,
        role="personal_process_package",
        schema_version="1.0.0",
        home_id=home.home_id,
    )
    manifest_artifact = workspace.put_object(
        manifest_json, role=BATCH_MANIFEST_ROLE, schema_version="1.0.0", home_id=home.home_id
    )

    provenance = {
        "generationJobId": generation_job_id,
        "dayCount": len(manifest.runs),
        "experimentId": manifest.experiment_id,
        "gate": "per-day compilation and bundling during generation",
    }
    workspace.create_revision(
        home.home_id,
        "scenario",
        scenario_artifact.artifact_id,
        status="valid",
        provenance=provenance,
    )
    workspace.create_revision(
        home.home_id,
        "behavior",
        behavior_artifact.artifact_id,
        status="valid",
        provenance=provenance,
    )
    workspace.create_revision(
        home.home_id,
        HORIZON_REVISION_KIND,
        manifest_artifact.artifact_id,
        status="valid",
        provenance=provenance,
    )

    home_result = application.publish_home(home.home_id, json.loads(home_json))
    if not home_result.get("valid"):
        raise GenerationIngestError("the generated home model did not pass validation")

    # The home's sensor field is the horizon's single installed field, not one day's deployment.
    field, _ = deploy_horizon_sensors(workspace, generation_job_id)
    sensor_result = application.publish_sensor(
        home.home_id, json.loads(field.model_dump_json(by_alias=True))
    )
    if not sensor_result.get("valid"):
        raise GenerationIngestError("the deployed sensor model did not pass validation")

    workspace.replace_authoring_residents(
        home.home_id,
        [
            (resident.resident_id, resident.display_name or resident.resident_id)
            for resident in scenario.residents
        ],
        scenario_artifact_id=scenario_artifact.artifact_id,
        behavior_artifact_id=behavior_artifact.artifact_id,
    )
    workspace.attach_job_home(generation_job_id, home.home_id)
    return GenerationIngestResult(
        home_id=home.home_id,
        resident_display_name=name,
        day_count=len(manifest.runs),
    )
