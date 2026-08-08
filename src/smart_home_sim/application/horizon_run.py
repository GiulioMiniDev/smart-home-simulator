"""Simulate a generated home's whole horizon and publish it as ONE run of that home.

Days are executed independently — the compiler and the engine only scale that way — but the
researcher never sees a pile of per-day files: the per-day traces, observable logs and oracle
mappings are merged into a single execution trace, a single sensor log and a single oracle mapping,
written into ``runs/<job_id>/`` under exactly the names an ordinary materialization run publishes.
That is what makes the rest of the application work unchanged on a generated horizon: the diary,
the observation table, the replay plan and the complete (never day-sectioned) dataset export.

Merged provenance is explicit rather than pretended: the trace carries a composite
``sourceBundleSha256`` over the ordered per-day bundle digests, its ``semanticDigest`` is recomputed
with the engine's own formula over the merged content, and ``horizon-manifest.json`` records each
contributing day with its own bundle digest and trace digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from smart_home_sim.application.generation_paths import generation_run_dir
from smart_home_sim.application.plan_approval import approved_home_model, approved_sensor_model
from smart_home_sim.application.workspace import WorkspaceService
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.application import JobProgress, JobStatus
from smart_home_sim.domain.batch import SimulationBatchManifest
from smart_home_sim.domain.environment import HomeModel, SimulationBundle
from smart_home_sim.domain.execution import ExecutionTrace
from smart_home_sim.domain.sensors import (
    ObservableSensorLog,
    OracleMapping,
    OracleObservationLink,
    SensorModel,
)
from smart_home_sim.environment import rebind_bundle_home
from smart_home_sim.materialization import bind_sensor_model, deploy_sensors
from smart_home_sim.materialization.service import load_sensor_policy
from smart_home_sim.sensors import project_sensors
from smart_home_sim.simulation import simulate_bundle, trace_semantic_digest

_SENSOR_ORDER = {"pir": 0, "contact": 1, "temperature": 2}


def _merge_sensor(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Combine two deployments of the same sensor, unioning a temperature sensor's heat sources."""
    if existing.get("sensorType") != "temperature":
        return existing
    sources = {item["entityId"]: item for item in existing.get("sources", [])}
    for item in candidate.get("sources", []):
        sources.setdefault(item["entityId"], item)
    merged = dict(existing)
    merged["sources"] = [
        sources[entity_id]
        for entity_id in sorted(sources, key=lambda name: (name.startswith("service_"), name))
    ]
    return merged


def horizon_sensor_field(
    day_models: list[tuple[str, SensorModel]],
    *,
    source_bundle_id: str,
    source_bundle_sha256: str,
) -> tuple[SensorModel, dict[str, list[str]]]:
    """The single sensor field of a whole horizon, plus which days first introduced each sensor.

    ``deploy_sensors`` derives contact sensors from the actions of the bundle it is given, and a
    temperature sensor's heat sources from the entities that bundle activates. Over a horizon of
    independently bundled days that yields a DIFFERENT field per day — physically wrong, because a
    home's sensors are installed once and then observe whatever happens. So the horizon's field is
    the union over its days: every sensor the home ever needs, present on every day. A day that
    never touches a given door simply produces no contact events for it, which is exactly what a
    real installation records.
    """
    definitions: dict[str, dict[str, Any]] = {}
    introduced_by: dict[str, list[str]] = {}
    reference: SensorModel | None = None
    for run_id, model in day_models:
        reference = reference or model
        for sensor in model.sensors:
            definition = sensor.model_dump(mode="json", by_alias=True)
            sensor_id = definition["sensorId"]
            if sensor_id in definitions:
                definitions[sensor_id] = _merge_sensor(definitions[sensor_id], definition)
            else:
                definitions[sensor_id] = definition
                introduced_by.setdefault(run_id, []).append(sensor_id)
    if reference is None:
        raise HorizonRunError("the horizon has no day to deploy sensors from")
    payload = json.loads(reference.model_dump_json(by_alias=True))
    payload["sourceBundleId"] = source_bundle_id
    payload["sourceBundleSha256"] = source_bundle_sha256
    payload["sensors"] = sorted(
        definitions.values(),
        key=lambda item: (_SENSOR_ORDER[item["sensorType"]], item["sensorId"]),
    )
    return SensorModel.model_validate_json(json.dumps(payload)), introduced_by


