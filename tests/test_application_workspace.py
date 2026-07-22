from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import (
    ApplicationIssue,
    GraphicalReference,
    JobProgress,
    JobStatus,
)


def test_workspace_persists_relationships_jobs_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace = WorkspaceService.create(root, "Acceptance lab")
    assert workspace.summary().name == "Acceptance lab"
    assert workspace.summary().format_version == "1.0.0"

    home = workspace.create_home("Test apartment", "Transactional fixture")
    scenario = workspace.put_object(b'{"schemaVersion":"1.0.0"}\n', role="scenario")
    behavior = workspace.put_object(b'{"packageVersion":"1.0.0"}\n', role="behavior")
    resident = workspace.add_resident(
        home.home_id,
        "source_resident",
        "Resident",
        scenario_artifact_id=scenario.artifact_id,
        behavior_artifact_id=behavior.artifact_id,
    )
    assert workspace.list_residents(home.home_id) == [resident]
    with pytest.raises(WorkspaceError, match="already associated"):
        workspace.add_resident(home.home_id, "source_resident", "Duplicate")

    revision = workspace.create_revision(
        home.home_id,
        "home",
        scenario.artifact_id,
        status="valid",
        provenance={"source": "test"},
    )
    assert revision.startswith("revision_")
    assert workspace.get_home(home.home_id).current_home_artifact_id == scenario.artifact_id

    job = workspace.create_job("simulation", home_id=home.home_id, seed=4, request={"x": 1})
    assert job.status is JobStatus.queued
    running = workspace.update_job(
        job.job_id,
        JobStatus.running,
        JobProgress(phase="execution", percent=30, message="Executing"),
        process_id=123,
    )
    assert running.started_at is not None
    completed = workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Done"),
        result_reference=job.job_id,
    )
    assert completed.finished_at is not None
    assert workspace.job_request(job.job_id) == {"x": 1}
    assert [event.sequence for event in workspace.list_events(job.job_id)] == [1, 2, 3]
    assert workspace.list_events(job.job_id, after=2)[0].message == "Done"
    assert workspace.list_jobs(home_id=home.home_id, limit=1) == [completed]

    manifest = workspace.manifest()
    assert manifest.workspace.home_count == 1
    assert {item.role for item in manifest.artifacts} == {"scenario", "behavior"}
    assert workspace.read_artifact(scenario.artifact_id).startswith(b"{")
    assert WorkspaceService.open(root).summary().workspace_id == manifest.workspace.workspace_id


def test_workspace_rejects_unsafe_or_corrupt_artifacts_and_recovers_jobs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    workspace = WorkspaceService.create(root, "Recovery")
    home = workspace.create_home("Recovery home")
    artifact = workspace.put_object(b"original", role="fixture", suffix=".bin")
    duplicate_content = workspace.put_object(b"original", role="secondary", suffix=".dat")
    assert duplicate_content.artifact_id != artifact.artifact_id
    assert duplicate_content.sha256 == artifact.sha256
    with pytest.raises(WorkspaceError, match="outside"):
        workspace.register_artifact(tmp_path / "outside.bin", role="outside")
    job = workspace.create_job("simulation", home_id=home.home_id)
    workspace.update_job(
        job.job_id,
        JobStatus.running,
        JobProgress(phase="execution", percent=5, message="Started"),
    )
    path = workspace.artifact_path(artifact.artifact_id)
    path.write_bytes(b"changed")
    with pytest.raises(WorkspaceError, match="missing or corrupt"):
        workspace.read_artifact(artifact.artifact_id)
    issues = workspace.reconcile()
    assert any("digest mismatch" in issue for issue in issues)
    with pytest.raises(WorkspaceError, match="diagnostic mode"):
        workspace.create_home("Publication must be paused")
    reopened = WorkspaceService.open(root, reconcile=False)
    assert reopened.get_job(job.job_id).status is JobStatus.interrupted
    assert reopened.get_job(job.job_id).error_code == "BACKEND_INTERRUPTED"


def test_workspace_duplicate_creation_unknown_ids_and_terminal_validation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace = WorkspaceService.create(root, "Errors")
    with pytest.raises(WorkspaceError, match="already exists"):
        WorkspaceService.create(root, "Again")
    with pytest.raises(WorkspaceError, match="required"):
        workspace.create_home(" ")
    with pytest.raises(WorkspaceError, match="unknown home"):
        workspace.get_home("missing")
    with pytest.raises(WorkspaceError, match="unknown artifact"):
        workspace.read_artifact("missing")
    with pytest.raises(WorkspaceError, match="unknown job"):
        workspace.get_job("missing")
    with pytest.raises(ValueError, match="terminal jobs require"):
        from smart_home_sim.domain.application import JobRecord

        JobRecord(
            job_id="job",
            kind="simulation",
            status=JobStatus.completed,
            progress=JobProgress(phase="done", percent=100, message="Done"),
            requested_at=datetime(2026, 7, 22, tzinfo=UTC),
        )


