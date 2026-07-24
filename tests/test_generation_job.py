from __future__ import annotations

import json
import types
import urllib.error

from fastapi.testclient import TestClient

from smart_home_sim.application.generation_job import generation_run_dir, run_generation_job
from smart_home_sim.application.jobs import JobManager
from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.domain.application import JobStatus
from smart_home_sim.hybrid_planning.lmstudio import LMStudioClient, LMStudioConfig
from smart_home_sim.web import create_app


def _h(label: str, kind: str, frequency: str, band: str) -> dict[str, str]:
    return {"label": label, "kind": kind, "frequency": frequency, "time_band": band}


_PERSONA = json.dumps(
    {
        "name": "Elena Bruni",
        "age": 72,
        "sex": "F",
        "occupation": "retired teacher",
        "household": "lives alone",
        "health": ["arthritis"],
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
        if "invent one coherent person" in text:
            reply = _PERSONA
        elif "daily-habit portfolio" in text:
            reply = _HABITS
        else:
            reply = "{}"
        return json.dumps({"choices": [{"message": {"content": reply}, "finish_reason": "stop"}]})

    return LMStudioClient(LMStudioConfig(model="qwen3.5-9b"), transport=transport)


def _raising_client(error: Exception) -> LMStudioClient:
    def transport(url: str, body: bytes, timeout: float) -> str:
        raise error

    return LMStudioClient(transport=transport)


def _generation_request() -> dict[str, object]:
    return {"brief": "an elderly woman", "startDate": "2026-08-03", "months": 1, "days": 2}


def _token(client: TestClient) -> str:
    return client.get("/api/session").json()["token"]


def test_run_generation_job_completes(tmp_path) -> None:
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    job = workspace.create_job("generation", request=_generation_request())
    run_generation_job(workspace, job.job_id, client=_pipeline_client())
    record = workspace.get_job(job.job_id)
    assert record.status is JobStatus.completed
    run_dir = generation_run_dir(workspace, job.job_id)
    assert (run_dir / "batch-manifest.json").exists()
    assert (run_dir / "persona.json").exists()
    assert (run_dir / "planned-habit-trace.json").exists()
    # generation output must NOT land under runs/ (reconcile would flag it as orphan)
    assert not (workspace.runs_path / job.job_id).exists()
    assert workspace.reconcile() == []


def test_run_generation_job_fails(tmp_path) -> None:
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    job = workspace.create_job("generation", request=_generation_request())
    run_generation_job(workspace, job.job_id, client=_raising_client(urllib.error.URLError("down")))
    assert workspace.get_job(job.job_id).status is JobStatus.failed


def test_run_generation_job_interrupted(tmp_path) -> None:
    workspace = WorkspaceService.create(tmp_path / "ws", "gen")
    job = workspace.create_job("generation", request=_generation_request())
    run_generation_job(workspace, job.job_id, client=_raising_client(InterruptedError()))
    assert workspace.get_job(job.job_id).status is JobStatus.cancelled


def test_start_generation_creates_job_without_spawning(monkeypatch, tmp_path) -> None:
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
    job = manager.start_generation("an elderly woman", start_date="2026-08-03", months=3, seed=7)
    assert job.kind == "generation"
    request = workspace.job_request(job.job_id)
    assert request["brief"] == "an elderly woman"
    assert request["startDate"] == "2026-08-03"
    assert request["months"] == 3


def test_start_generation_endpoint(monkeypatch, tmp_path) -> None:
    app = create_app(tmp_path / "ws")
    workspace = app.state.workspace
    monkeypatch.setattr(
        app.state.jobs,
        "start_generation",
        lambda *args, **kwargs: workspace.create_job("generation", request={}),
    )
    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        response = client.post(
            "/api/generation",
            headers=headers,
            json={"brief": "an elderly woman", "start_date": "2026-08-03", "months": 3},
        )
        assert response.status_code == 202
        assert response.json()["kind"] == "generation"
        bad = client.post(
            "/api/generation",
            headers=headers,
            json={"brief": "x", "start_date": "not-a-date"},
        )
        assert bad.status_code == 422


def test_generation_artifact_endpoint(tmp_path) -> None:
    root = tmp_path / "ws"
    workspace = WorkspaceService.create(root, "gen")
    job = workspace.create_job("generation", request={})
    run_dir = generation_run_dir(workspace, job.job_id)
    run_dir.mkdir(parents=True)
    (run_dir / "persona.json").write_text('{"personaId": "elena"}', encoding="utf-8")

    app = create_app(root)
    with TestClient(app) as client:
        headers = {"X-Workspace-Token": _token(client)}
        ok = client.get(f"/api/generation/{job.job_id}/artifact/persona.json", headers=headers)
        assert ok.status_code == 200
        assert ok.json()["personaId"] == "elena"
        unknown = client.get(f"/api/generation/{job.job_id}/artifact/secrets.json", headers=headers)
        assert unknown.status_code == 404
        missing = client.get(
            f"/api/generation/{job.job_id}/artifact/batch-manifest.json", headers=headers
        )
        assert missing.status_code == 404
