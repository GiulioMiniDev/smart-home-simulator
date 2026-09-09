from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from smart_home_sim.application.jobs import (
    JobManager,
    _materialization_worker,
    _sensor_policy_from_request,
)
from smart_home_sim.application.plan_approval import (
    DECISION_KEY,
    plan_approval,
    reusable_compilation,
)
from smart_home_sim.application.service import ApplicationService
from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.compiler import compile_scenario
from smart_home_sim.compiler.fingerprint import compiler_fingerprint
from smart_home_sim.domain.application import JobProgress, JobStatus
from smart_home_sim.domain.materialization import SensorDeploymentPolicy
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.environment import service as environment_service
from smart_home_sim.materialization.service import MaterializationFailure

PROJECT_ROOT = Path(__file__).parents[1]


def test_partial_sensor_policy_uses_realistic_research_defaults() -> None:
    assert _sensor_policy_from_request(None) == SensorDeploymentPolicy.realistic()
    assert _sensor_policy_from_request({"preset": "minimal"}) == SensorDeploymentPolicy.realistic(
        preset="minimal"
    )
    assert _sensor_policy_from_request(
        {"policyVersion": "1.1.0", "preset": "minimal"}
    ) == SensorDeploymentPolicy(preset="minimal")


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
        policy = json.loads(
            workspace.read_artifact(artifacts["sensor_deployment_policy"].artifact_id)
        )
        assert policy["policyVersion"] == "1.2.0"
        assert policy["observationProfile"] == "realistic"
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