def test_workspace_archive_round_trip_and_traversal_rejection(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "source", "Portable")
    home = workspace.create_home("Archived home")
    artifact = workspace.put_object(b"portable", role="fixture", home_id=home.home_id)
    archive = workspace.export_archive(tmp_path / "portable.shw")

    imported = WorkspaceService.import_archive(archive, tmp_path / "restored")
    assert imported.summary().workspace_id == workspace.summary().workspace_id
    assert imported.read_artifact(artifact.artifact_id) == b"portable"
    assert imported.reconcile() == []

    malicious = tmp_path / "malicious.shw"
    with zipfile.ZipFile(malicious, "w") as handle:
        handle.writestr("../outside.txt", "unsafe")
    with pytest.raises(WorkspaceError, match="unsafe path"):
        WorkspaceService.import_archive(malicious, tmp_path / "unsafe")


def test_workspace_archive_limits_missing_database_and_invalid_zip(tmp_path: Path) -> None:
    archive = tmp_path / "limited.shw"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload.txt", "payload")
    with pytest.raises(WorkspaceError, match="too many files"):
        WorkspaceService.import_archive(archive, tmp_path / "too-many", maximum_files=0)
    with pytest.raises(WorkspaceError, match="extraction limit"):
        WorkspaceService.import_archive(
            archive, tmp_path / "too-large", maximum_uncompressed_bytes=0
        )
    with pytest.raises(WorkspaceError, match="no database"):
        WorkspaceService.import_archive(archive, tmp_path / "missing-db")

    invalid = tmp_path / "invalid.shw"
    invalid.write_bytes(b"not a zip archive")
    with pytest.raises(WorkspaceError, match="cannot import"):
        WorkspaceService.import_archive(invalid, tmp_path / "invalid")


def test_workspace_archive_rejects_nonempty_duplicate_and_symlink(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "source", "Archive guards")
    archive = workspace.export_archive(tmp_path / "portable.shw")
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    nonempty.joinpath("keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="not empty"):
        WorkspaceService.import_archive(archive, nonempty)

    duplicate = tmp_path / "duplicate.shw"
    with (
        pytest.warns(UserWarning, match="Duplicate name"),
        zipfile.ZipFile(duplicate, "w") as handle,
    ):
        handle.writestr("same.txt", "first")
        handle.writestr("same.txt", "second")
    with pytest.raises(WorkspaceError, match="duplicate paths"):
        WorkspaceService.import_archive(duplicate, tmp_path / "duplicate")

    symlink = tmp_path / "symlink.shw"
    link = zipfile.ZipInfo("workspace.sqlite3")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    with zipfile.ZipFile(symlink, "w") as handle:
        handle.writestr(link, "target")
    with pytest.raises(WorkspaceError, match="symbolic link"):
        WorkspaceService.import_archive(symlink, tmp_path / "symlink")

    existing_empty = tmp_path / "existing-empty"
    existing_empty.mkdir()
    restored = WorkspaceService.import_archive(archive, existing_empty)
    assert restored.summary().workspace_id == workspace.summary().workspace_id


def test_workspace_persists_settings_issues_replay_and_blocks_live_archive(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Persistent metadata")
    home = workspace.create_home("Metadata home")
    issue = ApplicationIssue(
        code="HOME_ROUTE_INVALID",
        severity="error",
        stage="topology",
        path="$.connections.0",
        message="The route is disconnected",
        details={"connectionId": "door_1"},
        graphical_reference=GraphicalReference(surface="home", element_id="door_1"),
    )
    workspace.replace_validation_issues(home.home_id, [issue])
    assert workspace.list_validation_issues(home.home_id) == [issue]
    assert workspace.get_home(home.home_id).issue_count == 1
    workspace.replace_validation_issues(home.home_id, [])
    assert workspace.get_home(home.home_id).issue_count == 0

    assert workspace.get_setting("theme", "light") == "light"
    assert workspace.set_setting("theme", "dark") == "dark"
    assert WorkspaceService.open(workspace.root).get_setting("theme") == "dark"

    run_path = workspace.runs_path / "run_1"
    run_path.mkdir()
    trace_path = run_path / "execution-trace.json"
    trace_path.write_text("{}", encoding="utf-8")
    workspace.register_artifact(trace_path, role="execution_trace", run_id="run_1")
    saved = workspace.save_replay_session(
        "run_1",
        verified_digest="a" * 64,
        position_at=datetime(2026, 7, 22, tzinfo=UTC),
        filters={"actorId": "resident_1"},
    )
    assert saved["verifiedDigest"] == "a" * 64
    assert workspace.replay_session("run_1")["filters"] == {"actorId": "resident_1"}

    job = workspace.create_job("simulation", home_id=home.home_id)
    with pytest.raises(WorkspaceError, match="active jobs"):
        workspace.export_archive(tmp_path / "live.shw")
    workspace.update_job(
        job.job_id,
        JobStatus.cancelled,
        JobProgress(phase="cancelled", percent=0, message="Cancelled"),
    )
    assert workspace.export_archive(tmp_path / "stable.shw").is_file()
