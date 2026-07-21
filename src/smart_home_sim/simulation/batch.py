from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.batch import (
    SimulationBatchIssue,
    SimulationBatchManifest,
    SimulationBatchReport,
    SimulationBatchRun,
    SimulationBatchRunResult,
    SimulationBatchSummary,
)
from smart_home_sim.domain.execution import (
    ExecutionTrace,
    SimulationIssue,
    SimulationReport,
)
from smart_home_sim.simulation.locking import InterProcessFileLock, LockUnavailableError
from smart_home_sim.simulation.service import load_simulation_bundle_file, simulate_bundle
from smart_home_sim.validation.service import (
    MAX_SCENARIO_BYTES,
    DuplicateJsonKeyError,
    InvalidJsonConstantError,
    _exceeds_json_nesting_limit,
    _json_path,
    _reject_duplicate_keys,
    _reject_non_finite_constant,
)


class BatchManifestError(ValueError):
    def __init__(self, issues: list[SimulationBatchIssue]) -> None:
        super().__init__(issues[0].message if issues else "Invalid batch manifest")
        self.issues = issues


class BatchLockedError(RuntimeError):
    pass


def _issue(code: str, message: str, path: str = "$") -> SimulationBatchIssue:
    return SimulationBatchIssue(code=code, stage="input", path=path, message=message)


def _batch_issues(issues: list[SimulationIssue]) -> list[SimulationBatchIssue]:
    return [SimulationBatchIssue.model_validate(item.model_dump()) for item in issues]


def load_batch_manifest_file(path: Path) -> SimulationBatchManifest:
    try:
        encoded = path.read_bytes()
    except FileNotFoundError as error:
        raise BatchManifestError(
            [_issue("FILE_NOT_FOUND", f"Batch manifest not found: {path}")]
        ) from error
    except OSError as error:
        raise BatchManifestError(
            [_issue("FILE_READ_ERROR", f"Cannot read batch manifest: {error}")]
        ) from error
    if len(encoded) > MAX_SCENARIO_BYTES:
        raise BatchManifestError(
            [_issue("FILE_TOO_LARGE", "Batch manifest exceeds the input size limit.")]
        )
    try:
        raw = encoded.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BatchManifestError(
            [_issue("FILE_ENCODING_ERROR", "Batch manifest must be UTF-8.")]
        ) from error
    if _exceeds_json_nesting_limit(raw):
        raise BatchManifestError(
            [_issue("JSON_NESTING_TOO_DEEP", "Batch manifest is nested too deeply.")]
        )
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except (DuplicateJsonKeyError, InvalidJsonConstantError, json.JSONDecodeError) as error:
        raise BatchManifestError(
            [_issue("JSON_SYNTAX", f"Invalid batch manifest JSON: {error}")]
        ) from error
    if not isinstance(payload, dict):
        raise BatchManifestError(
            [_issue("STRUCTURE_INVALID", "Batch manifest must be a JSON object.")]
        )
    try:
        return SimulationBatchManifest.model_validate(payload)
    except ValidationError as error:
        issues = [
            _issue("BATCH_MANIFEST_INVALID", item["msg"], _json_path(item["loc"]))
            for item in error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
        ]
        raise BatchManifestError(issues) from error


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.tmp-",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        assert temporary is not None
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _output_lock(output_directory: Path):
    output_directory.mkdir(parents=True, exist_ok=True)
    lock_path = output_directory / ".simulation-batch.lock"
    try:
        with InterProcessFileLock(lock_path) as lock:
            lock.write_metadata(f"pid={os.getpid()}\nbackend={lock.backend.name}\n")
            yield
    except LockUnavailableError as error:
        raise BatchLockedError(
            f"Another batch is already writing to '{output_directory}'."
        ) from error


def _relative_artifact_paths(run_id: str) -> tuple[str, str, str]:
    return (
        f"{run_id}/simulation-bundle.json",
        f"{run_id}/execution-trace.json",
        f"{run_id}/simulation-report.json",
    )


def _resolved_input(manifest_path: Path, run: SimulationBatchRun) -> Path:
    path = Path(run.bundle_path)
    return path.resolve() if path.is_absolute() else (manifest_path.parent / path).resolve()


def _worker_failure(
    run: SimulationBatchRun,
    *,
    report_path: str,
    elapsed_seconds: float,
    code: str,
    message: str,
    worker_pid: int | None = None,
) -> SimulationBatchRunResult:
    return SimulationBatchRunResult(
        run_id=run.run_id,
        status="failed",
        input_bundle_path=run.bundle_path,
        effective_seed=run.seed,
        simulation_report_path=report_path,
        elapsed_seconds=elapsed_seconds,
        worker_pid=worker_pid,
        issues=[SimulationBatchIssue(code=code, stage="execution", path="$", message=message)],
    )


