from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.validation.service import validate_file, validate_payload

EXAMPLES = Path(__file__).parents[1] / "examples"


@pytest.mark.parametrize("path", sorted((EXAMPLES / "valid").glob("*.json")))
def test_every_valid_example_passes(path: Path) -> None:
    report = validate_file(path)

    assert report.valid, report.model_dump_json(indent=2)
    assert report.summary.error_count == 0


@pytest.mark.parametrize("path", sorted((EXAMPLES / "invalid").glob("*.json")))
def test_every_invalid_example_fails(path: Path) -> None:
    assert not validate_file(path).valid


def test_full_week_is_the_primary_acceptance_scenario() -> None:
    path = EXAMPLES / "valid/mario_week.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = validate_file(path)

    assert report.valid
    assert report.scenario_id == "mario_rossi_week_2026_10_12"
    assert len(payload["days"]) == 7
    assert sum(len(day["activities"]) for day in payload["days"]) == 173
    assert len(payload["commitments"]) == 7
    assert len(payload["runtimeEventCandidates"]) == 5


def test_strict_contract_rejects_unknown_fields(valid_payload: dict[str, Any]) -> None:
    valid_payload["unexpectedTypo"] = True

    report = validate_payload(valid_payload)

    assert not report.valid
    assert report.issues[0].code == "STRUCTURE_INVALID"
    assert report.issues[0].path == "$.unexpectedTypo"


def test_strict_contract_rejects_type_coercion(valid_payload: dict[str, Any]) -> None:
    valid_payload["seed"] = "1"

    report = validate_payload(valid_payload)

    assert not report.valid
    assert report.issues[0].code == "STRUCTURE_INVALID"
    assert report.issues[0].path == "$.seed"


def test_structure_errors_have_machine_readable_details(valid_payload: dict[str, Any]) -> None:
    valid_payload["days"][0]["activities"][0]["duration"]["minimumMinutes"] = -1.0

    report = validate_payload(valid_payload)

    assert not report.valid
    assert report.issues[0].path.endswith(".duration.minimumMinutes")
    assert report.issues[0].details["type"] == "greater_than"


def test_report_order_and_serialization_are_deterministic() -> None:
    path = EXAMPLES / "invalid/unknown_references.json"

    first = validate_file(path).model_dump_json(by_alias=True)
    second = validate_file(path).model_dump_json(by_alias=True)

    assert first == second


def test_public_report_contract_matches_golden_file() -> None:
    report = validate_file(EXAMPLES / "invalid/unknown_references.json")
    expected = (Path(__file__).parent / "golden/unknown_references.report.json").read_text(
        encoding="utf-8"
    )

    assert report.model_dump_json(by_alias=True, indent=2) + "\n" == expected
