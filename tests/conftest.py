from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
EXAMPLES = PROJECT_ROOT / "examples"


@pytest.fixture
def valid_payload() -> dict[str, Any]:
    payload = json.loads((EXAMPLES / "valid/minimal.json").read_text(encoding="utf-8"))
    return copy.deepcopy(payload)


@pytest.fixture
def all_example_files() -> Iterator[Path]:
    yield from sorted(EXAMPLES.glob("*/*.json"))
