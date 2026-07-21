from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from smart_home_sim.cli import app
from smart_home_sim.domain.batch import (
    SimulationBatchManifest,
    SimulationBatchReport,
    SimulationBatchRun,
    SimulationBatchRunResult,
    SimulationBatchSummary,
)
from smart_home_sim.domain.execution import ExecutionTrace, SimulationReport
from smart_home_sim.simulation.batch import (
    BatchLockedError,
    BatchManifestError,
    _output_lock,
    load_batch_manifest_file,
    run_batch_file,
)
from smart_home_sim.simulation.service import replay_files

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "examples/bundles/mario_week.simulation-bundle-behavior-1.1.0.json"


def _write_manifest(path: Path, runs: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "documentType": "simulation_batch_manifest",
                "experimentId": "batch_test",
                "runs": runs,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def parallel_batch(tmp_path_factory):
    directory = tmp_path_factory.mktemp("parallel-batch")
    manifest_path = directory / "manifest.json"
    _write_manifest(
        manifest_path,
        [
            {"runId": "seed_11", "bundlePath": str(BUNDLE), "seed": 11},
            {"runId": "seed_22", "bundlePath": str(BUNDLE), "seed": 22},
        ],
    )
    output = directory / "output"
    report = run_batch_file(manifest_path, output_directory=output, workers=2)
    return manifest_path, output, report


def test_parallel_batch_isolated_workers_and_replayable_artifacts(parallel_batch) -> None:
    _, output, report = parallel_batch
    assert report.success
    assert report.summary.completed_run_count == 2
    assert report.summary.worker_count == 2
    assert len({run.worker_pid for run in report.runs}) == 2
    assert len({run.semantic_digest for run in report.runs}) == 2
    assert [run.run_id for run in report.runs] == ["seed_11", "seed_22"]
    for run in report.runs:
        assert run.effective_bundle_path is not None
        assert run.trace_path is not None
        bundle_path = output / run.effective_bundle_path
        trace_path = output / run.trace_path
        assert b"\r\n" not in bundle_path.read_bytes()
        assert b"\r\n" not in trace_path.read_bytes()
        assert b"\r\n" not in (output / run.simulation_report_path).read_bytes()
        simulation_report = SimulationReport.model_validate_json(
            (output / run.simulation_report_path).read_text(encoding="utf-8")
        )
        trace = ExecutionTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
        assert trace.seed == run.effective_seed
        assert simulation_report.semantic_digest == run.semantic_digest
        assert replay_files(bundle_path, trace_path).matches


def test_batch_resume_reuses_verified_runs(parallel_batch) -> None:
    manifest_path, output, original = parallel_batch
    resumed = run_batch_file(manifest_path, output_directory=output, workers=2, resume=True)
    assert resumed.success
    assert resumed.summary.completed_run_count == 0
    assert resumed.summary.reused_run_count == 2
    assert all(run.status == "reused" and run.worker_pid is None for run in resumed.runs)
    assert [run.semantic_digest for run in resumed.runs] == [
        run.semantic_digest for run in original.runs
    ]


def test_batch_resume_rejects_tampered_trace(parallel_batch, tmp_path: Path) -> None:
    manifest_path, output, _ = parallel_batch
    copied = tmp_path / "tampered"
    shutil.copytree(output, copied)
    trace_path = copied / "seed_11/execution-trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["semanticDigest"] = "0" * 64
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    report = run_batch_file(manifest_path, output_directory=copied, workers=2, resume=True)
    assert not report.success
    assert report.runs[0].issues[0].code == "RESUME_INVALID"
    assert report.runs[1].status == "reused"


def test_batch_is_deterministic_across_worker_counts(parallel_batch, tmp_path: Path) -> None:
    manifest_path, _, parallel = parallel_batch
    sequential = run_batch_file(
        manifest_path,
        output_directory=tmp_path / "sequential",
        workers=1,
    )
    assert [run.semantic_digest for run in sequential.runs] == [
        run.semantic_digest for run in parallel.runs
    ]
    assert len({run.worker_pid for run in sequential.runs}) == 1


def test_batch_failure_is_isolated_and_reported(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        [
            {"runId": "valid", "bundlePath": str(BUNDLE), "seed": 33},
            {"runId": "missing", "bundlePath": "missing.json"},
        ],
    )
    output = tmp_path / "output"
    report = run_batch_file(manifest_path, output_directory=output, workers=1)
    assert not report.success
    assert report.summary.completed_run_count == 1
    assert report.summary.failed_run_count == 1
    assert report.runs[0].status == "completed"
    assert report.runs[1].issues[0].code == "FILE_NOT_FOUND"
    assert (
        SimulationBatchReport.model_validate_json(
            (output / "batch-report.json").read_text(encoding="utf-8")
        )
        == report
    )


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"schemaVersion":"1.0.0",}',
        '{"schemaVersion":"1.0.0","schemaVersion":"1.0.0"}',
        '{"schemaVersion":"1.0.0"}',
    ],
)
def test_batch_manifest_loader_rejects_invalid_inputs(tmp_path: Path, content: str) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(BatchManifestError):
        load_batch_manifest_file(path)