def _imported_home(workspace: WorkspaceService) -> tuple[str, dict[str, str]]:
    """A home with a bundle imported: the state every UI flow starts from.

    Importing validates, and validating compiles — so a plan for this scenario exists from here on,
    before any job has run.
    """
    home = workspace.create_home("Minimal")
    payload = json.loads(
        (PROJECT_ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text(
            encoding="utf-8"
        )
    )
    imported = ApplicationService(workspace).import_authoring(
        home.home_id, payload["scenario"], payload["personalProcessPackage"]
    )
    request = {
        "scenarioArtifactId": imported["scenarioArtifact"]["artifactId"],
        "behaviorArtifactId": imported["behaviorArtifact"]["artifactId"],
        "homePolicy": {},
        "sensorPolicy": {"preset": "minimal"},
    }
    return home.home_id, request


def _worker_job(
    workspace: WorkspaceService, home_id: str, request: dict[str, str], kind: str, **extra: Any
) -> tuple[str, list[str]]:
    """Run one job in this process, counting the horizons it solves for itself."""
    job = workspace.create_job(kind, home_id=home_id, request={**request, **extra})
    solved: list[str] = []
    real = compile_scenario

    def counted(scenario: Any, on_progress: Any = None) -> Any:
        solved.append(scenario.scenario_id)
        return real(scenario, on_progress)

    with (
        mock.patch("smart_home_sim.materialization.service.compile_scenario", counted),
        mock.patch("smart_home_sim.environment.service.compile_scenario", counted),
    ):
        environment_service._compiled_plan_digest.cache_clear()
        _materialization_worker(str(workspace.root), job.job_id)
    record = workspace.get_job(job.job_id)
    assert record.status is JobStatus.completed, record.error_message
    return job.job_id, solved


def _plan_reason(workspace: WorkspaceService, job_id: str) -> str:
    return next(
        event.message
        for event in workspace.list_events(job_id)
        if event.payload.get("decision") == DECISION_KEY
    )


def test_the_whole_ui_flow_solves_the_horizon_exactly_once(tmp_path: Path) -> None:
    """Import, preview, run — three steps that used to be three solves of one document.

    Each of them needs the same canonical plan and each used to derive it again: the import to
    check the scenario's deterministic preconditions, the preview to build the planimetry a
    researcher approves, the run to execute. On a five-month horizon that is roughly twenty
    minutes of CP-SAT spent producing one plan. The import is the only step that has to compile,
    because it is the first; what the other two need is to recognise what it left behind.
    """
    workspace = WorkspaceService.create(tmp_path / "workspace", "Whole flow")
    home_id, request = _imported_home(workspace)

    preview_id, preview_solves = _worker_job(
        workspace, home_id, request, "environment", stopAfter="environment"
    )
    run_id, run_solves = _worker_job(workspace, home_id, request, "materialization")

    assert preview_solves == []
    assert run_solves == []
    assert _plan_reason(workspace, preview_id) == (
        "reused the canonical plan compiled by the authoring import"
    )
    assert _plan_reason(workspace, run_id) == (
        "reused the canonical plan compiled by the authoring import"
    )
    # And it is the same plan throughout, which is the only reason skipping the solves is allowed.
    previewed = workspace.run_artifacts(preview_id)
    executed = workspace.run_artifacts(run_id)
    imported_plan = workspace.read_artifact(
        str(workspace.latest_revision(home_id, "plan")["artifactId"])
    )
    assert CanonicalPlan.model_validate_json(imported_plan) == CanonicalPlan.model_validate_json(
        workspace.read_artifact(executed["canonical_plan"].artifact_id)
    )
    # The dataset itself says nothing about which of the two happened, and must not: comparing
    # artifact digests across a change is how this pipeline is verified, and an output that
    # remembers whether an optimisation fired cannot serve as that control.
    assert workspace.read_artifact(
        executed["plan_approval"].artifact_id
    ) == workspace.read_artifact(previewed["plan_approval"].artifact_id)


def test_a_job_solves_again_when_the_compiler_is_not_the_one_that_published(
    tmp_path: Path,
) -> None:
    """A plan is a function of the scenario *and* of the code that compiled it.

    Nothing in a canonical plan says which code that was: `CompilerMetadata` is all frozen literals
    and `__version__` has never moved, so a plan from before the time-axis rescale is indis-
    tinguishable from one produced now. Left unchecked, editing the solver and then running a home
    imported yesterday would execute yesterday's plan on today's engine and publish a dataset that
    passes every gate while answering a question nobody asked.
    """
    workspace = WorkspaceService.create(tmp_path / "workspace", "Changed compiler")
    home_id, request = _imported_home(workspace)

    with mock.patch(
        "smart_home_sim.application.plan_approval.compiler_fingerprint",
        lambda: "0" * 64,
    ):
        run_id, solved = _worker_job(workspace, home_id, request, "materialization")

    assert len(solved) == 1
    assert _plan_reason(workspace, run_id) == (
        "compiled the horizon: no earlier plan matches this scenario and compiler"
    )
    # Refusing costs the solve and nothing else: this compiler agrees with the one that imported.
    executed = workspace.run_artifacts(run_id)
    imported_plan = workspace.read_artifact(
        str(workspace.latest_revision(home_id, "plan")["artifactId"])
    )
    assert CanonicalPlan.model_validate_json(imported_plan) == CanonicalPlan.model_validate_json(
        workspace.read_artifact(executed["canonical_plan"].artifact_id)
    )


def test_a_run_reuses_a_job_plan_when_the_import_left_none(tmp_path: Path) -> None:
    """Homes imported before plans were published still get the saving from the preview."""
    workspace = WorkspaceService.create(tmp_path / "workspace", "No import plan")
    home_id, request = _imported_home(workspace)
    # The state of a workspace whose import predates this: artifacts and revisions, but no plan.
    with workspace.transaction() as connection:
        connection.execute("DELETE FROM revisions WHERE home_id=? AND kind='plan'", (home_id,))

    preview_id, preview_solves = _worker_job(
        workspace, home_id, request, "environment", stopAfter="environment"
    )
    run_id, run_solves = _worker_job(workspace, home_id, request, "materialization")

    assert len(preview_solves) == 1
    assert _plan_reason(workspace, preview_id) == (
        "compiled the horizon: nothing earlier published a plan to reuse"
    )
    assert run_solves == []
    assert _plan_reason(workspace, run_id) == (
        f"reused the canonical plan compiled by {preview_id}"
    )


def test_a_plan_that_no_longer_matches_its_scenario_is_not_reused(tmp_path: Path) -> None:
    """The match is on the scenario's digest, so an edited scenario cannot inherit an old plan."""
    workspace = WorkspaceService.create(tmp_path / "workspace", "Edited scenario")
    home_id, request = _imported_home(workspace)
    scenario = Scenario.model_validate_json(workspace.read_artifact(request["scenarioArtifactId"]))
    edited = scenario.model_copy(update={"title": "a different document"})

    reuse = reusable_compilation(workspace, home_id, edited)

    assert reuse.compilation is None
    assert reuse.reason == (
        "compiled the horizon: no earlier plan matches this scenario and compiler"
    )


def test_a_plan_that_stopped_agreeing_with_its_report_is_not_reused(tmp_path: Path) -> None:
    """The two halves of one solve have to still describe each other.

    Both come out of the same compilation, so a report whose recorded plan digest is not the plan
    beside it means one of the two is not what that step produced. Downstream the materializer
    refuses such a pair outright; here it is simply not offered, because a caller that can compile
    has no reason to raise over a workspace it can route around.
    """
    workspace = WorkspaceService.create(tmp_path / "workspace", "Disagreeing pair")
    home_id, request = _imported_home(workspace)
    published = workspace.latest_revision(home_id, "plan")
    assert published is not None
    report = json.loads(
        workspace.read_artifact(published["provenance"]["compilationReportArtifactId"])
    )
    report["canonicalPlanSha256"] = "0" * 64
    doctored = workspace.put_object(
        json.dumps(report).encode("utf-8"), role="compilation_report", home_id=home_id
    )
    workspace.create_revision(
        home_id,
        "plan",
        published["artifactId"],
        status="valid",
        provenance={
            "compilationReportArtifactId": doctored.artifact_id,
            "compilerFingerprint": compiler_fingerprint(),
        },
    )

    scenario = Scenario.model_validate_json(workspace.read_artifact(request["scenarioArtifactId"]))
    reuse = reusable_compilation(workspace, home_id, scenario)

    assert reuse.compilation is None
    assert reuse.reason == (
        "compiled the horizon: no earlier plan matches this scenario and compiler"
    )


def test_an_unreadable_stored_plan_is_a_reason_to_compile_not_to_fail(tmp_path: Path) -> None:
    """Reuse is an optimisation, so every way of losing it ends in the solve that would have run."""
    workspace = WorkspaceService.create(tmp_path / "workspace", "Corrupt plan")
    home_id, request = _imported_home(workspace)
    published = workspace.latest_revision(home_id, "plan")
    assert published is not None
    workspace.artifact_path(str(published["artifactId"])).write_text(
        "{ this is not a canonical plan", encoding="utf-8"
    )

    scenario = Scenario.model_validate_json(workspace.read_artifact(request["scenarioArtifactId"]))
    reuse = reusable_compilation(workspace, home_id, scenario)

    assert reuse.compilation is None
    assert reuse.reason.startswith("compiled the horizon:")


def test_a_home_that_published_no_plan_at_all_says_so(tmp_path: Path) -> None:
    """A job that left no plan behind is nothing to reuse, not a fault."""
    workspace = WorkspaceService.create(tmp_path / "workspace", "No plan published")
    home_id, request = _imported_home(workspace)
    with workspace.transaction() as connection:
        connection.execute("DELETE FROM revisions WHERE home_id=? AND kind='plan'", (home_id,))
    # A completed job whose run published a scenario and nothing else.
    job = workspace.create_job("environment", home_id=home_id, request={})
    destination = workspace.runs_path / job.job_id
    destination.mkdir(parents=True)
    (destination / "scenario.json").write_bytes(
        workspace.read_artifact(request["scenarioArtifactId"])
    )
    workspace.import_run_directory(job.job_id, destination)
    workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Done"),
    )

    scenario = Scenario.model_validate_json(workspace.read_artifact(request["scenarioArtifactId"]))
    reuse = reusable_compilation(workspace, home_id, scenario)

    assert reuse.compilation is None
    assert reuse.reason == "compiled the horizon: nothing earlier published a plan to reuse"


