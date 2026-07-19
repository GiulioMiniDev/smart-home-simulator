from __future__ import annotations

from pathlib import Path

from smart_home_sim.domain.models import Scenario


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))
