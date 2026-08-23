from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from smart_home_sim.application.generation_ingest import HORIZON_REVISION_KIND
from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobStatus
from smart_home_sim.web import create_app
from smart_home_sim.web.app import _quieten_client_disconnects

PROJECT_ROOT = Path(__file__).parents[1]


def _token(client: TestClient) -> str:
    response = client.get("/api/session")
    assert response.status_code == 200
    return response.json()["token"]


def test_local_api_session_workspace_authoring_and_errors(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspace", workspace_name="API acceptance")
    with TestClient(app) as client:
        assert client.get("/api/overview").status_code == 401
        token = _token(client)
        headers = {"X-Workspace-Token": token}
        created = client.post(
            "/api/homes",
            headers=headers,
            json={"name": "API home", "description": "Fixture"},
        )
        assert created.status_code == 201
        home_id = created.json()["homeId"]
        payload = json.loads(
            (PROJECT_ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text(
                encoding="utf-8"
            )
        )
        imported = client.post(
            f"/api/homes/{home_id}/authoring-bundle",
            headers=headers,
            json=payload,
        )
        assert imported.status_code == 200
        assert imported.json()["valid"] is True
        assert imported.json()["bundleArtifact"]["role"] == "simulation_authoring_bundle"
        advanced = client.post(
            f"/api/homes/{home_id}/authoring",
            headers=headers,
            json={
                "scenario": payload["scenario"],
                "personal_process_package": payload["personalProcessPackage"],
            },
        )
        assert advanced.status_code == 200
        assert advanced.json()["valid"] is True
        detail = client.get(f"/api/homes/{home_id}", headers=headers).json()
        assert detail["residents"][0]["sourceResidentId"] == "resident_1"
        overview = client.get("/api/overview", headers=headers).json()
        assert overview["workspace"]["homeCount"] == 1
        manifest = client.get("/api/workspace/manifest", headers=headers).json()
        assert manifest["documentType"] == "application_workspace_manifest"
        setting = client.put("/api/settings/theme", headers=headers, json={"value": "dark"})
        assert setting.json() == {"key": "theme", "value": "dark"}
        assert client.get("/api/settings/theme", headers=headers).json()["value"] == "dark"
        archive = client.get("/api/workspace/archive", headers=headers)
        assert archive.status_code == 200
        assert archive.content.startswith(b"PK")
        assert archive.headers["content-type"].startswith(
            "application/vnd.smart-home-workspace+zip"
        )
        invalid = client.put(
            f"/api/homes/{home_id}/home-model", headers=headers, json={"model": {}}
        )
        assert invalid.status_code == 200
        assert invalid.json()["valid"] is False
        persisted = client.get(f"/api/homes/{home_id}", headers=headers).json()["issues"]
        assert persisted[0]["code"] == "HOME_STRUCTURE_INVALID"
        missing = client.get("/api/homes/missing", headers=headers)
        assert missing.status_code == 409
        assert missing.json()["error"]["code"] == "WORKSPACE_OPERATION_FAILED"


def test_the_environment_endpoint_guards_its_inputs_and_generated_homes(tmp_path: Path) -> None:
    """Building the environment is only offered where it is the missing step.

    A home created from a local generation already carries the plan and the sensor field its days
    were generated with, so rebuilding them from a scenario would replace reviewed models with
    different ones. It is refused with the reason rather than silently doing something else.
    """
    root = tmp_path / "workspace"
    workspace = WorkspaceService.create(root, "Environment API")
    authored = workspace.create_home("Authored")
    generated = workspace.create_home("Generated")
    workspace.create_revision(
        generated.home_id,
        HORIZON_REVISION_KIND,
        None,
        status="valid",
        provenance={"generationJobId": "job_generation"},
    )

    app = create_app(root)
    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        body = {"scenario_artifact_id": "missing", "behavior_artifact_id": "missing"}
        refused = client.post(
            f"/api/homes/{generated.home_id}/environment", headers=headers, json=body
        )
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "ENVIRONMENT_ALREADY_GENERATED"
        unknown = client.post(
            f"/api/homes/{authored.home_id}/environment", headers=headers, json=body
        )
        assert unknown.status_code == 409
        assert "unknown artifact" in unknown.json()["error"]["message"]
        assert workspace.list_jobs() == []


def test_api_rejects_non_loopback_client(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspace", workspace_name="Loopback")
    with TestClient(app, client=("192.0.2.10", 5000)) as client:
        response = client.get("/api/session")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOOPBACK_REQUIRED"


def test_failed_job_detail_serves_persisted_structured_issues(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace = WorkspaceService.create(root, "Failed run API")
    home = workspace.create_home("Failed run")
    job = workspace.create_job("simulation", home_id=home.home_id, seed=7)
    workspace.append_event(
        job.job_id,
        "issue",
        "Action 'leave_home' failed its precondition.",
        level="error",
        payload={
            "phase": "simulation",
            "code": "PRECONDITION_FAILED",
            "stage": "execution",
            "path": "$.actionBindings[activity_7:action_02]",
            "details": {"activityId": "activity_7", "actual": False},
        },
    )
    workspace.update_job(
        job.job_id,
        JobStatus.failed,
        JobProgress(phase="simulation", percent=52, message="Precondition failed"),
        error_code="PRECONDITION_FAILED",
        error_message="Action 'leave_home' failed its precondition.",
    )

    app = create_app(root)
    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        detail = client.get(f"/api/jobs/{job.job_id}", headers=headers)

    assert detail.status_code == 200
    payload = detail.json()
    issue = next(event for event in payload["events"] if event["eventType"] == "issue")
    assert issue["payload"]["code"] == "PRECONDITION_FAILED"
    assert issue["payload"]["details"] == {"activityId": "activity_7", "actual": False}


def test_run_replay_export_sse_and_file_endpoints(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace = WorkspaceService.create(root, "Run API")
    home = workspace.create_home("Golden run")
    job = workspace.create_job("simulation", home_id=home.home_id, seed=7)
    run_directory = workspace.runs_path / job.job_id
    shutil.copytree(
        PROJECT_ROOT / "examples/materialization/mario_rossi_2026_10_30",
        run_directory,
    )
    workspace.import_run_directory(job.job_id, run_directory)
    workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Complete"),
        result_reference=job.job_id,
    )
    trace_only_job = workspace.create_job("simulation", home_id=home.home_id, seed=8)
    trace_only_directory = workspace.runs_path / trace_only_job.job_id
    trace_only_directory.mkdir()
    shutil.copyfile(
        PROJECT_ROOT / "examples/materialization/mario_rossi_2026_10_30/execution-trace.json",
        trace_only_directory / "execution-trace.json",
    )
    workspace.register_artifact(
        trace_only_directory / "execution-trace.json",
        role="execution_trace",
        run_id=trace_only_job.job_id,
    )
    missing_trace_job = workspace.create_job("simulation", home_id=home.home_id, seed=9)

    app = create_app(root)
    with TestClient(app) as client:
        token = _token(client)
        headers = {"X-Workspace-Token": token}
        assert client.get("/").status_code == 200
        assert client.get("/simulations/client-route").status_code == 200
        assert any(
            item["jobId"] == job.job_id and item["status"] == "completed"
            for item in client.get("/api/jobs", headers=headers).json()
        )
        detail = client.get(f"/api/jobs/{job.job_id}", headers=headers).json()
        assert "execution_trace" in detail["artifacts"]
        assert client.get(f"/api/runs/{job.job_id}/diary", headers=headers).json()["total"]
        observable = client.get(f"/api/runs/{job.job_id}/observations", headers=headers).json()
        assert observable["mode"] == "observable"
        oracle = client.get(
            f"/api/runs/{job.job_id}/observations?include_oracle=true", headers=headers
        ).json()
        assert oracle["mode"] == "oracle"
        trace = json.loads(
            workspace.read_artifact(
                workspace.run_artifacts(job.job_id)["execution_trace"].artifact_id
            )
        )
        raw_timeline_ids = {
            item[key]
            for records, key in (
                (trace["activityExecutions"], "activityExecutionId"),
                (trace["actionExecutions"], "actionExecutionId"),
                (trace["movements"], "movementId"),
            )
            for item in records
        }
        timeline = client.get(f"/api/runs/{job.job_id}/timeline?limit=5000", headers=headers)
        assert timeline.status_code == 200
        assert {item["kind"] for item in timeline.json()} <= {"activity", "action", "movement"}
        assert all("actorId" not in item for item in timeline.json())
        assert raw_timeline_ids.isdisjoint({item["id"] for item in timeline.json()})
        oracle_timeline = client.get(
            f"/api/runs/{job.job_id}/timeline?limit=5000&include_oracle=true", headers=headers
        )
        assert any(
            item["id"] in raw_timeline_ids and item["actorId"] for item in oracle_timeline.json()
        )
        trace_only_timeline = client.get(
            f"/api/runs/{trace_only_job.job_id}/timeline?limit=5000", headers=headers
        )
        assert trace_only_timeline.status_code == 200
        assert {item["kind"] for item in trace_only_timeline.json()} <= {
            "activity",
            "action",
            "movement",
        }
        assert all("actorId" not in item for item in trace_only_timeline.json())
        assert raw_timeline_ids.isdisjoint({item["id"] for item in trace_only_timeline.json()})
        trace_only_oracle_timeline = client.get(
            f"/api/runs/{trace_only_job.job_id}/timeline?limit=5000&include_oracle=true",
            headers=headers,
        )
        assert trace_only_oracle_timeline.status_code == 200
        assert any(
            item["id"] in raw_timeline_ids and item["actorId"]
            for item in trace_only_oracle_timeline.json()
        )
        missing_trace_session = client.get(
            f"/api/runs/{missing_trace_job.job_id}/replay/session", headers=headers
        )
        assert missing_trace_session.status_code == 409
        assert "execution_trace" in missing_trace_session.json()["error"]["message"]
        missing_trace_write = client.put(
            f"/api/runs/{missing_trace_job.job_id}/replay/session",
            headers=headers,
            json={"filters": {"speed": 1}},
        )
        assert missing_trace_write.status_code == 409
        assert "execution_trace" in missing_trace_write.json()["error"]["message"]
        events = client.get(
            f"/api/runs/{job.job_id}/replay/events",
            params={"limit": 25, "kinds": "movement,observation", "include_oracle": "false"},
            headers=headers,
        )
        assert events.status_code == 200
        assert len(events.json()["items"]) <= 25
        assert {item["kind"] for item in events.json()["items"]} <= {"movement", "observation"}
        assert all("actorId" not in item for item in events.json()["items"])
        observable_serialized = json.dumps(events.json())
        assert all(
            item["label"] == f"{item['kind'].replace('_', ' ').title()} event"
            for item in events.json()["items"]
        )
        daily_summaries = client.get(
            f"/api/runs/{job.job_id}/replay/events",
            params={"kinds": "daily_summary", "include_oracle": "false", "limit": 25},
            headers=headers,
        )
        assert daily_summaries.status_code == 200
        assert daily_summaries.json()["total"] == len(trace["dailySummaries"])
        assert all(item["kind"] == "daily_summary" for item in daily_summaries.json()["items"])
        assert all(
            item["label"] == "Daily Summary event" for item in daily_summaries.json()["items"]
        )
        assert all("actorId" not in item for item in daily_summaries.json()["items"])
        observable_actor_filter = client.get(
            f"/api/runs/{job.job_id}/replay/events",
            params={"actor_id": trace["movements"][0]["actorId"]},
            headers=headers,
        )
        assert observable_actor_filter.status_code == 422
        assert observable_actor_filter.json()["detail"]["code"] == "ORACLE_REPLAY_OPT_IN_REQUIRED"
        oracle_actor_filter = client.get(
            f"/api/runs/{job.job_id}/replay/events",
            params={
                "actor_id": trace["movements"][0]["actorId"],
                "include_oracle": "true",
            },
            headers=headers,
        )
        assert oracle_actor_filter.status_code == 200
        assert oracle_actor_filter.json()["items"]
        assert all(
            item["actorId"] == trace["movements"][0]["actorId"]
            for item in oracle_actor_filter.json()["items"]
        )
        assert any(
            item["label"] not in observable_serialized
            for item in oracle_actor_filter.json()["items"]
        )

        target = events.json()["items"][0]["at"]
        frame = client.get(
            f"/api/runs/{job.job_id}/replay/frame",
            params={"at": target, "include_oracle": "false"},
            headers=headers,
        )
        assert frame.status_code == 200
        assert all(item.get("oracleCause") is None for item in frame.json()["sensorStates"])
        assert all("residentId" not in item for item in frame.json()["residents"])
        assert all("activityLabel" not in item for item in frame.json()["residents"])
        assert all(isinstance(item["activityActive"], bool) for item in frame.json()["residents"])
        assert "activeEventIds" not in frame.json()

        activity = trace["activityExecutions"][0]
        active_oracle_frame = client.get(
            f"/api/runs/{job.job_id}/replay/frame",
            params={"at": activity["actualStart"], "include_oracle": "true"},
            headers=headers,
        )
        assert active_oracle_frame.status_code == 200
        active_resident = next(
            item
            for item in active_oracle_frame.json()["residents"]
            if item["residentId"] == activity["actorId"]
        )
        assert active_resident["activityActive"] is True
        assert active_resident["activityLabel"] == activity["intent"]
        ended_oracle_frame = client.get(
            f"/api/runs/{job.job_id}/replay/frame",
            params={"at": activity["actualEnd"], "include_oracle": "true"},
            headers=headers,
        )
        ended_resident = next(
            item
            for item in ended_oracle_frame.json()["residents"]
            if item["residentId"] == activity["actorId"]
        )
        assert ended_resident["activityActive"] is False
        assert ended_resident["activityLabel"] is None

        assert (
            client.get(
                f"/api/runs/{job.job_id}/replay/events?limit=5001", headers=headers
            ).status_code
            == 422
        )
        assert (
            client.get(
                f"/api/runs/{job.job_id}/replay/events",
                params={"start": "2026-10-31T00:00:00Z", "end": "2026-10-30T00:00:00Z"},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.get(
                f"/api/runs/{job.job_id}/replay/events?kinds=unknown", headers=headers
            ).status_code
            == 422
        )
        assert client.get("/api/runs/missing/replay/events", headers=headers).status_code == 409
        profile = client.get(f"/api/runs/{job.job_id}/profile", headers=headers).json()
        assert profile["documentType"] == "resident_profile"
        assert profile["residents"][0]["narrative"]
        coarse = client.get(
            f"/api/runs/{job.job_id}/profile?slot_minutes=60", headers=headers
        ).json()
        assert len(coarse["slotLabels"]) == 24
        page = client.get(f"/api/runs/{job.job_id}/profile/page", headers=headers)
        assert page.headers["content-type"].startswith("text/html")
        assert page.text.startswith("<!doctype html>")
        assert "attachment" in page.headers["content-disposition"]
        models = client.get(f"/api/runs/{job.job_id}/models", headers=headers).json()
        assert {"homeModel", "sensorModel"} <= set(models)
        verification = client.post(f"/api/runs/{job.job_id}/replay/verify", headers=headers).json()
        assert verification["matches"] is True
        assert client.get(f"/api/runs/{job.job_id}/replay/session", headers=headers).json()[
            "verifiedDigest"
        ]
        oracle_filters = {
            "eventKinds": ["movement"],
            "actorIds": [trace["movements"][0]["actorId"]],
            "detailMode": "analysis",
            "visibilityMode": "oracle",
            "speed": 8,
            "selectedResidentId": trace["movements"][0]["actorId"],
        }
        rejected_oracle_session = client.put(
            f"/api/runs/{job.job_id}/replay/session",
            headers=headers,
            json={"positionAt": target, "filters": oracle_filters},
        )
        assert rejected_oracle_session.status_code == 422
        assert rejected_oracle_session.json()["detail"]["code"] == "ORACLE_REPLAY_OPT_IN_REQUIRED"
        oracle_saved = client.put(
            f"/api/runs/{job.job_id}/replay/session?include_oracle=true",
            headers=headers,
            json={"positionAt": target, "filters": oracle_filters},
        )
        assert oracle_saved.status_code == 200
        assert oracle_saved.json()["filters"]["visibilityMode"] == "oracle"
        assert oracle_saved.json()["filters"]["actorIds"] == oracle_filters["actorIds"]
        assert (
            oracle_saved.json()["filters"]["selectedResidentId"]
            == oracle_filters["selectedResidentId"]
        )
        observable_session = client.get(
            f"/api/runs/{job.job_id}/replay/session", headers=headers
        ).json()
        assert observable_session["filters"]["visibilityMode"] == "observable"
        assert "actorIds" not in observable_session["filters"]
        assert "selectedResidentId" not in observable_session["filters"]
        oracle_session = client.get(
            f"/api/runs/{job.job_id}/replay/session?include_oracle=true", headers=headers
        ).json()
        assert oracle_session["filters"]["visibilityMode"] == "oracle"
        assert oracle_session["filters"]["actorIds"] == oracle_filters["actorIds"]
        assert (
            oracle_session["filters"]["selectedResidentId"] == oracle_filters["selectedResidentId"]
        )
        saved = client.put(
            f"/api/runs/{job.job_id}/replay/session",
            headers=headers,
            json={
                "positionAt": target,
                "filters": {
                    "eventKinds": ["movement"],
                    "detailMode": "analysis",
                    "visibilityMode": "observable",
                    "speed": 8,
                },
            },
        ).json()
        assert saved["filters"]["speed"] == 8
        legacy_position = client.put(
            f"/api/runs/{job.job_id}/replay/session",
            headers=headers,
            json={
                "position_at": target,
                "filters": {
                    "eventKinds": ["movement"],
                    "detailMode": "analysis",
                    "visibilityMode": "observable",
                    "speed": 4,
                },
            },
        )
        assert legacy_position.status_code == 200
        assert legacy_position.json()["positionAt"] == target
        assert legacy_position.json()["filters"]["speed"] == 4
        assert (
            client.put(
                f"/api/runs/{job.job_id}/replay/session",
                headers=headers,
                json={"filters": {"speed": 64}},
            ).status_code
            == 422
        )
        assert client.get("/api/runs/missing/replay/session", headers=headers).status_code == 409

        mismatch = client.post(
            f"/api/runs/{job.job_id}/exports",
            headers=headers,
            json={"runId": "another", "formats": ["jsonl"], "roles": ["observable"]},
        )
        assert mismatch.status_code == 422
        exported = client.post(
            f"/api/runs/{job.job_id}/exports",
            headers=headers,
            json={"runId": job.job_id, "formats": ["jsonl"], "roles": ["observable"]},
        )
        assert exported.status_code == 201
        manifest = exported.json()
        export_id = manifest["exportId"]
        assert client.get(f"/api/exports/{export_id}/manifest", headers=headers).status_code == 200
        filename = Path(manifest["files"][0]["relativePath"]).name
        assert (
            client.get(f"/api/exports/{export_id}/files/{filename}", headers=headers).status_code
            == 200
        )
        assert (
            client.get(f"/api/exports/{export_id}/files/missing.jsonl", headers=headers).status_code
            == 404
        )
        zip_res = client.get(f"/api/exports/{export_id}/zip", headers=headers)
        assert zip_res.status_code == 200
        assert zip_res.headers["Content-Type"] == "application/zip"
        with client.stream(
            "GET", f"/api/jobs/{job.job_id}/events?token={token}&after=0"
        ) as response:
            stream = "".join(response.iter_text())
        assert "event: done" in stream


def test_integrity_repair_and_deletion_endpoints(tmp_path: Path) -> None:
    """Everything a researcher needs to reclaim space without leaving the application.

    Deleting export folders in the file manager is the documented way to get disk back, and doing
    it used to leave the workspace in diagnostic mode with no way out from the UI. The endpoints
    here are that way out, plus the deletions that make going to the file manager unnecessary.
    """
    root = tmp_path / "workspace"
    workspace = WorkspaceService.create(root, "Maintenance API")
    home = workspace.create_home("Disposable home")
    job = workspace.create_job("simulation", home_id=home.home_id, seed=7)
    run_directory = workspace.runs_path / job.job_id
    shutil.copytree(
        PROJECT_ROOT / "examples/materialization/mario_rossi_2026_10_30",
        run_directory,
    )
    workspace.import_run_directory(job.job_id, run_directory)
    workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Complete"),
        result_reference=job.job_id,
    )

    app = create_app(root)
    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        export_id = client.post(
            f"/api/runs/{job.job_id}/exports",
            headers=headers,
            json={"runId": job.job_id, "formats": ["jsonl"], "roles": ["observable"]},
        ).json()["exportId"]
        listed = client.get("/api/exports", headers=headers).json()
        assert [item["exportId"] for item in listed] == [export_id]
        assert listed[0]["fileCount"] > 0

        # A file removed from the folder is reported, then reconciled away on request.
        (workspace.exports_path / export_id / "manifest.json").unlink()
        integrity = client.get("/api/workspace/integrity", headers=headers).json()
        assert integrity["diagnosticMode"] is False
        assert [item["relativePath"] for item in integrity["missing"]] == [
            f"exports/{export_id}/manifest.json"
        ]
        repaired = client.post("/api/workspace/repair", headers=headers).json()
        assert repaired["summary"]["artifactsPruned"] == 1
        assert repaired["workspace"]["diagnosticMode"] is False
        assert client.get("/api/workspace/integrity", headers=headers).json()["missing"] == []
        assert client.get("/api/overview", headers=headers).json()["lastRepair"]["details"]

        assert (
            client.delete(f"/api/exports/{export_id}", headers=headers).json()["exportsRemoved"]
            == 1
        )
        assert client.get("/api/exports", headers=headers).json() == []
        assert client.delete(f"/api/jobs/{job.job_id}", headers=headers).json()["runsRemoved"] == 1
        assert client.get("/api/jobs", headers=headers).json() == []
        removed = client.delete(f"/api/homes/{home.home_id}", headers=headers).json()
        assert removed["homesRemoved"] == 1
        assert client.get("/api/homes", headers=headers).json() == []
        assert client.delete(f"/api/homes/{home.home_id}", headers=headers).status_code == 409
        assert client.get("/api/workspace/integrity", headers=headers).json()["missing"] == []


def test_client_disconnect_noise_is_quietened_but_real_failures_are_not() -> None:
    """A finished download ends with the browser dropping the socket.

    Windows' proactor then calls `shutdown()` on a socket that is already gone and asyncio prints a
    full traceback for a request that succeeded. This server tells its operator to read that
    console, so routine noise there is not cosmetic: it is what makes the one traceback that
    matters get scrolled past with the rest.
    """

    class Handle:
        def __init__(self, name: str) -> None:
            self.name = name

        def __repr__(self) -> str:
            return f"<Handle {self.name}(None)>"

    async def exercise() -> list[dict[str, object]]:
        loop = asyncio.get_running_loop()
        reported: list[dict[str, object]] = []
        loop.set_exception_handler(lambda _, context: reported.append(context))
        _quieten_client_disconnects(loop)

        teardown = Handle("_ProactorBasePipeTransport._call_connection_lost")
        loop.call_exception_handler(
            {"exception": ConnectionResetError(10054, "closed by peer"), "handle": teardown}
        )
        assert reported == [], "teardown noise must not reach the console"

        loop.call_exception_handler(
            {"exception": ConnectionResetError(10054, "closed"), "handle": Handle("elsewhere")}
        )
        loop.call_exception_handler({"exception": ValueError("a real defect"), "handle": teardown})
        return reported

    reported = asyncio.run(exercise())

    # The same socket error from another callback, and a real defect from that one, both survive.
    assert len(reported) == 2
    assert isinstance(reported[-1]["exception"], ValueError)


def test_the_plan_is_marked_as_a_recommendation_until_the_researcher_answers(
    tmp_path: Path,
) -> None:
    """The surface that shows the planimetry can tell a proposal from a decision.

    ``planApproval`` is what lets the review screen say "Recommended" over a plan nobody has
    looked at yet, and stop saying it the moment the researcher confirms or edits one.
    """
    app = create_app(tmp_path / "workspace", workspace_name="Plan review")
    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        home_id = client.post("/api/homes", headers=headers, json={"name": "Reviewed home"}).json()[
            "homeId"
        ]
        home = json.loads(
            (PROJECT_ROOT / "examples/environment/mario_monteverde.home.json").read_text(
                encoding="utf-8"
            )
        )

        published = client.put(
            f"/api/homes/{home_id}/home-model", headers=headers, json={"model": home}
        )
        assert published.status_code == 200
        assert published.json()["valid"] is True

        # Publishing through the editor IS the researcher's answer.
        detail = client.get(f"/api/homes/{home_id}", headers=headers).json()
        assert detail["planApproval"] == {
            "home": "researcher",
            "sensor": "recommended",
            "approved": True,
        }

        approved = client.post(f"/api/homes/{home_id}/plan-approval", headers=headers)
        assert approved.status_code == 200
        assert approved.json()["planApproval"]["approved"] is True

        empty = client.post("/api/homes", headers=headers, json={"name": "No plan"}).json()
        refused = client.post(f"/api/homes/{empty['homeId']}/plan-approval", headers=headers)
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "WORKSPACE_OPERATION_FAILED"