def _rebound_to_plan(bundle: SimulationBundle, home: HomeModel | None) -> SimulationBundle:
    """One generated day, re-gated against the plan the researcher approved.

    The day's bundle was assembled during generation around the recommended home. If the researcher
    has since moved a wall or a wardrobe, simulating that bundle would execute a home nobody
    approved — with different walking distances and different reachability. Rebinding re-runs the
    home-dependent M4 gates on the approved plan; a plan that fails them stops the run rather than
    silently reverting to the recommendation.
    """
    if home is None:
        return bundle
    result = rebind_bundle_home(bundle, home)
    if result.bundle is None:
        messages = " · ".join(issue.message for issue in result.report.issues[:3])
        raise HorizonRunError(f"the approved plan does not bind to this horizon: {messages}")
    return result.bundle


TRACE_COLLECTIONS: tuple[str, ...] = (
    "activityExecutions",
    "actionExecutions",
    "movements",
    "stateTransitions",
    "resourceEvents",
    "runtimeEvents",
    "planDeviations",
    "dailySummaries",
)


class HorizonRunError(RuntimeError):
    """The generated horizon could not be simulated into one publishable run."""


def _write_json(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


class _Accumulator:
    """Collects per-day results in wire (by-alias JSON) form and merges them once at the end."""

    def __init__(self, generation_job_id: str) -> None:
        self.generation_job_id = generation_job_id
        self.trace_parts: dict[str, list[Any]] = {key: [] for key in TRACE_COLLECTIONS}
        self.records: list[dict[str, Any]] = []
        self.links: list[dict[str, Any]] = []
        self.days: list[dict[str, Any]] = []
        self.seen_observations: set[str] = set()
        self.first_trace: dict[str, Any] | None = None
        self.last_trace: dict[str, Any] | None = None

    def add(
        self, run_id: str, trace: ExecutionTrace, log: ObservableSensorLog, oracle: OracleMapping
    ) -> None:
        payload = json.loads(trace.model_dump_json(by_alias=True))
        for key in TRACE_COLLECTIONS:
            self.trace_parts[key].extend(payload[key])
        for record in json.loads(log.model_dump_json(by_alias=True))["records"]:
            if record["observationId"] in self.seen_observations:
                raise HorizonRunError(
                    f"day '{run_id}' repeats observation '{record['observationId']}'"
                )
            self.seen_observations.add(record["observationId"])
            self.records.append(record)
        self.links.extend(json.loads(oracle.model_dump_json(by_alias=True))["links"])
        self.days.append(
            {
                "runId": run_id,
                "startedAt": payload["startedAt"],
                "endedAt": payload["endedAt"],
                "sourceBundleId": payload["sourceBundleId"],
                "sourceBundleSha256": payload["sourceBundleSha256"],
                "traceSemanticDigest": payload["semanticDigest"],
                "observationCount": len(log.records),
                "activityCount": len(trace.activity_executions),
            }
        )
        self.first_trace = self.first_trace or payload
        self.last_trace = payload

    def merged_trace(self) -> ExecutionTrace:
        if self.first_trace is None or self.last_trace is None:
            raise HorizonRunError("no day produced an execution trace")
        composite = hashlib.sha256(
            ":".join(day["sourceBundleSha256"] for day in self.days).encode("utf-8")
        ).hexdigest()
        payload: dict[str, Any] = {
            "schemaVersion": "1.0.0",
            "documentType": "execution_trace",
            "traceId": f"trace_{composite[:16]}",
            "sourceBundleId": f"horizon_{self.generation_job_id}",
            "sourceBundleSha256": composite,
            "seed": self.first_trace["seed"],
            "engine": self.first_trace["engine"],
            "startedAt": self.first_trace["startedAt"],
            "endedAt": self.last_trace["endedAt"],
            "status": "completed",
            "finalState": self.last_trace["finalState"],
            **self.trace_parts,
        }
        payload["semanticDigest"] = trace_semantic_digest(payload)
        return ExecutionTrace.model_validate_json(json.dumps(payload))

    def merged_log(self, sensor_model: SensorModel, trace: ExecutionTrace) -> ObservableSensorLog:
        records = sorted(
            self.records,
            key=lambda item: (item["observedAt"], item["sensorId"], item["observationId"]),
        )
        digest = canonical_sha256(
            {
                "sensorModelId": sensor_model.sensor_model_id,
                "sensorModelVersion": sensor_model.sensor_model_version,
                "records": records,
            }
        )
        last = datetime.fromisoformat(records[-1]["observedAt"]) if records else trace.ended_at
        return ObservableSensorLog.model_validate_json(
            json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "documentType": "observable_sensor_log",
                    "logId": f"sensor_log_{digest[:16]}",
                    "sensorModelId": sensor_model.sensor_model_id,
                    "sensorModelVersion": sensor_model.sensor_model_version,
                    "startedAt": trace.started_at.isoformat(),
                    "endedAt": max(trace.ended_at, last).isoformat(),
                    "records": records,
                    "semanticDigest": digest,
                }
            )
        )

    def merged_oracle(self, log: ObservableSensorLog, trace: ExecutionTrace) -> OracleMapping:
        order = {record.observation_id: index for index, record in enumerate(log.records)}
        links = sorted(self.links, key=lambda item: order[item["observationId"]])
        # OracleMapping derives its identity from the field-name (not alias) form of its links.
        digest = canonical_sha256(
            [
                OracleObservationLink.model_validate_json(json.dumps(item)).model_dump(mode="json")
                for item in links
            ]
        )
        return OracleMapping.model_validate_json(
            json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "documentType": "oracle_mapping",
                    "mappingId": f"oracle_{digest[:16]}",
                    "observableLogId": log.log_id,
                    "sourceTraceId": trace.trace_id,
                    "sourceTraceSemanticDigest": trace.semantic_digest,
                    "links": links,
                }
            )
        )


