"""A generated horizon becomes a home input, then one merged, exportable run of that home."""

from __future__ import annotations

import json
import shutil
import types

from fastapi.testclient import TestClient

from smart_home_sim.application.export import ExportService
from smart_home_sim.application.generation_ingest import (
    GenerationIngestError,
    horizon_revision,
    ingest_generation,
)
from smart_home_sim.application.generation_job import run_generation_job
from smart_home_sim.application.generation_paths import generation_run_dir
from smart_home_sim.application.horizon_run import (
    deploy_horizon_sensors,
    horizon_sensor_field,
    run_horizon_job,
    verify_horizon,
)
from smart_home_sim.application.jobs import JobManager
from smart_home_sim.application.replay import ReplayService
from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import (
    ExportFormat,
    ExportRequest,
    JobProgress,
    JobStatus,
)
from smart_home_sim.domain.sensors import SensorModel
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioConfig
from smart_home_sim.web import create_app


def _h(label: str, kind: str, frequency: str, band: str) -> dict[str, str]:
    return {"label": label, "kind": kind, "frequency": frequency, "time_band": band}


_PERSONA = json.dumps(
    {
        "name": "Elena Bruni",
        "age": 72,
        "sex": "F",
        "occupation": "retired",
        "household": "lives alone",
        "health": [],
        "city": "Bologna",
        "notes": "quiet",
        "routine_anchors": ["morning coffee", "evening pill"],
    }
)
_HABITS = json.dumps(
    {
        "habits": [
            _h("morning coffee", "anchor", "daily", "early_morning"),
            _h("evening pill", "anchor", "daily", "evening"),
            _h("morning walk", "anchor", "daily", "morning"),
            _h("groceries", "contextual", "weekly", "morning"),
            _h("laundry", "contextual", "weekly", "afternoon"),
            _h("call friend", "optional", "few_times_week", "evening"),
            _h("cinema", "optional", "biweekly", "evening"),
            _h("doctor visit", "rare", "monthly", "morning"),
        ]
    }
)


def _pipeline_client() -> LMStudioClient:
    def transport(url: str, body: bytes, timeout: float) -> str:
        text = " ".join(m["content"] for m in json.loads(body)["messages"]).lower()
        reply = _PERSONA if "invent one coherent person" in text else (
            _HABITS if "daily-habit portfolio" in text else "{}"
        )
        return json.dumps({"choices": [{"message": {"content": reply}, "finish_reason": "stop"}]})

    return LMStudioClient(LMStudioConfig(model="qwen3.5-9b"), transport=transport)


def _token(client: TestClient) -> str:
    return client.get("/api/session").json()["token"]


def _generate(workspace: WorkspaceService) -> str:
    job = workspace.create_job(
        "generation",
        request={"brief": "an elderly woman", "startDate": "2026-08-03", "months": 1, "days": 2},
    )
    run_generation_job(workspace, job.job_id, client=_pipeline_client())
    return job.job_id


def test_generation_publishes_a_home_with_authoring_inputs(tmp_path) -> None:
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    generation_job_id = _generate(workspace)

    job = workspace.get_job(generation_job_id)
    assert job.status is JobStatus.completed
    home_id = job.result_reference
    assert home_id is not None
    assert job.home_id == home_id

    home = workspace.get_home(home_id)
    assert "Elena Bruni" in home.name
    # The home is a first-class input: executable plan, sensor field and a bound resident.
    assert home.current_home_artifact_id and home.current_sensor_artifact_id
    residents = workspace.list_residents(home_id)
    assert len(residents) == 1
    assert residents[0].scenario_artifact_id and residents[0].behavior_artifact_id
    scenario = json.loads(workspace.read_artifact(residents[0].scenario_artifact_id))
    assert len(scenario["days"]) == 2

    provenance = horizon_revision(workspace, home_id)
    assert provenance is not None
    assert provenance["generationJobId"] == generation_job_id
    assert provenance["dayCount"] == 2
    assert workspace.reconcile() == []