def test_batch_manifest_loader_io_and_size_guards(monkeypatch, tmp_path: Path) -> None:
    with pytest.raises(BatchManifestError):
        load_batch_manifest_file(tmp_path / "missing.json")
    with pytest.raises(BatchManifestError):
        load_batch_manifest_file(tmp_path)
    invalid_utf8 = tmp_path / "invalid-utf8.json"
    invalid_utf8.write_bytes(b"\xff")
    with pytest.raises(BatchManifestError):
        load_batch_manifest_file(invalid_utf8)
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 300 + "]" * 300, encoding="utf-8")
    with pytest.raises(BatchManifestError):
        load_batch_manifest_file(deep)
    monkeypatch.setattr("smart_home_sim.simulation.batch.MAX_SCENARIO_BYTES", 0)
    with pytest.raises(BatchManifestError):
        load_batch_manifest_file(invalid_utf8)


def test_batch_output_directory_lock_is_non_blocking(tmp_path: Path) -> None:
    with (
        _output_lock(tmp_path),
        pytest.raises(BatchLockedError),
        _output_lock(tmp_path),
    ):
        pytest.fail("a second writer acquired the same batch directory")


def test_batch_manifest_models_enforce_identity_and_summary() -> None:
    run = SimulationBatchRun(run_id="valid", bundle_path="bundle.json")
    with pytest.raises(ValidationError):
        SimulationBatchManifest(
            experiment_id="experiment",
            runs=[run, run],
        )
    with pytest.raises(ValidationError):
        SimulationBatchRunResult(
            run_id="run",
            status="completed",
            input_bundle_path="bundle.json",
            simulation_report_path="report.json",
            elapsed_seconds=0,
        )
    with pytest.raises(ValidationError):
        SimulationBatchRunResult(
            run_id="run",
            status="failed",
            input_bundle_path="bundle.json",
            simulation_report_path="report.json",
            elapsed_seconds=0,
        )
    failed_run = SimulationBatchRunResult(
        run_id="run",
        status="failed",
        input_bundle_path="bundle.json",
        simulation_report_path="report.json",
        elapsed_seconds=0,
        issues=[
            {
                "code": "SIMULATION_FAILED",
                "stage": "execution",
                "path": "$",
                "message": "failed",
            }
        ],
    )
    started_at = datetime(2026, 7, 21, 10, tzinfo=UTC)
    with pytest.raises(ValidationError):
        SimulationBatchReport(
            success=True,
            experiment_id="experiment",
            manifest_sha256="0" * 64,
            started_at=started_at,
            ended_at=started_at - timedelta(hours=1),
            output_directory="output",
            runs=[failed_run],
            summary=SimulationBatchSummary(
                requested_run_count=1,
                completed_run_count=0,
                reused_run_count=0,
                failed_run_count=1,
                worker_count=1,
                elapsed_seconds=0,
            ),
        )


def test_cli_reports_invalid_batch_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "invalid.json"
    manifest.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["simulate-batch", str(manifest), "--output-dir", str(tmp_path / "output")],
    )
    assert result.exit_code == 2
    assert "BATCH_MANIFEST_INVALID" in result.output


def test_cli_resumes_completed_batch(parallel_batch) -> None:
    manifest, output, _ = parallel_batch
    result = CliRunner().invoke(
        app,
        [
            "simulate-batch",
            str(manifest),
            "--output-dir",
            str(output),
            "--workers",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Batch report written" in result.output