def deploy_horizon_sensors(
    workspace: WorkspaceService,
    generation_job_id: str,
    *,
    approved_home: HomeModel | None = None,
    progress: Any = None,
    cancelled: Any = None,
) -> tuple[SensorModel, dict[str, list[str]]]:
    """Deploy the one sensor field a generated horizon is observed with.

    With ``approved_home`` the field is deployed onto the plan the researcher approved, so a room
    they resized or added is covered by the policy exactly as the recommended rooms were.
    """
    generation_dir = generation_run_dir(workspace, generation_job_id)
    manifest = SimulationBatchManifest.model_validate_json(
        (generation_dir / "batch-manifest.json").read_text(encoding="utf-8")
    )
    policy = load_sensor_policy(None)
    day_models: list[tuple[str, SensorModel]] = []
    digests: list[str] = []
    total = len(manifest.runs)
    for index, run in enumerate(manifest.runs, start=1):
        if cancelled is not None and cancelled():
            raise InterruptedError("job was cancelled")
        bundle = _rebound_to_plan(
            SimulationBundle.model_validate_json(
                (generation_dir / run.bundle_path).read_text(encoding="utf-8")
            ),
            approved_home,
        )
        deployment = deploy_sensors(bundle, policy)
        if deployment.sensor_model is None:
            raise HorizonRunError(f"sensor deployment failed for day '{run.run_id}'")
        day_models.append((run.run_id, deployment.sensor_model))
        digests.append(canonical_sha256(bundle))
        if progress is not None:
            progress(
                "sensors",
                round(index / total * 10, 1),
                f"Deploying the horizon sensor field · day {index} of {total}",
            )
    return horizon_sensor_field(
        day_models,
        source_bundle_id=f"horizon_{generation_job_id}",
        source_bundle_sha256=hashlib.sha256(":".join(digests).encode("utf-8")).hexdigest(),
    )


