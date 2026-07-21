from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from smart_home_sim.simulation.batch import run_batch_file

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "examples/batch/mario_week.seed-sweep.json"
TARGET_SECONDS = 30.0


def main() -> None:
    parallel_workers = min(4, max(2, os.cpu_count() or 2))
    with tempfile.TemporaryDirectory(prefix="smart-home-batch-benchmark-") as directory:
        root = Path(directory)
        sequential = run_batch_file(
            MANIFEST,
            output_directory=root / "sequential",
            workers=1,
            resume=False,
        )
        parallel = run_batch_file(
            MANIFEST,
            output_directory=root / "parallel",
            workers=parallel_workers,
            resume=False,
        )
        sequential_digests = [run.semantic_digest for run in sequential.runs]
        parallel_digests = [run.semantic_digest for run in parallel.runs]
        worker_pids = {run.worker_pid for run in parallel.runs}
        deterministic = sequential_digests == parallel_digests
        isolated_workers = len(worker_pids) >= 2
        passed = (
            sequential.success
            and parallel.success
            and deterministic
            and isolated_workers
            and parallel.summary.elapsed_seconds < TARGET_SECONDS
        )
        payload = {
            "benchmarkVersion": "simulation-batch-1.0.0",
            "runCount": len(parallel.runs),
            "parallelWorkers": parallel.summary.worker_count,
            "observedWorkerProcesses": len(worker_pids),
            "sequentialSeconds": round(sequential.summary.elapsed_seconds, 6),
            "parallelSeconds": round(parallel.summary.elapsed_seconds, 6),
            "speedup": round(
                sequential.summary.elapsed_seconds / parallel.summary.elapsed_seconds,
                4,
            ),
            "deterministicAcrossWorkerCounts": deterministic,
            "targetSeconds": TARGET_SECONDS,
            "passed": passed,
        }
        print(json.dumps(payload, sort_keys=True))
        if not passed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