def test_horizon_run_merges_every_day_into_one_exportable_run(tmp_path) -> None:
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    generation_job_id = _generate(workspace)
    home_id = workspace.get_job(generation_job_id).result_reference
    assert home_id is not None

    run = workspace.create_job(
        "simulation", home_id=home_id, request={"generationJobId": generation_job_id}
    )
    run_horizon_job(workspace, run.job_id)
    assert workspace.get_job(run.job_id).status is JobStatus.completed

    artifacts = workspace.run_artifacts(run.job_id)
    assert {
        "execution_trace",
        "observable_sensor_log",
        "oracle_mapping",
        "horizon_manifest",
    } <= set(artifacts)
    summary = json.loads(
        (workspace.runs_path / run.job_id / "horizon-manifest.json").read_text(encoding="utf-8")
    )
    assert summary["dayCount"] == 2
    assert summary["observationCount"] > 0

    log = json.loads(
        (workspace.runs_path / run.job_id / "observable-sensor-log.json").read_text("utf-8")
    )
    oracle = json.loads(
        (workspace.runs_path / run.job_id / "oracle-mapping.json").read_text("utf-8")
    )
    # One dataset, not two day-shaped ones: every observation is present once and oracle-linked.
    assert len(log["records"]) == summary["observationCount"]
    assert len(oracle["links"]) == len(log["records"])
    assert len({record["observationId"] for record in log["records"]}) == len(log["records"])
    # Both generated days are in the same log (the overnight sleep spills into the next date).
    observed_days = {record["observedAt"][:10] for record in log["records"]}
    assert {"2026-08-03", "2026-08-04"} <= observed_days

    verification = ReplayService(workspace).verify(run.job_id)
    assert verification.matches

    manifest = ExportService(workspace).export(
        ExportRequest(
            run_id=run.job_id,
            formats=[ExportFormat.jsonl],
            roles=["observable", "oracle"],
        )
    )
    counts = {item.role: item.record_count for item in manifest.files}
    assert counts["observable"] == len(log["records"])
    assert counts["oracle"] == len(oracle["links"])
    assert workspace.reconcile() == []


def test_horizon_run_reports_cancellation_and_refuses_to_republish(tmp_path) -> None:
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    generation_job_id = _generate(workspace)
    home_id = workspace.get_job(generation_job_id).result_reference
    assert home_id is not None

    cancelled = workspace.create_job(
        "simulation", home_id=home_id, request={"generationJobId": generation_job_id}
    )
    workspace.update_job(
        cancelled.job_id,
        JobStatus.cancelled,
        JobProgress(phase="cancelled", percent=0, message="stop"),
    )
    run_horizon_job(workspace, cancelled.job_id)
    assert workspace.get_job(cancelled.job_id).status is JobStatus.cancelled
    assert not (workspace.runs_path / cancelled.job_id).exists()
    assert not list(workspace.runs_path.glob(f".{cancelled.job_id}.*"))

    published = workspace.create_job(
        "simulation", home_id=home_id, request={"generationJobId": generation_job_id}
    )
    (workspace.runs_path / published.job_id).mkdir(parents=True)
    run_horizon_job(workspace, published.job_id)
    record = workspace.get_job(published.job_id)
    assert record.status is JobStatus.failed
    assert "already published" in (record.error_message or "")


def test_horizon_installs_one_sensor_field_over_days_that_deploy_different_ones(tmp_path) -> None:
    """A day that never opens the fridge must still observe the fridge sensor.

    ``deploy_sensors`` derives contact sensors from the actions of the day it is given, so days of
    one horizon deploy different fields. The horizon installs their union once.
    """
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    generation_job_id = _generate(workspace)
    full, _ = deploy_horizon_sensors(workspace, generation_job_id)
    assert len(full.sensors) >= 2

    # A day whose plan touched fewer entities: the same field minus its last contact sensor.
    reduced_payload = json.loads(full.model_dump_json(by_alias=True))
    dropped = next(
        item for item in reversed(reduced_payload["sensors"]) if item["sensorType"] == "contact"
    )
    reduced_payload["sensors"] = [
        item for item in reduced_payload["sensors"] if item["sensorId"] != dropped["sensorId"]
    ]
    reduced = SensorModel.model_validate_json(json.dumps(reduced_payload))

    field, introduced = horizon_sensor_field(
        [("day-2", reduced), ("day-1", full)],
        source_bundle_id="horizon_test",
        source_bundle_sha256="b" * 64,
    )
    assert {item.sensor_id for item in field.sensors} == {
        item.sensor_id for item in full.sensors
    }
    assert introduced["day-1"] == [dropped["sensorId"]]
    assert field.source_bundle_id == "horizon_test"


