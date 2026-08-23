from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree
from xml.sax.saxutils import XMLGenerator

import pytest
from pydantic import ValidationError

from smart_home_sim.application.export import (
    ExportService,
    _csv,
    _filtered,
    _items,
    _record_time,
    _xes,
    _xes_attribute,
)
from smart_home_sim.application.replay import ReplayService
from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import (
    ExportFormat,
    ExportManifest,
    ExportRequest,
    JobProgress,
    JobStatus,
)
from smart_home_sim.domain.environment import Point2D
from smart_home_sim.domain.execution import MovementExecution, StateTransition, TraceCausality

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE = PROJECT_ROOT / "examples/materialization/mario_rossi_2026_10_30"


def _completed_workspace(root: Path) -> tuple[WorkspaceService, str]:
    """One imported run, ready to replay or export.

    A function rather than only a fixture because the module fixture is shared and one test
    deliberately corrupts a file in it, which puts the workspace into diagnostic mode: a test that
    needs to write afterwards has to bring its own.
    """
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


@pytest.fixture(scope="module")
def completed_workspace(tmp_path_factory: pytest.TempPathFactory) -> tuple[WorkspaceService, str]:
    return _completed_workspace(tmp_path_factory.mktemp("application-run") / "workspace")


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


def test_replay_indexes_every_trace_family_and_bounds_windows(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    trace = json.loads(
        workspace.read_artifact(workspace.run_artifacts(run_id)["execution_trace"].artifact_id)
    )
    start = datetime.fromisoformat(trace["startedAt"])
    end = start + timedelta(hours=12)

    window = replay.events(run_id, start=start, end=end, limit=37)

    assert len(window.items) <= 37
    assert window.window_start == start
    assert window.window_end == end
    expected_kinds = {
        kind
        for kind, records in {
            "activity": trace["activityExecutions"],
            "action": trace["actionExecutions"],
            "movement": trace["movements"],
            "state_transition": trace["stateTransitions"],
            "resource": trace["resourceEvents"],
            "runtime_event": trace["runtimeEvents"],
            "plan_deviation": trace["planDeviations"],
        }.items()
        if records
    }
    assert {
        item.kind for item in replay.events(run_id, start=start, end=end, limit=5000).items
    } >= expected_kinds


def test_replay_frame_is_random_seek_stable_and_oracle_is_opt_in(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    window = replay.events(run_id, limit=100)
    target = window.items[len(window.items) // 2].at

    first = replay.frame(run_id, at=target, include_oracle=False)
    replay.frame(run_id, at=window.trace_end, include_oracle=False)
    second = replay.frame(run_id, at=target, include_oracle=False)

    assert first == second
    assert all(item.oracle_cause is None for item in first.sensor_states)
    oracle = replay.frame(run_id, at=target, include_oracle=True)
    assert any(item.oracle_cause is not None for item in oracle.sensor_states)


def test_replay_interpolation_uses_the_midpoint_between_two_waypoints() -> None:
    from smart_home_sim.application import replay as replay_module

    start = datetime(2026, 8, 23, 8, tzinfo=UTC)
    movement = MovementExecution.model_validate(
        {
            "movementId": "movement_1",
            "actionExecutionId": "action_1",
            "actorId": "resident_1",
            "startedAt": start,
            "endedAt": start + timedelta(seconds=10),
            "originRegionId": "origin",
            "destinationRegionId": "destination",
            "distanceMeters": 10,
            "durationMicroseconds": 10_000_000,
            "waypoints": [
                {
                    "at": start,
                    "regionId": "origin",
                    "position": Point2D(x=2, y=4),
                    "traversalMode": "walking",
                },
                {
                    "at": start + timedelta(seconds=10),
                    "regionId": "destination",
                    "position": Point2D(x=8, y=10),
                    "traversalMode": "walking",
                },
            ],
        }
    )

    assert replay_module._point_at(movement, start + timedelta(seconds=5)) == Point2D(x=5, y=7)


def test_replay_without_a_bundle_seeds_transition_previous_values(tmp_path: Path) -> None:
    workspace, run_id = _completed_workspace(tmp_path / "workspace")
    with workspace.transaction() as connection:
        connection.execute(
            "DELETE FROM artifacts WHERE run_id = ? AND role = 'simulation_bundle'", (run_id,)
        )
    replay = ReplayService(workspace)
    index = replay._index(run_id)
    posture = next(
        item
        for item in index.trace.state_transitions
        if item.subject_type == "resident"
        and item.fact == "posture"
        and item.previous_value is not None
    )
    entity = next(
        item
        for item in index.trace.state_transitions
        if item.subject_type == "entity" and item.previous_value is not None
    )
    instant = min(posture.at, entity.at) - timedelta(microseconds=1)

    frame = replay.frame(run_id, at=instant)

    resident = next(item for item in frame.residents if item.resident_id == posture.subject_id)
    assert resident.posture == posture.previous_value
    assert frame.entity_states[entity.subject_id][entity.fact] == entity.previous_value
    assert replay.frame(run_id, at=index.trace_end).at == index.trace_end


def test_replay_bundle_fallback_keeps_the_first_transition_previous_value() -> None:
    from smart_home_sim.application import replay as replay_module

    at = datetime(2026, 8, 23, 8, tzinfo=UTC)
    trace = SimpleNamespace(
        state_transitions=[
            StateTransition(
                transition_id="first",
                at=at,
                subject_type="resident",
                subject_id="resident_1",
                fact="execution_state",
                previous_value="idle",
                value="performing_activity",
                operation="set",
                causality=TraceCausality(cause_type="action_effect", cause_id="action_1"),
            ),
            StateTransition(
                transition_id="second",
                at=at + timedelta(seconds=1),
                subject_type="resident",
                subject_id="resident_1",
                fact="execution_state",
                previous_value="performing_activity",
                value="moving",
                operation="set",
                causality=TraceCausality(cause_type="action_effect", cause_id="action_2"),
            ),
        ]
    )

    seeded = replay_module._initial_residents(trace, None)

    assert seeded["resident_1"]["execution_state"] == "idle"


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
    # `quality` belongs with them: a column stating which of its own readings the noise model
    # disturbed is an admission no real sensor log makes, and an evaluator reading it is being
    # handed part of the answer. It stays in the internal log; it does not ship.
    assert not (
        {"residentId", "activityExecutionId", "actionExecutionId", "quality"} & set(first_record)
    )
    assert {"sensorId", "observedAt", "measurement", "value"} <= set(first_record)

    corrupt = workspace.exports_path / manifest.files[0].relative_path
    corrupt.write_text("corrupt", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="integrity checks"):
        service.verify_manifest(manifest.export_id)


def test_xes_carries_a_day_per_trace_and_the_standard_extension_keys(tmp_path: Path) -> None:
    """The three keys a process miner reads, on a log cut into cases it can compare.

    Every one of these assertions stands for a way the export used to open in ProM without
    complaint and teach an algorithm nothing: one trace for the whole run, the timestamp filed
    under `observedAt` where nothing looks for it, no lifecycle to pair a start with its
    completion, and every sensor firing named after its `measurement` so that 72k PIR events
    arrived as one indistinguishable activity.
    """
    observable = [
        {"observationId": "o1", "sensorId": "pir_kitchen", "measurement": "motion", "value": 1.0},
        {"observationId": "o2", "sensorId": "pir_bedroom", "measurement": "motion", "value": 1.0},
        {"observationId": "o3", "sensorId": "pir_kitchen", "measurement": "motion", "value": 1.0},
    ]
    # Deliberately out of order inside the day: the second reading closes after the third opens.
    for record, stamp in zip(
        observable,
        ("2026-07-24T23:59:00+02:00", "2026-07-25T08:00:00+02:00", "2026-07-25T07:00:00+02:00"),
        strict=True,
    ):
        record["observedAt"] = stamp

    path = tmp_path / "observable.xes"
    assert _xes(path, "observable", observable, "job_1") == 3
    log = ElementTree.parse(path).getroot()
    namespace = "{http://www.xes-standard.org/}"

    assert [item.get("prefix") for item in log.findall(f"{namespace}extension")] == [
        "concept",
        "time",
        "lifecycle",
        "org",
    ]
    assert len(log.findall(f"{namespace}classifier")) == 2
    traces = log.findall(f"{namespace}trace")
    assert [
        trace.find(f"{namespace}string[@key='concept:name']").get("value") for trace in traces
    ] == ["2026-07-24", "2026-07-25"]
    second = traces[1].findall(f"{namespace}event")
    assert [
        event.find(f"{namespace}date[@key='time:timestamp']").get("value") for event in second
    ] == ["2026-07-25T07:00:00+02:00", "2026-07-25T08:00:00+02:00"]
    assert [
        event.find(f"{namespace}string[@key='concept:name']").get("value") for event in second
    ] == ["pir_kitchen", "pir_bedroom"]
    assert all(
        event.find(f"{namespace}string[@key='lifecycle:transition']").get("value") == "complete"
        for event in second
    )
    # The observable half stays blind: naming the resident here would hand over the oracle.
    assert second[0].find(f"{namespace}string[@key='org:resource']") is None

    # An interval record becomes the standard start/complete pair, counted once.
    activity = {
        "activityExecutionId": "a1",
        "intent": "eat_breakfast",
        "actorId": "francesca_verdi",
        "actualStart": "2026-07-24T08:00:00+02:00",
        "actualEnd": "2026-07-24T08:20:00+02:00",
    }
    paired = tmp_path / "activities.xes"
    assert _xes(paired, "activities", [activity], "job_1") == 1
    events = ElementTree.parse(paired).getroot().findall(f".//{namespace}event")
    assert [
        event.find(f"{namespace}string[@key='lifecycle:transition']").get("value")
        for event in events
    ] == ["start", "complete"]
    assert {
        event.find(f"{namespace}string[@key='concept:instance']").get("value") for event in events
    } == {"a1"}
    assert (
        events[0].find(f"{namespace}string[@key='org:resource']").get("value") == "francesca_verdi"
    )


def test_xes_falls_back_for_undated_roles_and_rejects_disordered_sources(tmp_path: Path) -> None:
    # `oracle` is a join table keyed by observation, not a log: no timestamp, so no day to cut.
    links = [{"observationId": "o1", "causeType": "trace"}, {"observationId": "o2"}]
    undated = tmp_path / "oracle.xes"
    assert _xes(undated, "oracle", links, "job_1") == 2
    namespace = "{http://www.xes-standard.org/}"
    log = ElementTree.parse(undated).getroot()
    trace = log.find(f"{namespace}trace")
    assert len(log.findall(f"{namespace}trace")) == 1
    # The `<global>` block still declares the key; no event carries a value for it.
    assert trace.find(f".//{namespace}date[@key='time:timestamp']") is None

    assert _xes(tmp_path / "empty.xes", "observable", [], "job_1") == 0

    mixed = [
        {"sensorId": "pir_kitchen", "observedAt": "2026-07-24T08:00:00+02:00"},
        {"sensorId": "pir_bedroom"},
    ]
    with pytest.raises(WorkspaceError, match="with and without a timestamp"):
        _xes(tmp_path / "mixed.xes", "observable", mixed, "job_1")

    revisited = [
        {"sensorId": "a", "observedAt": "2026-07-24T08:00:00+02:00"},
        {"sensorId": "b", "observedAt": "2026-07-25T08:00:00+02:00"},
        {"sensorId": "c", "observedAt": "2026-07-24T09:00:00+02:00"},
    ]
    with pytest.raises(WorkspaceError, match="not in chronological order"):
        _xes(tmp_path / "disordered.xes", "observable", revisited, "job_1")


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


def test_export_creates_missing_exports_directory(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    if workspace.exports_path.exists():
        shutil.rmtree(workspace.exports_path)
    assert not workspace.exports_path.exists()

    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["observable"],
        )
    )
    assert workspace.exports_path.exists()
    assert (workspace.exports_path / manifest.export_id / "manifest.json").is_file()


def test_archive_export_creates_valid_zip(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["observable"],
        )
    )
    zip_path = service.archive_export(manifest.export_id)
    assert zip_path.is_file()
    assert zip_path.name == f"{manifest.export_id}.zip"
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        assert f"{manifest.export_id}/manifest.json" in names
        assert f"{manifest.export_id}/observable.jsonl" in names
    relative = f"exports/{manifest.export_id}.zip"
    with workspace.connection() as connection:
        row = connection.execute(
            "SELECT * FROM artifacts WHERE relative_path = ?", (relative,)
        ).fetchone()
    assert row is not None
    assert row["role"] == "export_archive"


def test_repair_auto_registers_orphan_export_zips(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["observable"],
        )
    )
    service.archive_export(manifest.export_id)
    relative = f"exports/{manifest.export_id}.zip"
    # Unregister zip artifact manually to simulate an uncatalogued/orphan export archive
    with workspace.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE relative_path = ?", (relative,))
    assert any(f"orphan file: {relative}" in issue for issue in workspace.reconcile())
    # Repair — which every open runs — adopts the archive rather than reporting it forever.
    assert workspace.repair().artifacts_adopted == 1
    reconciled_issues = [
        issue for issue in workspace.reconcile() if f"orphan file: {relative}" in issue
    ]
    assert reconciled_issues == []
    with workspace.connection() as connection:
        row = connection.execute(
            "SELECT * FROM artifacts WHERE relative_path = ?", (relative,)
        ).fetchone()
    assert row is not None
    assert row["role"] == "export_archive"