def test_worker_persists_structured_gate_issues_before_marking_run_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Structured failure")
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
        request={
            "scenarioArtifactId": imported["scenarioArtifact"]["artifactId"],
            "behaviorArtifactId": imported["behaviorArtifact"]["artifactId"],
        },
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise MaterializationFailure(
            "simulation",
            "Simulation failed.",
            [
                {
                    "code": "PRECONDITION_FAILED",
                    "severity": "error",
                    "stage": "execution",
                    "path": "$.actionBindings[activity_7:action_02]",
                    "message": "Action 'leave_home' failed its precondition.",
                    "details": {
                        "activityId": "activity_7",
                        "actionType": "leave_home",
                        "expected": True,
                        "actual": False,
                    },
                }
            ],
        )

    monkeypatch.setattr("smart_home_sim.application.jobs.materialize_workspace", fail)

    _materialization_worker(str(workspace.root), job.job_id)

    failed = workspace.get_job(job.job_id)
    events = [event for event in workspace.list_events(job.job_id) if event.event_type == "issue"]
    assert failed.status is JobStatus.failed
    assert failed.progress.phase == "simulation"
    assert failed.error_code == "PRECONDITION_FAILED"
    assert failed.error_message == "Action 'leave_home' failed its precondition."
    assert len(events) == 1
    assert events[0].level == "error"
    assert events[0].payload["phase"] == "simulation"
    assert events[0].payload["path"] == "$.actionBindings[activity_7:action_02]"
    assert events[0].payload["details"] == {
        "activityId": "activity_7",
        "actionType": "leave_home",
        "expected": True,
        "actual": False,
    }