def test_verify_horizon_rejects_tampered_evidence(tmp_path) -> None:
    trace = tmp_path / "execution-trace.json"
    summary = tmp_path / "horizon-manifest.json"
    trace.write_text(
        json.dumps(
            {
                "sourceBundleId": "horizon_gen",
                "sourceBundleSha256": "0" * 64,
                "seed": 1,
                "activityExecutions": [],
                "actionExecutions": [],
                "movements": [],
                "stateTransitions": [],
                "resourceEvents": [],
                "runtimeEvents": [],
                "planDeviations": [],
                "finalState": {},
                "semanticDigest": "f" * 64,
            }
        ),
        encoding="utf-8",
    )
    summary.write_text(json.dumps({"days": [{"sourceBundleSha256": "a" * 64}]}), encoding="utf-8")
    matches, expected, actual = verify_horizon(trace, summary)
    assert not matches
    assert expected == "f" * 64
    assert actual != expected


def test_publishing_an_earlier_generation_rebuilds_its_horizon_scenario(tmp_path) -> None:
    app = create_app(tmp_path / "ws")
    workspace = app.state.workspace
    generation_job_id = _generate(workspace)
    published_home = workspace.get_job(generation_job_id).result_reference
    assert published_home is not None
    expected_days = len(
        json.loads(
            (generation_run_dir(workspace, generation_job_id) / "horizon-scenario.json").read_text(
                encoding="utf-8"
            )
        )["days"]
    )

    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        # A generation that already has its home must not publish a second one.
        again = client.post(f"/api/generation/{generation_job_id}/publish", headers=headers)
        assert again.status_code == 409
        assert "already published" in again.json()["detail"]["message"]

    # Simulate a generation from before the home workflow: no home, no horizon scenario file.
    legacy = workspace.create_job("generation", request={})
    legacy_dir = generation_run_dir(workspace, legacy.job_id)
    shutil.copytree(generation_run_dir(workspace, generation_job_id), legacy_dir)
    (legacy_dir / "horizon-scenario.json").unlink()

    app = create_app(tmp_path / "ws")
    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        published = client.post(f"/api/generation/{legacy.job_id}/publish", headers=headers)
        assert published.status_code == 201
        home_id = published.json()["homeId"]
        assert home_id != published_home
        assert published.json()["dayCount"] == 2

        detail = client.get(f"/api/homes/{home_id}", headers=headers)
        resident = detail.json()["residents"][0]
        scenario = json.loads(
            app.state.workspace.read_artifact(resident["scenarioArtifactId"])
        )
        # The rebuilt document holds every day of the horizon, spanning the whole window.
        assert len(scenario["days"]) == expected_days
        assert scenario["simulationWindow"]["start"] < scenario["simulationWindow"]["end"]


def test_ingest_requires_generated_artifacts(tmp_path) -> None:
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    job = workspace.create_job("generation", request={})
    try:
        ingest_generation(workspace, job.job_id)
    except GenerationIngestError as error:
        assert "artifact directory" in str(error)
    else:  # pragma: no cover - the guard must reject an empty generation
        raise AssertionError("an empty generation must not publish a home")


def test_start_horizon_run_requires_a_generated_home(monkeypatch, tmp_path) -> None:
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    manager = JobManager(workspace)

    class _FakeProcess:
        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(
        manager, "_context", types.SimpleNamespace(Process=lambda **kwargs: _FakeProcess())
    )
    authored = workspace.create_home("Authored by hand")
    try:
        manager.start_horizon_run(authored.home_id)
    except Exception as error:  # WorkspaceError
        assert "local generation" in str(error)
    else:  # pragma: no cover
        raise AssertionError("an authored home has no horizon to run")


def test_run_endpoint_routes_a_generated_home_to_its_horizon(monkeypatch, tmp_path) -> None:
    app = create_app(tmp_path / "ws")
    workspace = app.state.workspace
    generation_job_id = _generate(workspace)
    home_id = workspace.get_job(generation_job_id).result_reference
    assert home_id is not None
    started: list[str] = []
    monkeypatch.setattr(
        app.state.jobs,
        "start_horizon_run",
        lambda home: (
            started.append(home)
            or workspace.create_job("simulation", home_id=home, request={}),
        )[-1],
    )
    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        detail = client.get(f"/api/homes/{home_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["generation"]["generationJobId"] == generation_job_id

        resident = detail.json()["residents"][0]
        response = client.post(
            f"/api/homes/{home_id}/runs",
            headers=headers,
            json={
                "scenario_artifact_id": resident["scenarioArtifactId"],
                "behavior_artifact_id": resident["behaviorArtifactId"],
            },
        )
        assert response.status_code == 202
        assert started == [home_id]

        listing = client.get("/api/generations", headers=headers)
        assert generation_job_id in {row["jobId"] for row in listing.json()}
        artifact = client.get(
            f"/api/generation/{generation_job_id}/artifact/horizon-scenario.json", headers=headers
        )
        assert artifact.status_code == 200