def test_the_export_offers_every_role_the_backend_defines() -> None:
    """A role the UI never asks for is a dataset column nobody receives.

    `habit_ground_truth` was added for outline-first horizons, and the value of adding it is
    entirely in it reaching the researcher who downloads the export — so the button must request
    it. Comparing the two lists is what stops one from quietly falling behind the other.
    """
    import re

    from smart_home_sim.application.export import PROFILE_ROLE, ROLE_SOURCES, SUMMARY_ROLE

    source = (PROJECT_ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    match = re.search(r"roles: \[([^\]]+)\]", source)
    assert match is not None, "the export button no longer names its roles"
    requested = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    offered = set(ROLE_SOURCES) | {PROFILE_ROLE, SUMMARY_ROLE}

    assert requested == offered, {
        "missing from the UI": sorted(offered - requested),
        "unknown to the backend": sorted(requested - offered),
    }


def test_an_identical_export_is_reused_rather_than_written_again(tmp_path: Path) -> None:
    """Exporting is deterministic, so a second identical request needs no second copy.

    Each click on the download button was writing another full dataset: one workspace that had
    exported eleven times held 4.5 GB, of which roughly four were duplicates of the same run.
    """
    workspace, run_id = _completed_workspace(tmp_path / "workspace")
    service = ExportService(workspace)
    request = ExportRequest(
        run_id=run_id, formats=[ExportFormat.jsonl], roles=["observable", "activities"]
    )

    first = service.export(request)
    again = service.export(request)

    assert again.export_id == first.export_id
    assert len(list(workspace.exports_path.glob("export_*"))) == 1

    # A different request is a different dataset and still gets its own directory.
    other = service.export(
        ExportRequest(run_id=run_id, formats=[ExportFormat.csv], roles=["observable"])
    )
    assert other.export_id != first.export_id

    # And deleting the files is how the space is reclaimed: the next export rebuilds them.
    shutil.rmtree(workspace.exports_path / first.export_id)
    rebuilt = service.export(request)
    assert rebuilt.export_id != first.export_id
    assert (workspace.exports_path / rebuilt.export_id / "manifest.json").is_file()


def test_export_publishes_the_resident_profile_as_document_page_and_matrix(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)

    manifest = service.export(
        ExportRequest(run_id=run_id, formats=[ExportFormat.jsonl], roles=["resident_profile"])
    )

    assert {item.format for item in manifest.files} == {
        ExportFormat.json,
        ExportFormat.html,
        ExportFormat.csv,
    }
    # The requested format applies to record roles only: a profile is published in the shapes it
    # has, whatever a caller asked for the rest of the dataset.
    assert {item.role for item in manifest.files} == {"resident_profile"}
    assert service.verify_manifest(manifest.export_id) == manifest
    document = next(item for item in manifest.files if item.format == ExportFormat.json)
    payload = json.loads(
        (workspace.exports_path / document.relative_path).read_text(encoding="utf-8")
    )
    assert payload["documentType"] == "resident_profile"
    assert payload["runId"] == run_id
    assert payload["residents"][0]["narrative"]
    page = next(item for item in manifest.files if item.format == ExportFormat.html)
    assert (
        (workspace.exports_path / page.relative_path)
        .read_text(encoding="utf-8")
        .startswith("<!doctype html>")
    )


def test_export_publishes_one_summary_page_that_indexes_the_dataset(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)

    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["summary", "observable", "activities"],
        )
    )

    summary = next(item for item in manifest.files if item.role == "summary")
    assert summary.format is ExportFormat.html
    assert service.verify_manifest(manifest.export_id) == manifest
    page = (workspace.exports_path / summary.relative_path).read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    # The home model and the sensor field reach a reader for the first time here: no other role
    # publishes them, so without this page the log names sensors that are nowhere to be found.
    assert "The home" in page and 'class="plan"' in page
    assert "pir_kitchen" in page
    # And the page indexes the rest of the export, which is why it is written last whatever order
    # the roles were requested in.
    assert "observable.jsonl" in page and "activities.jsonl" in page