def test_the_environment_is_publishable_before_any_execution(tmp_path: Path) -> None:
    """A researcher can see and approve the plan without paying for the run first.

    Building the environment publishes the same home and sensor revisions a full run publishes, so
    what the plan editor then opens is exactly what a later run executes. The evidence a run would
    have produced is deliberately absent: this job executed nothing and must not look as if it did.
    """
    workspace = WorkspaceService.create(tmp_path / "workspace", "Environment first")
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
        "environment",
        home_id=home.home_id,
        seed=payload["scenario"]["seed"],
        request={
            "scenarioArtifactId": imported["scenarioArtifact"]["artifactId"],
            "behaviorArtifactId": imported["behaviorArtifact"]["artifactId"],
            "homePolicy": {},
            "sensorPolicy": {"preset": "minimal"},
            "stopAfter": "environment",
        },
    )
    _materialization_worker(str(workspace.root), job.job_id)

    completed = workspace.get_job(job.job_id)
    assert completed.status is JobStatus.completed
    assert "no simulation was executed" in completed.progress.message
    artifacts = workspace.run_artifacts(job.job_id)
    assert {"home_model", "sensor_model", "simulation_bundle"} <= set(artifacts)
    assert {"execution_trace", "observable_sensor_log", "oracle_mapping"} & set(artifacts) == set()
    published = workspace.get_home(home.home_id)
    assert published.current_home_artifact_id == artifacts["home_model"].artifact_id
    assert published.current_sensor_artifact_id == artifacts["sensor_model"].artifact_id
    # The plan is a recommendation until the researcher answers, exactly as after a full run.
    assert plan_approval(workspace, home.home_id)["approved"] is False
    phases = {
        event.payload.get("phase")
        for event in workspace.list_events(job.job_id)
        if event.event_type in {"progress", "status"}
    }
    assert {"compilation", "home", "binding", "sensors"} <= phases
    assert "simulation" not in phases
