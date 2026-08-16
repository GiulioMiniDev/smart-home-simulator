from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
EXAMPLES = PROJECT_ROOT / "examples"


@pytest.fixture(autouse=True)
def isolated_application_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Keep every test off the real installation's settings file.

    The configuration is deliberately stored outside the workspace, at a fixed path in the user's
    home folder, so a test that saved a workspace location would move the machine's own
    installation the next time the researcher started it.
    """
    home = tmp_path_factory.mktemp("application-home")
    monkeypatch.setenv("SMART_HOME_SIM_HOME", str(home))
    monkeypatch.delenv("SMART_HOME_SIM_DATA_DIR", raising=False)
    monkeypatch.delenv("SMART_HOME_SIM_WORKSPACE", raising=False)
    monkeypatch.delenv("SMART_HOME_SIM_SUPERVISED", raising=False)
    return home


@pytest.fixture
def valid_payload() -> dict[str, Any]:
    payload = json.loads((EXAMPLES / "valid/minimal.json").read_text(encoding="utf-8"))
    return copy.deepcopy(payload)


@pytest.fixture
def all_example_files() -> Iterator[Path]:
    yield from sorted(EXAMPLES.glob("*/*.json"))
