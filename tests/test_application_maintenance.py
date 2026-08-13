"""Integrity reconciliation and deletion: what happens when the folder and the catalogue differ.

A researcher works in the workspace folder as well as in the application — reclaiming disk by
deleting an export folder is the documented way to get the space back. Everything here is about
that: which divergences are ordinary housekeeping the application should absorb, which one is real
corruption that must still stop publication, and what deleting a home, a run or an export removes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobStatus


def _workspace_with_evidence(root: Path) -> tuple[WorkspaceService, str, str]:
    """A home with one completed run, its run artifacts and one published export."""
    workspace = WorkspaceService.create(root, "Deletable")
    home = workspace.create_home("Deletable home")
    scenario = workspace.put_object(b'{"scenario":true}', role="scenario", home_id=home.home_id)
    behavior = workspace.put_object(b'{"behavior":true}', role="behavior", home_id=home.home_id)
    workspace.add_resident(
        home.home_id,
        "resident",
        "Resident",
        scenario_artifact_id=scenario.artifact_id,
        behavior_artifact_id=behavior.artifact_id,
    )
    workspace.create_revision(home.home_id, "home", scenario.artifact_id, status="valid")
    job = workspace.create_job("simulation", home_id=home.home_id)
    run_directory = workspace.runs_path / job.job_id
    run_directory.mkdir(parents=True)
    (run_directory / "execution-trace.json").write_text('{"trace":1}', encoding="utf-8")
    workspace.import_run_directory(job.job_id, run_directory)
    workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Done"),
    )
    export_directory = workspace.exports_path / "export_fixture"
    export_directory.mkdir(parents=True)
    (export_directory / "observable.jsonl").write_text('{"o":1}\n', encoding="utf-8")
    workspace.register_artifact(
        export_directory / "observable.jsonl",
        role="export_observable_jsonl",
        run_id=job.job_id,
    )
    with workspace.transaction() as connection:
        connection.execute(
            "INSERT INTO exports(export_id, run_id, request_json, created_at) VALUES (?, ?, ?, ?)",
            ("export_fixture", job.job_id, "{}", "2026-07-22T10:00:00+00:00"),
        )
    return workspace, home.home_id, job.job_id


def test_a_folder_a_researcher_tidied_reopens_without_diagnostic_mode(tmp_path: Path) -> None:
    """Deleting exports in the file manager is housekeeping, not corruption.

    This is the case that used to lock the whole application: reclaiming disk by removing export
    folders left the catalogue describing files that were gone, every one of them counted as an
    integrity failure, and publication stayed paused with no way back inside the application.
    """
    root = tmp_path / "workspace"
    workspace, home_id, job_id = _workspace_with_evidence(root)
    shutil.rmtree(workspace.exports_path / "export_fixture")
    abandoned = workspace.exports_path / ".export_abandoned.tmp"
    abandoned.mkdir()
    (abandoned / "partial.csv").write_text("x", encoding="utf-8")

    reopened = WorkspaceService.open(root)
    assert reopened.diagnostic_mode is False
    assert reopened.last_repair is not None
    assert reopened.last_repair.artifacts_pruned == 1
    assert reopened.last_repair.exports_removed == 1
    assert reopened.last_repair.files_removed == 1  # the abandoned staging directory
    assert reopened.integrity().missing == []
    assert not abandoned.exists()
    # Publication works again, and the evidence still on disk was never touched.
    assert reopened.create_home("A home the researcher can still create").home_id
    assert set(reopened.run_artifacts(job_id)) == {"execution_trace"}
    assert reopened.get_home(home_id).name == "Deletable home"


def test_content_that_contradicts_the_catalogue_still_pauses_publication(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace, _, _ = _workspace_with_evidence(root)
    artifact = workspace.put_object(b"original", role="fixture", suffix=".bin")
    workspace.artifact_path(artifact.artifact_id).write_bytes(b"changed")

    reopened = WorkspaceService.open(root)
    assert reopened.diagnostic_mode is True
    report = reopened.integrity()
    assert [item.detail for item in report.corrupt] == ["size or digest mismatch"]
    assert report.missing == []
    with pytest.raises(WorkspaceError, match="diagnostic mode"):
        reopened.create_home("Blocked")
    # Repair reports the mismatch instead of hiding it by forgetting the row.
    assert reopened.repair().corrupt_remaining == 1
    assert reopened.diagnostic_mode is True


def test_uncatalogued_files_are_reported_and_only_removed_when_asked(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace, _, _ = _workspace_with_evidence(root)
    stray = workspace.exports_path / "stray.csv"
    stray.write_text("a,b\n", encoding="utf-8")

    assert [item.relative_path for item in workspace.integrity().orphans] == ["exports/stray.csv"]
    assert workspace.repair().files_removed == 0
    assert stray.is_file()
    summary = workspace.repair(remove_orphans=True)
    assert summary.files_removed == 1
    assert summary.bytes_freed == stray.stat().st_size if stray.exists() else summary.bytes_freed
    assert not stray.exists()
    assert workspace.integrity().orphans == []


def test_a_catalogue_row_pointing_outside_the_workspace_is_corruption(tmp_path: Path) -> None:
    """A path that escapes the root cannot be checked, so it can never be quietly forgotten."""
    root = tmp_path / "workspace"
    workspace, _, _ = _workspace_with_evidence(root)
    with workspace.transaction() as connection:
        connection.execute(
            "UPDATE artifacts SET relative_path='../escaped.json' WHERE role='scenario'"
        )

    report = workspace.integrity()
    assert [item.relative_path for item in report.corrupt] == ["../escaped.json"]
    assert "escapes the workspace" in report.corrupt[0].detail
    assert workspace.repair().corrupt_remaining == 1
    assert workspace.diagnostic_mode is True


def test_integrity_survives_a_content_directory_that_was_removed_whole(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace, _, _ = _workspace_with_evidence(root)
    shutil.rmtree(workspace.objects_path)

    report = workspace.integrity()
    assert report.corrupt == []
    assert {item.role for item in report.missing} == {"scenario", "behavior"}
    reopened = WorkspaceService.open(root)
    assert reopened.diagnostic_mode is False
    assert reopened.list_residents() != []  # the resident stays, without its stored inputs
    assert reopened.list_residents()[0].scenario_artifact_id is None


def test_deleting_a_home_removes_its_runs_exports_and_stored_inputs(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace, home_id, job_id = _workspace_with_evidence(root)
    stored = workspace.put_object(b'{"scenario":true}', role="scenario", home_id=home_id)
    assert stored.relative_path.startswith("objects/")

    summary = workspace.delete_home(home_id)
    assert summary.homes_removed == 1
    assert summary.runs_removed == 1
    assert summary.exports_removed == 1
    assert summary.bytes_freed > 0
    assert workspace.list_homes() == []
    assert workspace.list_residents() == []
    with pytest.raises(WorkspaceError, match="unknown home"):
        workspace.get_home(home_id)
    with pytest.raises(WorkspaceError, match="unknown job"):
        workspace.get_job(job_id)
    assert not (workspace.runs_path / job_id).exists()
    assert not (workspace.exports_path / "export_fixture").exists()
    assert not (workspace.root / stored.relative_path).exists()
    # The folder and the catalogue still agree, so nothing was left half-deleted.
    assert workspace.reconcile() == []
    assert workspace.summary().artifact_count == 0


def test_a_home_with_active_work_is_not_deletable(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace, home_id, _ = _workspace_with_evidence(root)
    workspace.create_job("materialization", home_id=home_id)
    with pytest.raises(WorkspaceError, match="active jobs"):
        workspace.delete_home(home_id)
    assert workspace.get_home(home_id).home_id == home_id


def test_deleting_a_run_keeps_the_home_and_refuses_while_it_executes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace, home_id, job_id = _workspace_with_evidence(root)
    generation = workspace.create_job("generation", home_id=home_id)
    generation_directory = workspace.root / "generations" / generation.job_id
    generation_directory.mkdir(parents=True)
    (generation_directory / "persona.json").write_text("{}", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="cancel this run"):
        workspace.delete_run(generation.job_id)
    workspace.update_job(
        generation.job_id,
        JobStatus.cancelled,
        JobProgress(phase="cancelled", percent=0, message="Cancelled"),
    )
    assert workspace.delete_run(generation.job_id).runs_removed == 1
    # A generation keeps its days outside `runs/`; deleting the job takes them with it.
    assert not generation_directory.exists()

    summary = workspace.delete_run(job_id)
    assert summary.runs_removed == 1
    assert summary.exports_removed == 1
    assert workspace.get_home(home_id).run_count == 0
    assert workspace.list_residents(home_id)  # the resident context survives its run
    assert workspace.reconcile() == []


def test_deleting_an_export_leaves_the_run_it_came_from_intact(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace, _, job_id = _workspace_with_evidence(root)
    with pytest.raises(WorkspaceError, match="unknown export"):
        workspace.delete_export("export_missing")

    summary = workspace.delete_export("export_fixture")
    assert summary.exports_removed == 1
    assert summary.artifacts_pruned == 1
    assert not (workspace.exports_path / "export_fixture").exists()
    assert set(workspace.run_artifacts(job_id)) == {"execution_trace"}
    assert workspace.reconcile() == []


def test_an_object_two_homes_share_survives_deleting_one_of_them(tmp_path: Path) -> None:
    """Content-addressed storage means one file can back several homes at once.

    Both homes publish the same bytes, so both point at the same catalogue row and the same file.
    Deleting one home must not take the other's stored input with it — the row is only collected
    once nothing that survives still names it.
    """
    workspace = WorkspaceService.create(tmp_path / "workspace", "Shared")
    first = workspace.create_home("First")
    second = workspace.create_home("Second")
    shared = workspace.put_object(b'{"model":1}', role="home_model", home_id=first.home_id)
    workspace.create_revision(first.home_id, "home", shared.artifact_id, status="valid")
    workspace.create_revision(second.home_id, "home", shared.artifact_id, status="valid")

    workspace.delete_home(first.home_id)
    assert (workspace.root / shared.relative_path).is_file()
    assert workspace.get_home(second.home_id).current_home_artifact_id == shared.artifact_id
    assert workspace.reconcile() == []

    workspace.delete_home(second.home_id)
    assert not (workspace.root / shared.relative_path).exists()
