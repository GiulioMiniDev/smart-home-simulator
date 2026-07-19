import json
from pathlib import Path

import pytest

from smart_home_sim.validation.service import validate_file, validate_payload

EXAMPLES = Path(__file__).parents[1] / "examples"


def test_valid_two_day_scenario() -> None:
    report = validate_file(EXAMPLES / "valid" / "mario_two_days.json")

    assert report.valid
    assert report.scenario_id == "mario_rossi_two_days"
    assert report.summary.error_count == 0


@pytest.mark.parametrize(
    ("filename", "expected_code"),
    [
        ("unknown_references.json", "UNKNOWN_ACTOR"),
        ("dependency_cycle.json", "DEPENDENCY_CYCLE"),
        ("fixed_overlap.json", "FIXED_ACTIVITY_OVERLAP"),
        ("malformed.json", "JSON_SYNTAX"),
    ],
)
def test_invalid_examples(filename: str, expected_code: str) -> None:
    report = validate_file(EXAMPLES / "invalid" / filename)

    assert not report.valid
    assert expected_code in {item.code for item in report.issues}


def test_structure_errors_have_json_paths() -> None:
    payload = json.loads((EXAMPLES / "valid" / "mario_two_days.json").read_text())
    payload["days"][0]["activities"][0]["timing"]["duration"]["minimumMinutes"] = -1

    report = validate_payload(payload)

    assert not report.valid
    assert report.issues[0].code == "STRUCTURE_INVALID"
    assert report.issues[0].path.startswith("$.days[0].activities[0]")


def test_report_is_deterministic() -> None:
    path = EXAMPLES / "invalid" / "unknown_references.json"

    assert validate_file(path).model_dump_json() == validate_file(path).model_dump_json()
