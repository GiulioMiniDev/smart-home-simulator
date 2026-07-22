from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import JobProgress, JobStatus
from smart_home_sim.web import create_app

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
            f"/api/homes/{home_id}/authoring",
            headers=headers,
            json={
                "scenario": payload["scenario"],
                "personal_process_package": payload["personalProcessPackage"],
            },
        )
        assert imported.status_code == 200
        assert imported.json()["valid"] is True
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


def test_api_rejects_non_loopback_client(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspace", workspace_name="Loopback")
    with TestClient(app, client=("192.0.2.10", 5000)) as client:
        response = client.get("/api/session")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOOPBACK_REQUIRED"


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

    app = create_app(root)
    with TestClient(app) as client:
        token = _token(client)
        headers = {"X-Workspace-Token": token}
        assert client.get("/").status_code == 200
        assert client.get("/simulations/client-route").status_code == 200
        assert client.get("/api/jobs", headers=headers).json()[0]["status"] == "completed"
        detail = client.get(f"/api/jobs/{job.job_id}", headers=headers).json()
        assert "execution_trace" in detail["artifacts"]
        assert client.get(f"/api/runs/{job.job_id}/diary", headers=headers).json()["total"]
        observable = client.get(f"/api/runs/{job.job_id}/observations", headers=headers).json()
        assert observable["mode"] == "observable"
        oracle = client.get(
            f"/api/runs/{job.job_id}/observations?include_oracle=true", headers=headers
        ).json()
        assert oracle["mode"] == "oracle"
        assert client.get(f"/api/runs/{job.job_id}/timeline?limit=5", headers=headers).json()
        models = client.get(f"/api/runs/{job.job_id}/models", headers=headers).json()
        assert {"homeModel", "sensorModel"} <= set(models)
        verification = client.post(f"/api/runs/{job.job_id}/replay/verify", headers=headers).json()
        assert verification["matches"] is True
        assert client.get(f"/api/runs/{job.job_id}/replay/session", headers=headers).json()[
            "verifiedDigest"
        ]
        saved = client.put(
            f"/api/runs/{job.job_id}/replay/session",
            headers=headers,
            json={"position_at": "2026-10-30T08:00:00Z", "filters": {"actorId": "mario"}},
        ).json()
        assert saved["filters"] == {"actorId": "mario"}

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
        with client.stream(
            "GET", f"/api/jobs/{job.job_id}/events?token={token}&after=0"
        ) as response:
            stream = "".join(response.iter_text())
        assert "event: done" in stream
