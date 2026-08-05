from __future__ import annotations

import asyncio
import faulthandler
import json
import logging
import os
import secrets
import tempfile
import time
import traceback
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator
from starlette.background import BackgroundTask

from smart_home_sim.application.export import ExportService
from smart_home_sim.application.generation_ingest import (
    GenerationIngestError,
    generation_job_for_home,
    horizon_revision,
    ingest_generation,
)
from smart_home_sim.application.generation_paths import GENERATION_ARTIFACTS, generation_run_dir
from smart_home_sim.application.jobs import JobManager
from smart_home_sim.application.replay import ReplayService
from smart_home_sim.application.service import ApplicationService
from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import ExportRequest, JobStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HomeCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class AuthoringImport(ApiModel):
    scenario: dict[str, Any]
    personal_process_package: dict[str, Any]


class MaterializationStart(ApiModel):
    scenario_artifact_id: str = Field(min_length=1)
    behavior_artifact_id: str = Field(min_length=1)
    seed: int | None = None
    home_policy: dict[str, Any] = Field(default_factory=dict)
    sensor_policy: dict[str, Any] = Field(default_factory=dict)


class GenerationStart(ApiModel):
    brief: str = Field(min_length=1, max_length=2000)
    start_date: str = Field(min_length=1)
    months: int = Field(default=1, ge=1)
    use_llm_days: bool = False
    use_llm_package: bool = False
    model: str | None = None
    base_url: str | None = None
    temperature: float = Field(default=0.6, ge=0)
    seed: int | None = None

    @field_validator("start_date")
    @classmethod
    def check_start_date(cls, value: str) -> str:
        try:
            _date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("startDate must be YYYY-MM-DD") from error
        return value


class RevealRequest(ApiModel):
    kind: Literal["workspace", "exports", "runs", "export", "run"]
    identifier: str = Field(default="", max_length=120)


class ModelPublish(ApiModel):
    model: dict[str, Any]


class SettingUpdate(ApiModel):
    value: JsonValue


class ReplaySessionUpdate(ApiModel):
    position_at: Annotated[AwareDatetime, Field(strict=False)] | None = None
    filters: dict[str, JsonValue] = Field(default_factory=dict)


class ExportCreate(ExportRequest):
    model_config = ConfigDict(strict=False)


log = logging.getLogger("smart_home_sim.web")


@dataclass
class _Operation:
    """One request the server is currently holding, and how far into it the handler has got."""

    method: str
    path: str
    started: float
    stage: str = "starting"


def _crash_log_path(workspace_root: Path) -> Path:
    return workspace_root / "server-errors.log"


