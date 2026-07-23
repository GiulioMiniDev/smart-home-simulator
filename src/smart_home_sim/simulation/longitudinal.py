from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from smart_home_sim.compiler import compile_scenario
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.application import ReplayVerification
from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.domain.execution import ExecutionTrace, FinalWorldState
from smart_home_sim.domain.longitudinal import (
    LongitudinalCheckpoint,
    LongitudinalChunkRecord,
    LongitudinalSimulationIssue,
    LongitudinalSimulationReport,
)
from smart_home_sim.domain.materialization import SyntheticWorkspaceManifest, WorkspaceArtifact
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.sensors import ObservableSensorLog, OracleMapping
from smart_home_sim.environment import build_bundle_files
from smart_home_sim.materialization.service import (
    deploy_sensors_for_bundles,
    generate_home,
)
from smart_home_sim.sensors import project_sensors
from smart_home_sim.simulation.service import simulate_bundle
from smart_home_sim.simulation.longitudinal_aggregate import (
    aggregate_execution_traces,
    aggregate_oracle_mappings,
    aggregate_sensor_logs,
)
from smart_home_sim.simulation.longitudinal_validation import (
    load_and_validate_longitudinal_manifest,
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_write(path: Path, model: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        model.model_dump_json(by_alias=True, indent=2)
        if hasattr(model, "model_dump_json")
        else json.dumps(model, indent=2)
    )
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(content + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp_path, path)


def run_longitudinal_file(
    manifest_path: Path,
    *,
    output_directory: Path,
    resume: bool = True,
    progress: Callable[[str, float, str, dict[str, int]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> LongitudinalSimulationReport:
    started_at = datetime.now(timezone.utc)
    manifest_path = manifest_path.resolve()
    output_directory = output_directory.resolve()

    resolved = load_and_validate_longitudinal_manifest(manifest_path)

    checkpoint_file = output_directory / "checkpoint.json"
    checkpoint: LongitudinalCheckpoint | None = None
    completed_chunks: list[LongitudinalChunkRecord] = []

    if output_directory.exists():
        if resume and checkpoint_file.is_file():
            try:
                loaded_cp = LongitudinalCheckpoint.model_validate_json(
                    checkpoint_file.read_bytes()
                )
                if (
                    loaded_cp.manifest_sha256 != resolved.manifest_sha256
                    or loaded_cp.configuration_sha256 != resolved.configuration_sha256
                ):
                    raise ValueError(
                        "Checkpoint manifest or configuration digest mismatch on resume."
                    )

                # Verify recorded chunk artifacts on disk
                for record in loaded_cp.chunks:
                    chunk_dir = output_directory / record.artifact_path
                    if (
                        not (chunk_dir / "execution-trace.json").is_file()
                        or _file_sha256(chunk_dir / "execution-trace.json")
                        != record.trace_sha256
                        or not (chunk_dir / "terminal-state.json").is_file()
                        or _file_sha256(chunk_dir / "terminal-state.json")
                        != record.terminal_state_sha256
                        or not (chunk_dir / "observable-sensor-log.json").is_file()
                        or _file_sha256(chunk_dir / "observable-sensor-log.json")
                        != record.sensor_log_sha256
                        or not (chunk_dir / "oracle-mapping.json").is_file()
                        or _file_sha256(chunk_dir / "oracle-mapping.json")
                        != record.oracle_mapping_sha256
                    ):
                        raise ValueError(
                            f"Recorded chunk {record.chunk_index} artifact digest mismatch on resume."
                        )

                checkpoint = loaded_cp
                completed_chunks = list(loaded_cp.chunks)
            except Exception as error:
                raise ValueError(f"Failed to resume longitudinal run: {error}") from error
        elif not resume:
            # Clean start when resume is explicitly False
            pass

    output_directory.mkdir(parents=True, exist_ok=True)
    _json_write(output_directory / "manifest.json", resolved.manifest)

    # Step 1: Prebuild home model, canonical plans, and simulation bundles
    home_res = generate_home(
        resolved.scenarios[0], resolved.package, resolved.home_policy
    )
    if home_res.home is None:
        raise ValueError("failed to generate home model for longitudinal simulation")

    _json_write(output_directory / "home-model.json", home_res.home)

    bundles: list[SimulationBundle] = []
    canonical_plans = []

    for idx, sc in enumerate(resolved.scenarios):
        compilation = compile_scenario(sc)
        if compilation.plan is None:
            raise ValueError(f"failed to compile scenario chunk {idx + 1}")

        # Truncation gate check
        # Only enforce truncation check on the final chunk of the longitudinal sequence,
        # as intermediate chunks end at midnight boundaries where state handoff carries over.
        if idx == len(resolved.scenarios) - 1:
            for day in compilation.plan.days:
                for act in day.activities:
                    if act.truncated_at_simulation_end:
                        raise ValueError(
                            f"Scenario chunk {idx + 1} activity '{act.source_activity_id}' "
                            "is truncated at simulation end, which is not permitted."
                        )

        canonical_plans.append(compilation.plan)

        # Temporary files for bundle building
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sc_file = tmp_path / "scenario.json"
            plan_file = tmp_path / "plan.json"
            pkg_file = tmp_path / "package.json"
            home_file = tmp_path / "home.json"

            sc_file.write_text(sc.model_dump_json(by_alias=True), encoding="utf-8")
            plan_file.write_text(
                compilation.plan.model_dump_json(by_alias=True), encoding="utf-8"
            )
            pkg_file.write_text(
                resolved.package.model_dump_json(by_alias=True), encoding="utf-8"
            )
            home_file.write_text(
                home_res.home.model_dump_json(by_alias=True), encoding="utf-8"
            )

            bundle_res = build_bundle_files(sc_file, plan_file, pkg_file, home_file)
            if bundle_res.bundle is None:
                raise ValueError(f"failed to build simulation bundle for chunk {idx + 1}")
            bundles.append(bundle_res.bundle)

    # Step 2: Deploy shared sensor model
    sensor_res = deploy_sensors_for_bundles(bundles, resolved.sensor_policy)
    if sensor_res.sensor_model is None:
        raise ValueError("failed to deploy shared sensor model for longitudinal simulation")

    _json_write(output_directory / "sensor-model.json", sensor_res.sensor_model)

    total_chunks = len(resolved.scenarios)
    last_terminal_state: FinalWorldState | None = (
        checkpoint.terminal_state if checkpoint is not None else None
    )

    completed_count = len(completed_chunks)

    # Step 3: Transactional per-chunk execution
    for chunk_idx in range(completed_count + 1, total_chunks + 1):
        if cancelled is not None and cancelled():
            raise InterruptedError("longitudinal simulation run cancelled")

        if progress is not None:
            progress(
                "execution",
                (chunk_idx - 1) / total_chunks * 100,
                f"Executing longitudinal chunk {chunk_idx}/{total_chunks}",
                {"chunk": chunk_idx, "total": total_chunks},
            )

        bundle = bundles[chunk_idx - 1]
        sc = resolved.scenarios[chunk_idx - 1]
        plan = canonical_plans[chunk_idx - 1]
        sc_path = resolved.manifest.scenario_paths[chunk_idx - 1]

        # Execute chunk simulation with prior terminal state
        sim_res = simulate_bundle(bundle, initial_world_state=last_terminal_state)
        if not sim_res.report.success or sim_res.trace is None:
            issue = LongitudinalSimulationIssue(
                code="LONGITUDINAL_WORKER_FAILED",
                stage="execution",
                path=f"$.chunks[{chunk_idx - 1}]",
                message=f"Simulation failed for chunk {chunk_idx}: {sim_res.report.issues}",
            )
            fail_report = LongitudinalSimulationReport(
                success=False,
                run_id=resolved.manifest.run_id,
                manifest_sha256=resolved.manifest_sha256,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                chunks=completed_chunks,
                issues=[issue],
            )
            _json_write(output_directory / "run.json", fail_report)
            return fail_report

        # Project sensors for chunk
        proj_res = project_sensors(
            sim_res.trace, bundle, sensor_res.sensor_model
        )
        if (
            not proj_res.report.success
            or proj_res.observable_log is None
            or proj_res.oracle_mapping is None
        ):
            issue = LongitudinalSimulationIssue(
                code="LONGITUDINAL_WORKER_FAILED",
                stage="execution",
                path=f"$.chunks[{chunk_idx - 1}]",
                message=f"Sensor projection failed for chunk {chunk_idx}.",
            )
            fail_report = LongitudinalSimulationReport(
                success=False,
                run_id=resolved.manifest.run_id,
                manifest_sha256=resolved.manifest_sha256,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                chunks=completed_chunks,
                issues=[issue],
            )
            _json_write(output_directory / "run.json", fail_report)
            return fail_report

        # Save accepted chunk artifacts into chunks/NNNN
        chunk_rel_path = f"chunks/{chunk_idx:04d}"
        chunk_dir = output_directory / chunk_rel_path
        chunk_dir.mkdir(parents=True, exist_ok=True)

        _json_write(chunk_dir / "scenario.json", sc)
        _json_write(chunk_dir / "canonical-plan.json", plan)
        _json_write(chunk_dir / "simulation-bundle.json", bundle)
        _json_write(chunk_dir / "execution-trace.json", sim_res.trace)
        _json_write(chunk_dir / "simulation-report.json", sim_res.report)
        _json_write(chunk_dir / "terminal-state.json", sim_res.trace.final_state)
        _json_write(chunk_dir / "observable-sensor-log.json", proj_res.observable_log)
        _json_write(chunk_dir / "oracle-mapping.json", proj_res.oracle_mapping)

        if last_terminal_state is not None:
            _json_write(chunk_dir / "input-state.json", last_terminal_state)

        record = LongitudinalChunkRecord(
            chunk_index=chunk_idx,
            scenario_path=sc_path,
            scenario_sha256=_file_sha256(chunk_dir / "scenario.json"),
            input_state_sha256=(
                _file_sha256(chunk_dir / "input-state.json")
                if (chunk_dir / "input-state.json").is_file()
                else None
            ),
            artifact_path=chunk_rel_path,
            bundle_sha256=_file_sha256(chunk_dir / "simulation-bundle.json"),
            trace_sha256=_file_sha256(chunk_dir / "execution-trace.json"),
            terminal_state_sha256=_file_sha256(chunk_dir / "terminal-state.json"),
            sensor_log_sha256=_file_sha256(chunk_dir / "observable-sensor-log.json"),
            oracle_mapping_sha256=_file_sha256(chunk_dir / "oracle-mapping.json"),
        )

        completed_chunks.append(record)
        last_terminal_state = sim_res.trace.final_state

        # Update checkpoint atomically
        checkpoint = LongitudinalCheckpoint(
            run_id=resolved.manifest.run_id,
            manifest_sha256=resolved.manifest_sha256,
            configuration_sha256=resolved.configuration_sha256,
            completed_chunk_count=chunk_idx,
            terminal_state=last_terminal_state,
            chunks=completed_chunks,
        )
        _json_write(checkpoint_file, checkpoint)

    # Step 4: Publish aggregated monthly outputs
    chunk_traces: list[ExecutionTrace] = []
    chunk_logs: list[ObservableSensorLog] = []
    chunk_oracles: list[OracleMapping] = []

    for record in completed_chunks:
        c_dir = output_directory / record.artifact_path
        chunk_traces.append(
            ExecutionTrace.model_validate_json((c_dir / "execution-trace.json").read_bytes())
        )
        chunk_logs.append(
            ObservableSensorLog.model_validate_json((c_dir / "observable-sensor-log.json").read_bytes())
        )
        chunk_oracles.append(
            OracleMapping.model_validate_json((c_dir / "oracle-mapping.json").read_bytes())
        )

    agg_trace = aggregate_execution_traces(
        resolved.manifest.run_id, resolved.manifest.seed, chunk_traces
    )
    agg_log = aggregate_sensor_logs(chunk_logs)
    agg_oracle = aggregate_oracle_mappings(agg_trace, agg_log, chunk_oracles)

    ended_at = datetime.now(timezone.utc)
    report = LongitudinalSimulationReport(
        success=True,
        run_id=resolved.manifest.run_id,
        manifest_sha256=resolved.manifest_sha256,
        started_at=started_at,
        ended_at=ended_at,
        chunks=completed_chunks,
        issues=[],
    )

    staging_agg = output_directory / "aggregate.tmp"
    staging_agg.mkdir(parents=True, exist_ok=True)

    _json_write(staging_agg / "execution-trace.json", agg_trace)
    _json_write(staging_agg / "observable-sensor-log.json", agg_log)
    _json_write(staging_agg / "oracle-mapping.json", agg_oracle)
    _json_write(staging_agg / "simulation-report.json", report)

    agg_dir = output_directory / "aggregate"
    if agg_dir.exists():
        import shutil
        shutil.rmtree(agg_dir)
    os.replace(staging_agg, agg_dir)

    # Root workspace manifest
    workspace_manifest = SyntheticWorkspaceManifest(
        scenario_id=resolved.scenarios[0].scenario_id,
        bundle_id=f"longitudinal_{resolved.manifest.run_id}",
        trace_id=agg_trace.trace_id,
        sensor_log_id=agg_log.log_id,
        artifacts=[
            WorkspaceArtifact(
                role="execution_trace",
                relative_path="aggregate/execution-trace.json",
                sha256=_file_sha256(agg_dir / "execution-trace.json"),
            ),
            WorkspaceArtifact(
                role="observable_sensor_log",
                relative_path="aggregate/observable-sensor-log.json",
                sha256=_file_sha256(agg_dir / "observable-sensor-log.json"),
            ),
            WorkspaceArtifact(
                role="oracle_mapping",
                relative_path="aggregate/oracle-mapping.json",
                sha256=_file_sha256(agg_dir / "oracle-mapping.json"),
            ),
            WorkspaceArtifact(
                role="home_model",
                relative_path="home-model.json",
                sha256=_file_sha256(output_directory / "home-model.json"),
            ),
            WorkspaceArtifact(
                role="sensor_model",
                relative_path="sensor-model.json",
                sha256=_file_sha256(output_directory / "sensor-model.json"),
            ),
            WorkspaceArtifact(
                role="longitudinal_report",
                relative_path="aggregate/simulation-report.json",
                sha256=_file_sha256(agg_dir / "simulation-report.json"),
            ),
        ],
    )
    _json_write(output_directory / "workspace-manifest.json", workspace_manifest)
    _json_write(output_directory / "run.json", report)

    if progress is not None:
        progress(
            "completed",
            100,
            "Completed longitudinal simulation run",
            {"chunks": len(completed_chunks)},
        )

    return report


def verify_longitudinal_run(output_directory: Path) -> ReplayVerification:
    output_directory = output_directory.resolve()
    checkpoint_file = output_directory / "checkpoint.json"
    manifest_file = output_directory / "manifest.json"

    if not checkpoint_file.is_file() or not manifest_file.is_file():
        return ReplayVerification(
            run_id=output_directory.name,
            verified_at=datetime.now(timezone.utc),
            matches=False,
            expected_semantic_digest="0" * 64,
            actual_semantic_digest=None,
        )

    try:
        cp = LongitudinalCheckpoint.model_validate_json(checkpoint_file.read_bytes())
        agg_trace_file = output_directory / "aggregate/execution-trace.json"
        if not agg_trace_file.is_file():
            return ReplayVerification(
                run_id=cp.run_id,
                verified_at=datetime.now(timezone.utc),
                matches=False,
                expected_semantic_digest="0" * 64,
                actual_semantic_digest=None,
            )

        agg_trace = ExecutionTrace.model_validate_json(agg_trace_file.read_bytes())
        expected_digest = agg_trace.semantic_digest

        # Re-verify chunk traces
        chunk_traces: list[ExecutionTrace] = []
        for record in cp.chunks:
            c_dir = output_directory / record.artifact_path
            t_file = c_dir / "execution-trace.json"
            if not t_file.is_file() or _file_sha256(t_file) != record.trace_sha256:
                return ReplayVerification(
                    run_id=cp.run_id,
                    verified_at=datetime.now(timezone.utc),
                    matches=False,
                    expected_semantic_digest=expected_digest,
                    actual_semantic_digest=None,
                )
            chunk_traces.append(ExecutionTrace.model_validate_json(t_file.read_bytes()))

        # Re-build aggregate trace
        rebuilt_agg_trace = aggregate_execution_traces(
            cp.run_id, agg_trace.seed, chunk_traces
        )
        actual_digest = rebuilt_agg_trace.semantic_digest

        return ReplayVerification(
            run_id=cp.run_id,
            verified_at=datetime.now(timezone.utc),
            matches=(actual_digest == expected_digest),
            expected_semantic_digest=expected_digest,
            actual_semantic_digest=actual_digest,
        )
    except Exception:
        return ReplayVerification(
            run_id=output_directory.name,
            verified_at=datetime.now(timezone.utc),
            matches=False,
            expected_semantic_digest="0" * 64,
            actual_semantic_digest=None,
        )
