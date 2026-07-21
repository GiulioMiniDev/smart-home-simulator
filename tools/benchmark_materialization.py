from __future__ import annotations

import tempfile
import time
from pathlib import Path

from smart_home_sim.materialization import materialize_workspace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "generated/mario_rossi_2026_10_30_ingested"
MAX_SECONDS = 10.0


def main() -> None:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as temporary:
        manifest = materialize_workspace(
            SOURCE / "scenario.json",
            SOURCE / "personal-process-package.json",
            Path(temporary) / "workspace",
        )
    elapsed = time.perf_counter() - started
    print(
        f"M6.1 scenario-first benchmark: {elapsed:.3f}s, "
        f"{len(manifest.artifacts)} verified artifacts"
    )
    if elapsed > MAX_SECONDS:
        raise SystemExit(
            f"materialization benchmark exceeded {MAX_SECONDS:.1f}s acceptance threshold"
        )


if __name__ == "__main__":
    main()