def _append_crash_log(workspace_root: Path, entry: str) -> None:
    """Best effort: a failure to record a failure must not replace the original one."""
    try:
        path = _crash_log_path(workspace_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n===== {datetime.now(UTC).isoformat()} =====\n{entry}")
    except OSError:  # pragma: no cover - the reply and the console still carry the error
        log.warning("could not write the crash log", exc_info=True)


def _enable_fault_traces(workspace_root: Path) -> None:
    """Make a hard interpreter abort leave a Python traceback behind.

    A stack overflow or a C-level `abort()` kills the process without unwinding, so no exception
    handler runs and both the console and the reply stay empty — the operator sees a request that
    never returns. `faulthandler` writes the stacks of every thread at that moment straight to a
    file descriptor, which is the only thing that survives that kind of exit.
    """
    try:
        path = _crash_log_path(workspace_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Deliberately never closed: it has to outlive normal shutdown to catch a crash at exit.
        handle = path.open("a", encoding="utf-8")
        faulthandler.enable(file=handle, all_threads=True)
    except (OSError, ValueError):  # pragma: no cover - stderr remains the fallback
        faulthandler.enable(all_threads=True)


def _quieten_client_disconnects(loop: asyncio.AbstractEventLoop) -> None:
    """Stop Windows' proactor from printing a traceback for a connection the client already closed.

    Downloading a 49 MB archive ends with the browser dropping the socket as soon as it has the
    bytes. The proactor event loop then calls `shutdown()` on a socket that is already gone and
    raises inside `_call_connection_lost`, which asyncio reports as an unhandled callback
    exception — a full traceback in the console for a request that succeeded.

    It matters because this server tells its operator to read that console: a crash log worth
    checking is worth keeping free of routine noise, or the one traceback that means something gets
    scrolled past with the others. Narrow on purpose — only a socket error, only from that
    callback; everything else still goes through asyncio's own reporting.
    """
    default = loop.get_exception_handler()

    def handler(active_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exception = context.get("exception")
        source = repr(context.get("handle", ""))
        if isinstance(exception, OSError) and "_call_connection_lost" in source:
            log.debug("client closed the connection during teardown: %s", exception)
            return
        if default is not None:
            default(active_loop, context)
        else:
            active_loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


def _static_root() -> Path | None:
    packaged = Path(__file__).parent / "static"
    source = Path(__file__).parents[3] / "frontend" / "dist"
    for candidate in (packaged, source):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def create_app(workspace_root: Path, *, workspace_name: str = "Research workspace") -> FastAPI:
    workspace_root = workspace_root.resolve()
    _enable_fault_traces(workspace_root)
    if (workspace_root / "workspace.sqlite3").exists():
        workspace = WorkspaceService.open(workspace_root)
    else:
        workspace = WorkspaceService.create(workspace_root, workspace_name)
    application = ApplicationService(workspace)
    jobs = JobManager(workspace)
    replay = ReplayService(workspace)
    exports = ExportService(workspace)
    session_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _quieten_client_disconnects(asyncio.get_running_loop())
        yield
        jobs.shutdown()

    app = FastAPI(
        title="Smart Home Simulator Local Application API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.workspace = workspace
    app.state.jobs = jobs
    app.state.session_token = session_token

    @app.exception_handler(WorkspaceError)
    async def workspace_error(_: Request, error: WorkspaceError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "WORKSPACE_OPERATION_FAILED",
                    "message": str(error),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, error: Exception) -> JSONResponse:
        """Turn a crash into one readable sentence in the browser and a traceback on disk.

        Without this the browser gets an empty 500 and the operator gets nothing they can act on:
        the console window scrolls away, and closing it takes the traceback with it. The reply
        carries the exception type and message rather than the traceback, which stays in the log.
        """
        reference = secrets.token_hex(4)
        log.exception("unhandled error %s on %s %s", reference, request.method, request.url.path)
        _append_crash_log(
            workspace_root,
            f"{reference} {request.method} {request.url.path}\n"
            + "".join(traceback.format_exception(error)),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "UNHANDLED_SERVER_ERROR",
                    "message": (
                        f"{type(error).__name__}: {error}. The full traceback was written to "
                        f"{_crash_log_path(workspace_root)} under reference {reference}."
                    ),
                    "reference": reference,
                }
            },
        )

    # What the server is busy with right now, keyed by an id the browser also holds. A long import
    # is indistinguishable from a dead one from the outside, and that ambiguity is the whole
    # problem: the operator is left watching a spinner with no way to tell which it is.
    in_flight: dict[str, _Operation] = {}

    @app.middleware("http")
    async def track_in_flight(request: Request, call_next: Any) -> Any:
        operation = request.headers.get("X-Operation-Id")
        if operation is None:
            return await call_next(request)
        in_flight[operation] = _Operation(request.method, request.url.path, time.monotonic())
        try:
            return await call_next(request)
        finally:
            in_flight.pop(operation, None)

    def stage_reporter(request: Request) -> Callable[[str], None]:
        """Let a long handler name the step it is on, for whoever polls `/api/health`."""
        running = in_flight.get(request.headers.get("X-Operation-Id") or "")

        def report(name: str) -> None:
            if running is not None:
                running.stage = name

        return report

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Any:
        client = request.client.host if request.client else ""
        if client not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "LOOPBACK_REQUIRED", "message": "Local access only"}},
            )
        return await call_next(request)

    def authorize(
        x_workspace_token: Annotated[str | None, Header()] = None,
        token: Annotated[str | None, Query()] = None,
    ) -> None:
        if not secrets.compare_digest(x_workspace_token or token or "", session_token):
            raise HTTPException(
                status_code=401,
                detail={"code": "SESSION_TOKEN_INVALID", "message": "Invalid local session"},
            )

    secured = Depends(authorize)

    @app.get("/api/health")
    def health(operation: str | None = None) -> dict[str, Any]:
        """Is the server alive, and is it still working on ``operation``?

        Unauthenticated and free of any workspace access on purpose: this is what a client polls
        while a request it has already sent is outstanding, so it has to answer even when the
        thing it is reporting on is monopolising the application.
        """
        running = in_flight.get(operation or "")
        return {
            "status": "ok",
            "operation": None
            if running is None
            else {
                "operationId": operation,
                "method": running.method,
                "path": running.path,
                "stage": running.stage,
                "elapsedSeconds": round(time.monotonic() - running.started, 1),
            },
            "inFlight": len(in_flight),
        }

    @app.get("/api/session")
    def session() -> dict[str, Any]:
        return {
            "token": session_token,
            "apiVersion": "1.0.0",
            "workspace": workspace.summary().model_dump(mode="json", by_alias=True),
        }

    @app.get("/api/overview", dependencies=[secured])
    def overview() -> dict[str, Any]:
        return {
            "workspace": workspace.summary().model_dump(mode="json", by_alias=True),
            "homes": [
                item.model_dump(mode="json", by_alias=True) for item in workspace.list_homes()
            ],
            "residents": [
                item.model_dump(mode="json", by_alias=True) for item in workspace.list_residents()
            ],
            "jobs": [
                item.model_dump(mode="json", by_alias=True)
                for item in workspace.list_jobs(limit=50)
            ],
        }

    @app.get("/api/workspace/manifest", dependencies=[secured])
    def workspace_manifest() -> dict[str, Any]:
        return workspace.manifest().model_dump(mode="json", by_alias=True)

    @app.get("/api/settings/{key}", dependencies=[secured])
    def get_setting(key: str) -> dict[str, Any]:
        return {"key": key, "value": workspace.get_setting(key)}

    @app.put("/api/settings/{key}", dependencies=[secured])
    def set_setting(key: str, request: SettingUpdate) -> dict[str, Any]:
        return {"key": key, "value": workspace.set_setting(key, request.value)}

    @app.get("/api/workspace/archive", dependencies=[secured])
    def workspace_archive() -> FileResponse:
        handle, name = tempfile.mkstemp(prefix="smart-home-workspace-", suffix=".shw")
        # mkstemp reserves a unique name; close its descriptor before the
        # atomic archive writer replaces that path.
        os.close(handle)
        Path(name).unlink(missing_ok=True)
        archive = workspace.export_archive(Path(name))
        return FileResponse(
            archive,
            media_type="application/vnd.smart-home-workspace+zip",
            filename=f"{workspace.summary().name}.shw",
            background=BackgroundTask(archive.unlink, missing_ok=True),
        )

    @app.get("/api/homes", dependencies=[secured])
    def list_homes(query: str = "") -> list[dict[str, Any]]:
        return [item.model_dump(mode="json", by_alias=True) for item in workspace.list_homes(query)]

    @app.post("/api/homes", status_code=201, dependencies=[secured])
    def create_home(request: HomeCreate) -> dict[str, Any]:
        return workspace.create_home(request.name, request.description).model_dump(
            mode="json", by_alias=True
        )

    @app.get("/api/homes/{home_id}", dependencies=[secured])
    def home_detail(home_id: str) -> dict[str, Any]:
        return {
            "home": workspace.get_home(home_id).model_dump(mode="json", by_alias=True),
            "residents": [
                item.model_dump(mode="json", by_alias=True)
                for item in workspace.list_residents(home_id)
            ],
            "models": application.current_models(home_id),
            "issues": [
                item.model_dump(mode="json", by_alias=True)
                for item in workspace.list_validation_issues(home_id)
            ],
            "jobs": [
                item.model_dump(mode="json", by_alias=True)
                for item in workspace.list_jobs(home_id=home_id)
            ],
            "generation": horizon_revision(workspace, home_id),
        }

    @app.post("/api/homes/{home_id}/authoring", dependencies=[secured])
    def import_authoring(home_id: str, request: AuthoringImport) -> dict[str, Any]:
        return application.import_authoring(
            home_id, request.scenario, request.personal_process_package
        )

    @app.post("/api/homes/{home_id}/authoring-bundle", dependencies=[secured])
    def import_authoring_bundle(home_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return application.import_authoring_bundle(home_id, request)

    @app.post("/api/homes/{home_id}/horizon-outline", dependencies=[secured])
    def import_horizon_outline(
        home_id: str, request: dict[str, Any], http_request: Request, seed: int = 0
    ) -> dict[str, Any]:
        return application.import_horizon_outline(
            home_id, request, seed=seed, on_stage=stage_reporter(http_request)
        )

    @app.put("/api/homes/{home_id}/home-model", dependencies=[secured])
    def publish_home(home_id: str, request: ModelPublish) -> dict[str, Any]:
        return application.publish_home(home_id, request.model)

    @app.put("/api/homes/{home_id}/sensor-model", dependencies=[secured])
    def publish_sensor(home_id: str, request: ModelPublish) -> dict[str, Any]:
        return application.publish_sensor(home_id, request.model)

    @app.post("/api/homes/{home_id}/runs", status_code=202, dependencies=[secured])
    def start_run(home_id: str, request: MaterializationStart) -> dict[str, Any]:
        # A home created from a local generation carries a horizon of independently compiled days;
        # running it merges those days into one run instead of materializing a single scenario.
        if generation_job_for_home(workspace, home_id) is not None:
            return jobs.start_horizon_run(home_id).model_dump(mode="json", by_alias=True)
        return jobs.start_materialization(
            home_id,
            request.scenario_artifact_id,
            request.behavior_artifact_id,
            seed=request.seed,
            home_policy=request.home_policy,
            sensor_policy=request.sensor_policy,
        ).model_dump(mode="json", by_alias=True)

    @app.post("/api/generation", status_code=202, dependencies=[secured])
    def start_generation(request: GenerationStart) -> dict[str, Any]:
        return jobs.start_generation(
            request.brief,
            start_date=request.start_date,
            months=request.months,
            use_llm_days=request.use_llm_days,
            use_llm_package=request.use_llm_package,
            model=request.model,
            base_url=request.base_url,
            temperature=request.temperature,
            seed=request.seed,
        ).model_dump(mode="json", by_alias=True)

    @app.get("/api/generations", dependencies=[secured])
    def list_generations(limit: int = 100) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json", by_alias=True)
            for item in workspace.list_jobs(limit=limit)
            if item.kind == "generation"
        ]

    @app.post("/api/generation/{job_id}/publish", status_code=201, dependencies=[secured])
    def publish_generation(job_id: str) -> dict[str, Any]:
        """Publish an earlier generation as a home input (generations now do this themselves)."""
        workspace.get_job(job_id)
        try:
            result = ingest_generation(workspace, job_id)
        except GenerationIngestError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "GENERATION_NOT_PUBLISHABLE", "message": str(error)},
            ) from error
        return {
            "homeId": result.home_id,
            "residentDisplayName": result.resident_display_name,
            "dayCount": result.day_count,
        }

    @app.get("/api/generation/{job_id}/artifact/{name}", dependencies=[secured])
    def generation_artifact(job_id: str, name: str) -> FileResponse:
        if name not in GENERATION_ARTIFACTS:
            raise HTTPException(status_code=404, detail="Unknown generation artifact")
        run_dir = generation_run_dir(workspace, job_id).resolve()
        path = (run_dir / name).resolve()
        if run_dir not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="Generation artifact not found")
        return FileResponse(path, media_type="application/json", filename=name)

    @app.get("/api/jobs", dependencies=[secured])
    def list_jobs(home_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json", by_alias=True)
            for item in workspace.list_jobs(home_id=home_id, limit=limit)
        ]

    @app.get("/api/jobs/{job_id}", dependencies=[secured])
    def job_detail(job_id: str) -> dict[str, Any]:
        return {
            "job": workspace.get_job(job_id).model_dump(mode="json", by_alias=True),
            "events": [
                item.model_dump(mode="json", by_alias=True)
                for item in workspace.list_events(job_id)
            ],
            "artifacts": {
                role: item.model_dump(mode="json", by_alias=True)
                for role, item in workspace.run_artifacts(job_id).items()
            },
        }

    @app.post("/api/jobs/{job_id}/cancel", dependencies=[secured])
    def cancel_job(job_id: str) -> dict[str, Any]:
        return jobs.cancel(job_id).model_dump(mode="json", by_alias=True)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, token: str, after: int = 0) -> StreamingResponse:
        authorize(token=token)

        async def stream() -> AsyncIterator[str]:
            sequence = max(after, 0)
            idle = 0
            while True:
                events = workspace.list_events(job_id, sequence)
                if events:
                    idle = 0
                    for event in events:
                        sequence = event.sequence
                        yield (
                            f"id: {event.sequence}\n"
                            f"event: {event.event_type}\n"
                            f"data: {event.model_dump_json(by_alias=True)}\n\n"
                        )
                else:
                    idle += 1
                    if idle % 20 == 0:
                        yield ": heartbeat\n\n"
                status = workspace.get_job(job_id).status
                if status in {
                    JobStatus.completed,
                    JobStatus.failed,
                    JobStatus.cancelled,
                    JobStatus.interrupted,
                } and not workspace.list_events(job_id, sequence):
                    yield f"event: done\ndata: {json.dumps({'status': status.value})}\n\n"
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/diary", dependencies=[secured])
    def diary(
        run_id: str,
        actor_id: str | None = None,
        status: str | None = None,
        query: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        entries, total = replay.diary(
            run_id,
            actor_id=actor_id,
            status=status,
            query=query,
            offset=offset,
            limit=limit,
        )
        return {
            "items": [item.model_dump(mode="json", by_alias=True) for item in entries],
            "total": total,
        }

    @app.get("/api/runs/{run_id}/observations", dependencies=[secured])
    def observations(
        run_id: str,
        include_oracle: bool = False,
        sensor_id: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        records, total = replay.observations(
            run_id,
            include_oracle=include_oracle,
            sensor_id=sensor_id,
            offset=offset,
            limit=limit,
        )
        return {
            "items": [item.model_dump(mode="json", by_alias=True) for item in records],
            "total": total,
            "mode": "oracle" if include_oracle else "observable",
        }

    @app.get("/api/runs/{run_id}/timeline", dependencies=[secured])
    def timeline(run_id: str, limit: int = 2000) -> list[dict[str, Any]]:
        return replay.timeline(run_id, limit=limit)

    @app.get("/api/runs/{run_id}/models", dependencies=[secured])
    def run_models(run_id: str) -> dict[str, Any]:
        artifacts = workspace.run_artifacts(run_id)
        result: dict[str, Any] = {}
        for role, key in (("home_model", "homeModel"), ("sensor_model", "sensorModel")):
            artifact = artifacts.get(role)
            if artifact is not None:
                result[key] = json.loads(workspace.read_artifact(artifact.artifact_id))
        return result

    @app.post("/api/runs/{run_id}/replay/verify", dependencies=[secured])
    def verify_replay(run_id: str) -> dict[str, Any]:
        return replay.verify(run_id).model_dump(mode="json", by_alias=True)

    @app.get("/api/runs/{run_id}/replay/session", dependencies=[secured])
    def replay_session(run_id: str) -> dict[str, Any]:
        return workspace.replay_session(run_id)

    @app.put("/api/runs/{run_id}/replay/session", dependencies=[secured])
    def save_replay_session(run_id: str, request: ReplaySessionUpdate) -> dict[str, Any]:
        return workspace.save_replay_session(
            run_id,
            position_at=request.position_at,
            filters=request.filters,
        )

    @app.post("/api/runs/{run_id}/exports", status_code=201, dependencies=[secured])
    def create_export(run_id: str, request: ExportCreate) -> dict[str, Any]:
        if request.run_id != run_id:
            raise HTTPException(
                status_code=422,
                detail={"code": "RUN_ID_MISMATCH", "message": "Path and body run IDs differ"},
            )
        return exports.export(request).model_dump(mode="json", by_alias=True)

    @app.get("/api/exports/{export_id}/manifest", dependencies=[secured])
    def export_manifest(export_id: str) -> dict[str, Any]:
        return exports.verify_manifest(export_id).model_dump(mode="json", by_alias=True)

    @app.get("/api/exports/{export_id}/files/{filename}", dependencies=[secured])
    def export_file(export_id: str, filename: str) -> FileResponse:
        manifest = exports.verify_manifest(export_id)
        entry = next(
            (item for item in manifest.files if Path(item.relative_path).name == filename), None
        )
        if entry is None:
            raise HTTPException(status_code=404, detail="Unknown export file")
        path = (workspace.exports_path / entry.relative_path).resolve()
        return FileResponse(path, media_type=entry.media_type, filename=filename)

    @app.get("/api/exports/{export_id}/zip", dependencies=[secured])
    def export_zip(export_id: str) -> FileResponse:
        archive_path = exports.archive_export(export_id)
        return FileResponse(archive_path, media_type="application/zip", filename=f"{export_id}.zip")

    static_root = _static_root()
    if static_root is not None:
        assets = static_root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str) -> FileResponse:
            candidate = (static_root / path).resolve()
            if path and candidate.is_file() and static_root.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static_root / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def frontend_missing() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "FRONTEND_NOT_BUILT",
                        "message": "Build frontend assets with 'npm run build' in frontend/.",
                    }
                },
            )

    return app