def _execute_run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    run = SimulationBatchRun.model_validate(payload["run"])
    input_path = Path(payload["input_path"])
    output_directory = Path(payload["output_directory"])
    bundle_relative, trace_relative, report_relative = _relative_artifact_paths(run.run_id)
    bundle_path = output_directory / bundle_relative
    trace_path = output_directory / trace_relative
    report_path = output_directory / report_relative
    pid = os.getpid()
    try:
        bundle, input_issues = load_simulation_bundle_file(input_path)
        if bundle is None:
            elapsed = time.perf_counter() - started
            report = SimulationReport(
                success=False,
                issues=input_issues,
                summary={
                    "plannedActivityCount": 0,
                    "completedActivityCount": 0,
                    "deviatedActivityCount": 0,
                    "failedActivityCount": 0,
                    "droppedActivityCount": 0,
                    "actionExecutionCount": 0,
                    "movementCount": 0,
                    "stateTransitionCount": 0,
                    "runtimeEventCount": 0,
                    "errorCount": len(input_issues),
                    "warningCount": 0,
                },
            )
            _atomic_write(report_path, report.model_dump_json(by_alias=True, indent=2))
            return SimulationBatchRunResult(
                run_id=run.run_id,
                status="failed",
                input_bundle_path=run.bundle_path,
                effective_seed=run.seed,
                simulation_report_path=report_relative,
                elapsed_seconds=elapsed,
                worker_pid=pid,
                issues=_batch_issues(input_issues),
            ).model_dump(mode="json", by_alias=True)
        input_sha = canonical_sha256(bundle)
        effective = bundle if run.seed is None else bundle.model_copy(update={"seed": run.seed})
        effective_sha = canonical_sha256(effective)
        _atomic_write(bundle_path, effective.model_dump_json(by_alias=True, indent=2))
        result = simulate_bundle(effective)
        if result.trace is not None:
            _atomic_write(trace_path, result.trace.model_dump_json(by_alias=True, indent=2))
        elif trace_path.exists():
            trace_path.unlink()
        _atomic_write(report_path, result.report.model_dump_json(by_alias=True, indent=2))
        elapsed = time.perf_counter() - started
        if result.trace is None:
            return SimulationBatchRunResult(
                run_id=run.run_id,
                status="failed",
                input_bundle_path=run.bundle_path,
                input_bundle_sha256=input_sha,
                effective_bundle_sha256=effective_sha,
                effective_seed=effective.seed,
                effective_bundle_path=bundle_relative,
                simulation_report_path=report_relative,
                elapsed_seconds=elapsed,
                worker_pid=pid,
                issues=_batch_issues(result.report.issues),
            ).model_dump(mode="json", by_alias=True)
        return SimulationBatchRunResult(
            run_id=run.run_id,
            status="completed",
            input_bundle_path=run.bundle_path,
            input_bundle_sha256=input_sha,
            effective_bundle_sha256=effective_sha,
            effective_seed=effective.seed,
            effective_bundle_path=bundle_relative,
            trace_path=trace_relative,
            simulation_report_path=report_relative,
            semantic_digest=result.trace.semantic_digest,
            trace_sha256=result.report.trace_sha256,
            elapsed_seconds=elapsed,
            worker_pid=pid,
        ).model_dump(mode="json", by_alias=True)
    except Exception as error:
        return _worker_failure(
            run,
            report_path=report_relative,
            elapsed_seconds=time.perf_counter() - started,
            worker_pid=pid,
            code="BATCH_WORKER_FAILED",
            message=str(error),
        ).model_dump(mode="json", by_alias=True)