def simulate_horizon(
    workspace: WorkspaceService,
    generation_job_id: str,
    staging: Path,
    *,
    scenario_json: bytes | None = None,
    behavior_json: bytes | None = None,
    approved_home: HomeModel | None = None,
    approved_sensors: SensorModel | None = None,
    progress: Any = None,
    cancelled: Any = None,
) -> dict[str, Any]:
    """Simulate every generated day and write the merged run artifacts into ``staging``.

    ``scenario_json``/``behavior_json`` are the home's published input artifacts; the run records
    exactly what the home declares. They fall back to the generation directory only for a horizon
    inspected outside a home.

    ``approved_home``/``approved_sensors`` are the plan and field the researcher confirmed or
    edited after reviewing the recommendation. The approved plan replaces the generated one in
    every day's bundle; the approved field is installed as it stands instead of being redeployed
    from the policy. Without them the horizon runs exactly on what generation produced.
    """
    generation_dir = generation_run_dir(workspace, generation_job_id)
    manifest = SimulationBatchManifest.model_validate_json(
        (generation_dir / "batch-manifest.json").read_text(encoding="utf-8")
    )
    accumulator = _Accumulator(generation_job_id)
    bundle: SimulationBundle | None = None
    skipped: list[str] = []
    total = len(manifest.runs)

    if approved_sensors is not None:
        sensor_model, introduced_by = approved_sensors, {}
    else:
        sensor_model, introduced_by = deploy_horizon_sensors(
            workspace,
            generation_job_id,
            approved_home=approved_home,
            progress=progress,
            cancelled=cancelled,
        )

    for index, run in enumerate(manifest.runs, start=1):
        if cancelled is not None and cancelled():
            raise InterruptedError("job was cancelled")
        bundle = _rebound_to_plan(
            SimulationBundle.model_validate_json(
                (generation_dir / run.bundle_path).read_text(encoding="utf-8")
            ),
            approved_home,
        )
        simulation = simulate_bundle(bundle)
        if simulation.trace is None:
            skipped.append(run.run_id)
            continue
        # Every day observes the SAME installed field; only its provenance is bound to the day.
        projection = project_sensors(
            simulation.trace, bundle, bind_sensor_model(sensor_model, bundle)
        )
        if projection.observable_log is None or projection.oracle_mapping is None:
            skipped.append(run.run_id)
            continue
        accumulator.add(
            run.run_id, simulation.trace, projection.observable_log, projection.oracle_mapping
        )
        if progress is not None:
            progress(
                "simulating",
                round(10 + index / total * 85, 1),
                f"Day {index} of {total} · {len(accumulator.records)} observations",
            )

    if not accumulator.days or bundle is None:
        raise HorizonRunError("no generated day produced execution evidence")

    trace = accumulator.merged_trace()
    log = accumulator.merged_log(sensor_model, trace)
    oracle = accumulator.merged_oracle(log, trace)

    _write_json(
        staging / "home-model.json",
        bundle.home_model.model_dump_json(by_alias=True, indent=2) + "\n",
    )
    _write_json(
        staging / "sensor-model.json", sensor_model.model_dump_json(by_alias=True, indent=2) + "\n"
    )
    _write_json(
        staging / "scenario.json",
        (
            scenario_json.decode("utf-8")
            if scenario_json is not None
            else (generation_dir / "horizon-scenario.json").read_text(encoding="utf-8")
        ),
    )
    _write_json(
        staging / "personal-process-package.json",
        (
            behavior_json.decode("utf-8")
            if behavior_json is not None
            else (generation_dir / "personal-process-package.json").read_text(encoding="utf-8")
        ),
    )
    _write_json(staging / "execution-trace.json", trace.model_dump_json(by_alias=True, indent=2))
    _write_json(
        staging / "observable-sensor-log.json", log.model_dump_json(by_alias=True, indent=2)
    )
    _write_json(staging / "oracle-mapping.json", oracle.model_dump_json(by_alias=True, indent=2))
    summary = {
        "generationJobId": generation_job_id,
        "experimentId": manifest.experiment_id,
        "dayCount": len(accumulator.days),
        "skippedDays": skipped,
        "observationCount": len(log.records),
        "activityCount": len(trace.activity_executions),
        "traceId": trace.trace_id,
        "traceSemanticDigest": trace.semantic_digest,
        "sourceBundleSha256": trace.source_bundle_sha256,
        "observableLogId": log.log_id,
        "sensorField": _sensor_field_summary(sensor_model, introduced_by),
        "planApproval": {
            "homeModel": "researcher_approved" if approved_home else "generated",
            "sensorModel": "researcher_approved" if approved_sensors else "generated",
            "homeSha256": canonical_sha256(bundle.home_model),
            "sensorModelSha256": canonical_sha256(sensor_model),
        },
        "days": accumulator.days,
    }
    _write_json(staging / "horizon-manifest.json", json.dumps(summary, indent=2) + "\n")
    return summary


def _sensor_field_summary(
    model: SensorModel, introduced_by: dict[str, list[str]]
) -> dict[str, Any]:
    """Describe the installed field and which day each of its sensors first came from."""
    return {
        "sensorModelId": model.sensor_model_id,
        "sensorModelVersion": model.sensor_model_version,
        "sensorCount": len(model.sensors),
        "installedOnce": True,
        "sensorsFirstDeployedOn": introduced_by,
    }


