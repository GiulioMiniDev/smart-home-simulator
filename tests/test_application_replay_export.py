from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from xml.sax.saxutils import XMLGenerator

import pytest

from smart_home_sim.application.export import (
    ExportService,
    _csv,
    _filtered,
    _items,
    _record_time,
    _xes_attribute,
)
from smart_home_sim.application.replay import ReplayService
from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import ExportFormat, ExportRequest, JobProgress, JobStatus

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE = PROJECT_ROOT / "examples/materialization/mario_rossi_2026_10_30"


@pytest.fixture(scope="module")
def completed_workspace(tmp_path_factory: pytest.TempPathFactory) -> tuple[WorkspaceService, str]:
    root = tmp_path_factory.mktemp("application-run") / "workspace"
    workspace = WorkspaceService.create(root, "Replay")
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
    return workspace, job.job_id


def test_ground_truth_diary_observable_and_oracle_views(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    diary, total = replay.diary(run_id, limit=5)
    assert total > 5
    assert diary[0].actions
    assert diary[0].source_activity_id
    assert len(diary[0].trace_semantic_digest) == 64
    filtered, filtered_total = replay.diary(
        run_id, actor_id=diary[0].actor_id, query=diary[0].intent, status=diary[0].status
    )
    assert filtered_total > 0
    assert all(item.actor_id == diary[0].actor_id for item in filtered)

    observable, observation_total = replay.observations(run_id, limit=3)
    assert observation_total > 3
    assert all(item.oracle_cause is None for item in observable)
    oracle, _ = replay.observations(run_id, include_oracle=True, limit=3)
    assert all(item.oracle_cause is not None for item in oracle)
    sensor_only, _ = replay.observations(run_id, sensor_id=oracle[0].sensor_id, limit=10)
    assert all(item.sensor_id == oracle[0].sensor_id for item in sensor_only)
    timeline = replay.timeline(run_id, limit=100)
    assert timeline == sorted(timeline, key=lambda item: (item["at"], item["kind"], item["id"]))
    assert {item["kind"] for item in timeline} <= {"activity", "action", "movement"}
    verification = replay.verify(run_id)
    assert verification.matches is True
    assert verification.actual_semantic_digest == verification.expected_semantic_digest


def test_streaming_export_formats_manifest_and_integrity(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl, ExportFormat.csv, ExportFormat.xes],
            roles=["observable", "activities", "actions"],
        )
    )
    assert manifest.observable_oracle_separated is True
    assert len(manifest.files) == 9
    assert all(item.record_count > 0 for item in manifest.files)
    assert service.verify_manifest(manifest.export_id) == manifest
    observable_jsonl = next(
        item for item in manifest.files if item.role == "observable" and item.format == "jsonl"
    )
    first_record = json.loads(
        (workspace.exports_path / observable_jsonl.relative_path)
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert not ({"residentId", "activityExecutionId", "actionExecutionId"} & set(first_record))

    corrupt = workspace.exports_path / manifest.files[0].relative_path
    corrupt.write_text("corrupt", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="integrity checks"):
        service.verify_manifest(manifest.export_id)


def test_replay_requires_complete_run_artifacts(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Incomplete")
    replay = ReplayService(workspace)
    with pytest.raises(WorkspaceError, match="has no 'execution_trace'"):
        replay.diary("missing")


def test_export_streaming_helpers_cover_filters_and_malformed_sources(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"records":[1]}', encoding="utf-8")
    with pytest.raises(WorkspaceError, match="not a record sequence"):
        list(_items(malformed, "records.item"))

    request = ExportRequest(
        run_id="run",
        formats=[ExportFormat.csv],
        roles=["observable"],
        include_start=datetime(2026, 7, 22, 9, tzinfo=UTC),
        include_end=datetime(2026, 7, 22, 10, tzinfo=UTC),
    )
    records = [
        {"observedAt": "2026-07-22T08:00:00+00:00", "value": 1},
        {"observedAt": "2026-07-22T09:30:00+00:00", "value": 2},
        {"observedAt": "2026-07-22T11:00:00+00:00", "value": 3},
    ]
    assert list(_filtered(records, request)) == [records[1]]
    assert _record_time({"value": 1}) is None
    assert _csv(tmp_path / "empty.csv", []) == 0
    with pytest.raises(WorkspaceError, match="stable field set"):
        _csv(tmp_path / "unstable.csv", [{"a": 1}, {"b": 2}])

    target = StringIO()
    xml = XMLGenerator(target, encoding="utf-8")
    _xes_attribute(xml, "enabled", True)
    assert 'value="true"' in target.getvalue()


def test_export_rejects_incomplete_provenance_and_missing_role(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Export guards")
    service = ExportService(workspace)
    request = lambda run_id: ExportRequest(  # noqa: E731
        run_id=run_id,
        formats=[ExportFormat.jsonl],
        roles=["observable"],
    )

    with pytest.raises(WorkspaceError, match="requires bundle"):
        service.export(request("missing"))

    def register_run(run_id: str, trace: dict[str, object]) -> None:
        directory = workspace.runs_path / run_id
        directory.mkdir()
        bundle = directory / "simulation-bundle.json"
        bundle.write_text("{}", encoding="utf-8")
        trace_path = directory / "execution-trace.json"
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        workspace.register_artifact(bundle, role="simulation_bundle", run_id=run_id)
        workspace.register_artifact(trace_path, role="execution_trace", run_id=run_id)

    register_run("no-provenance", {})
    with pytest.raises(WorkspaceError, match="provenance is incomplete"):
        service.export(request("no-provenance"))

    register_run(
        "no-seed",
        {"sourceBundleSha256": "a" * 64, "semanticDigest": "b" * 64},
    )
    with pytest.raises(WorkspaceError, match="seed is invalid"):
        service.export(request("no-seed"))

    register_run(
        "no-observations",
        {"sourceBundleSha256": "a" * 64, "semanticDigest": "b" * 64, "seed": 7},
    )
    with pytest.raises(WorkspaceError, match="has no artifact"):
        service.export(request("no-observations"))
    assert not list(workspace.exports_path.glob(".export_*"))


def test_export_manifest_rejects_missing_and_unsafe_paths(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    with pytest.raises(WorkspaceError, match="escapes"):
        service.verify_manifest("../outside")
    with pytest.raises(WorkspaceError, match="cannot read"):
        service.verify_manifest("missing")

    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["observable"],
        )
    )
    path = workspace.exports_path / manifest.export_id / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["files"][0]["relativePath"] = "../outside.jsonl"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkspaceError, match="unsafe path"):
        service.verify_manifest(manifest.export_id)
