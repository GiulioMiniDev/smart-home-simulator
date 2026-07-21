from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from smart_home_sim.materialization import materialize_workspace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "generated/mario_rossi_2026_10_30_ingested"
TARGET = ROOT / "examples/materialization/mario_rossi_2026_10_30"


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary) / "workspace"
        materialize_workspace(
            SOURCE / "scenario.json",
            SOURCE / "personal-process-package.json",
            workspace,
        )
        if TARGET.exists():
            shutil.rmtree(TARGET)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(workspace, TARGET)


if __name__ == "__main__":
    main()