def test_a_rebuilt_summary_is_the_same_page(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    """The export promises that deleting a dataset costs nothing but the time to rebuild it."""
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    request = ExportRequest(run_id=run_id, formats=[ExportFormat.csv], roles=["summary"])
    first = service.export(request)

    shutil.rmtree(workspace.exports_path / first.export_id)
    rebuilt = service.export(request)

    assert rebuilt.export_id != first.export_id
    assert [item.sha256 for item in rebuilt.files] == [item.sha256 for item in first.files]


def test_a_windowed_export_profiles_only_the_window(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    whole = service.export(
        ExportRequest(run_id=run_id, formats=[ExportFormat.jsonl], roles=["resident_profile"])
    )
    trace = json.loads(
        workspace.artifact_path(
            workspace.run_artifacts(run_id)["execution_trace"].artifact_id
        ).read_text(encoding="utf-8")
    )
    opened = datetime.fromisoformat(trace["startedAt"])

    windowed = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["resident_profile"],
            include_start=opened,
            include_end=opened + timedelta(days=1),
        )
    )

    def day_count(manifest: ExportManifest) -> int:
        document = next(item for item in manifest.files if item.format == ExportFormat.json)
        return json.loads(
            (workspace.exports_path / document.relative_path).read_text(encoding="utf-8")
        )["dayCount"]

    assert day_count(windowed) < day_count(whole)


def test_only_record_formats_can_be_requested() -> None:
    with pytest.raises(ValidationError, match="only jsonl, csv and xes"):
        ExportRequest(run_id="run", formats=[ExportFormat.html], roles=["observable"])