def _resume_result(
    run: SimulationBatchRun,
    manifest_path: Path,
    output_directory: Path,
) -> SimulationBatchRunResult | None:
    bundle_relative, trace_relative, report_relative = _relative_artifact_paths(run.run_id)
    effective_path = output_directory / bundle_relative
    trace_path = output_directory / trace_relative
    report_path = output_directory / report_relative
    if not report_path.exists():
        return None
    try:
        report = SimulationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError):
        return _worker_failure(
            run,
            report_path=report_relative,
            elapsed_seconds=0,
            code="RESUME_INVALID",
            message="Existing simulation report is invalid; use a new output directory.",
        )
    if not report.success:
        return None
    input_bundle, input_issues = load_simulation_bundle_file(_resolved_input(manifest_path, run))
    effective_bundle, effective_issues = load_simulation_bundle_file(effective_path)
    try:
        trace = ExecutionTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError):
        trace = None
    if input_bundle is None or effective_bundle is None or trace is None:
        issues = [*input_issues, *effective_issues]
        detail = issues[0].message if issues else "Existing run artifacts are incomplete."
        return _worker_failure(
            run,
            report_path=report_relative,
            elapsed_seconds=0,
            code="RESUME_INVALID",
            message=f"Cannot resume run '{run.run_id}': {detail}",
        )
    expected_effective = (
        input_bundle if run.seed is None else input_bundle.model_copy(update={"seed": run.seed})
    )
    valid = (
        canonical_sha256(expected_effective) == canonical_sha256(effective_bundle)
        and report.source_bundle_sha256 == canonical_sha256(effective_bundle)
        and report.trace_sha256 == canonical_sha256(trace)
        and report.semantic_digest == trace.semantic_digest
    )
    if not valid:
        return _worker_failure(
            run,
            report_path=report_relative,
            elapsed_seconds=0,
            code="RESUME_INVALID",
            message=f"Existing artifacts for run '{run.run_id}' do not match its current input.",
        )
    return SimulationBatchRunResult(
        run_id=run.run_id,
        status="reused",
        input_bundle_path=run.bundle_path,
        input_bundle_sha256=canonical_sha256(input_bundle),
        effective_bundle_sha256=canonical_sha256(effective_bundle),
        effective_seed=effective_bundle.seed,
        effective_bundle_path=bundle_relative,
        trace_path=trace_relative,
        simulation_report_path=report_relative,
        semantic_digest=trace.semantic_digest,
        trace_sha256=report.trace_sha256,
        elapsed_seconds=0,
    )


def run_batch_manifest(
    manifest: SimulationBatchManifest,
    *,
    manifest_path: Path,
    output_directory: Path,
    workers: int,
    resume: bool = True,
) -> SimulationBatchReport:
    if workers < 1:
        raise ValueError("workers must be at least one")
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    output_directory = output_directory.resolve()
    worker_count = min(workers, len(manifest.runs))
    results: dict[str, SimulationBatchRunResult] = {}
    pending: list[SimulationBatchRun] = []
    with _output_lock(output_directory):
        for run in manifest.runs:
            reused = _resume_result(run, manifest_path, output_directory) if resume else None
            if reused is None:
                pending.append(run)
            else:
                results[run.run_id] = reused
        if pending and worker_count == 1:
            for run in pending:
                results[run.run_id] = SimulationBatchRunResult.model_validate(
                    _execute_run_worker(
                        {
                            "run": run.model_dump(mode="json", by_alias=True),
                            "input_path": str(_resolved_input(manifest_path, run)),
                            "output_directory": str(output_directory),
                        }
                    )
                )
        elif pending:
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(max_workers=worker_count, mp_context=context) as executor:
                future_runs = {
                    executor.submit(
                        _execute_run_worker,
                        {
                            "run": run.model_dump(mode="json", by_alias=True),
                            "input_path": str(_resolved_input(manifest_path, run)),
                            "output_directory": str(output_directory),
                        },
                    ): run
                    for run in pending
                }
                for future in as_completed(future_runs):
                    run = future_runs[future]
                    try:
                        results[run.run_id] = SimulationBatchRunResult.model_validate(
                            future.result()
                        )
                    except Exception as error:
                        results[run.run_id] = _worker_failure(
                            run,
                            report_path=_relative_artifact_paths(run.run_id)[2],
                            elapsed_seconds=0,
                            code="BATCH_WORKER_FAILED",
                            message=str(error),
                        )
        ordered = [results[run.run_id] for run in manifest.runs]
        elapsed = time.perf_counter() - started
        failed = sum(run.status == "failed" for run in ordered)
        report = SimulationBatchReport(
            success=failed == 0,
            experiment_id=manifest.experiment_id,
            manifest_sha256=canonical_sha256(manifest),
            started_at=started_at,
            ended_at=datetime.now(UTC),
            output_directory=str(output_directory),
            runs=ordered,
            summary=SimulationBatchSummary(
                requested_run_count=len(ordered),
                completed_run_count=sum(run.status == "completed" for run in ordered),
                reused_run_count=sum(run.status == "reused" for run in ordered),
                failed_run_count=failed,
                worker_count=worker_count,
                elapsed_seconds=elapsed,
            ),
        )
        _atomic_write(
            output_directory / "batch-report.json",
            report.model_dump_json(by_alias=True, indent=2),
        )
        return report


def run_batch_file(
    manifest_path: Path,
    *,
    output_directory: Path,
    workers: int,
    resume: bool = True,
) -> SimulationBatchReport:
    manifest = load_batch_manifest_file(manifest_path)
    return run_batch_manifest(
        manifest,
        manifest_path=manifest_path.resolve(),
        output_directory=output_directory,
        workers=workers,
        resume=resume,
    )
