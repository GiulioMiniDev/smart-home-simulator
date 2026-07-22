from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from smart_home_sim.application.workspace import WorkspaceService, _iso


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark an M7 application workspace")
    parser.add_argument("--artifacts", type=int, default=10_000)
    parser.add_argument("--runs", type=int, default=1_000)
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    if arguments.artifacts < 1 or arguments.runs < 1:
        raise SystemExit("artifact and run counts must be positive")
    with tempfile.TemporaryDirectory(prefix="smart-home-m7-benchmark-") as temporary:
        root = Path(temporary) / "workspace"
        workspace = WorkspaceService.create(root, "M7 benchmark")
        home = workspace.create_home("Acceptance home")
        artifact_root = workspace.objects_path / "benchmark"
        artifact_root.mkdir()
        now = _iso()
        artifact_rows = []
        for index in range(arguments.artifacts):
            content = json.dumps({"index": index}, separators=(",", ":")).encode()
            path = artifact_root / f"artifact-{index:05d}.json"
            path.write_bytes(content)
            artifact_rows.append(
                (
                    f"benchmark_artifact_{index:05d}",
                    home.home_id,
                    f"run_{index % arguments.runs:04d}",
                    "benchmark_record",
                    "1.0.0",
                    "application/json",
                    path.relative_to(root).as_posix(),
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                    now,
                )
            )
        job_rows = [
            (
                f"run_{index:04d}",
                home.home_id,
                "simulation",
                "completed",
                "completed",
                100.0,
                1,
                1,
                "Completed",
                now,
                now,
                now,
                f"run_{index:04d}",
                index,
                "{}",
            )
            for index in range(arguments.runs)
        ]
        with workspace.transaction() as connection:
            connection.executemany(
                """INSERT INTO artifacts(
                    artifact_id, home_id, run_id, role, schema_version, media_type,
                    relative_path, size_bytes, sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                artifact_rows,
            )
            connection.executemany(
                """INSERT INTO jobs(
                    job_id, home_id, kind, status, phase, percent, completed_units,
                    total_units, message, requested_at, started_at, finished_at,
                    result_reference, seed, request_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                job_rows,
            )

        tracemalloc.start()
        started = time.perf_counter()
        reopened = WorkspaceService.open(root, reconcile=False, recover_jobs=False)
        open_seconds = time.perf_counter() - started
        started = time.perf_counter()
        assert reopened.list_homes("Acceptance")
        search_seconds = time.perf_counter() - started
        started = time.perf_counter()
        manifest = reopened.manifest()
        manifest_seconds = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        result = {
            "artifacts": len(manifest.artifacts),
            "runs": reopened.summary().run_count,
            "openSeconds": round(open_seconds, 4),
            "searchSeconds": round(search_seconds, 4),
            "manifestSeconds": round(manifest_seconds, 4),
            "peakMiB": round(peak / 1024**2, 2),
        }
        print(json.dumps(result, sort_keys=True))
        if open_seconds > 5 or search_seconds > 2 or manifest_seconds > 15 or peak > 300 * 1024**2:
            raise SystemExit("M7 workspace benchmark exceeded its acceptance budget")


if __name__ == "__main__":
    main()