def verify_horizon(trace_path: Path, manifest_path: Path) -> tuple[bool, str, str]:
    """Recompute a published horizon trace's digest from its own content.

    Returns ``(matches, expected, actual)``. A merged trace cannot be re-executed from a single
    bundle — its days were executed independently — so verification recomputes the authoritative
    semantic digest over the published content and cross-checks the composite bundle digest against
    the per-day bundle digests recorded when the run was published.
    """
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    expected = str(payload.get("semanticDigest", ""))
    actual = trace_semantic_digest(payload)
    summary = json.loads(manifest_path.read_text(encoding="utf-8"))
    composite = hashlib.sha256(
        ":".join(str(day["sourceBundleSha256"]) for day in summary.get("days", [])).encode("utf-8")
    ).hexdigest()
    matches = actual == expected and composite == payload.get("sourceBundleSha256")
    return matches, expected, actual


def _home_inputs(
    workspace: WorkspaceService, home_id: str | None
) -> tuple[bytes | None, bytes | None]:
    """The home's published scenario and process package, so the run records its declared input."""
    if home_id is None:
        return None, None
    documents = []
    for kind in ("scenario", "behavior"):
        revision = workspace.latest_revision(home_id, kind)
        artifact_id = revision["artifactId"] if revision else None
        documents.append(workspace.read_artifact(artifact_id) if artifact_id else None)
    return documents[0], documents[1]


def run_horizon_job(workspace: WorkspaceService, job_id: str) -> None:
    """Run one horizon simulation job, publishing its merged artifacts under the home."""
    request = workspace.job_request(job_id)
    generation_job_id = request["generationJobId"]
    output = workspace.runs_path / job_id
    staging = workspace.runs_path / f".{job_id}.staging"

    def cancelled() -> bool:
        return workspace.get_job(job_id).status is JobStatus.cancelled

    def progress(phase: str, percent: float, message: str) -> None:
        # Never resurrect a job cancelled between two updates.
        if cancelled():
            raise InterruptedError("job was cancelled")
        workspace.update_job(
            job_id,
            JobStatus.running,
            JobProgress(phase=phase, percent=percent, message=message),
            process_id=os.getpid(),
        )

    try:
        if output.exists():
            raise HorizonRunError("this run has already published its artifacts")
        shutil.rmtree(staging, ignore_errors=True)
        progress("starting", 1, "Started a local worker")
        home_id = workspace.get_job(job_id).home_id
        scenario_json, behavior_json = _home_inputs(workspace, home_id)
        summary = simulate_horizon(
            workspace,
            generation_job_id,
            staging,
            scenario_json=scenario_json,
            behavior_json=behavior_json,
            approved_home=approved_home_model(workspace, home_id) if home_id else None,
            approved_sensors=approved_sensor_model(workspace, home_id) if home_id else None,
            progress=progress,
            cancelled=cancelled,
        )
        staging.replace(output)
        workspace.import_run_directory(job_id, output)
        workspace.update_job(
            job_id,
            JobStatus.completed,
            JobProgress(
                phase="completed",
                percent=100,
                message=(
                    f"{summary['dayCount']} days merged into one run · "
                    f"{summary['observationCount']} sensor observations"
                ),
            ),
            process_id=os.getpid(),
            result_reference=job_id,
        )
    except InterruptedError:
        shutil.rmtree(staging, ignore_errors=True)
        current = workspace.get_job(job_id)
        if current.status is not JobStatus.cancelled:
            workspace.update_job(
                job_id,
                JobStatus.cancelled,
                JobProgress(
                    phase="cancelled", percent=current.progress.percent, message="Cancelled"
                ),
            )
    except Exception as error:  # noqa: BLE001 - any failure becomes a failed job
        shutil.rmtree(staging, ignore_errors=True)
        current = workspace.get_job(job_id)
        if current.status is not JobStatus.cancelled:
            workspace.update_job(
                job_id,
                JobStatus.failed,
                JobProgress(phase="failed", percent=current.progress.percent, message=str(error)),
                process_id=os.getpid(),
                error_code=type(error).__name__.upper(),
                error_message=str(error),
            )


def _horizon_worker(root: str, job_id: str) -> None:
    workspace = WorkspaceService.open(Path(root), reconcile=False, recover_jobs=False)
    run_horizon_job(workspace, job_id)
