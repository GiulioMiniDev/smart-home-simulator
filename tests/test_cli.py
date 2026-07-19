import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from smart_home_sim.cli import app

EXAMPLES = Path(__file__).parents[1] / "examples"
runner = CliRunner()


def test_validate_valid_scenario_exits_zero() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLES / "valid" / "mario_two_days.json")])

    assert result.exit_code == 0
    assert "VALID: mario_rossi_two_days" in result.stdout


def test_validate_invalid_scenario_exits_one_with_json_report() -> None:
    result = runner.invoke(
        app,
        [
            "validate",
            str(EXAMPLES / "invalid" / "unknown_references.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["valid"] is False
    assert report["summary"]["errorCount"] > 0


@pytest.mark.parametrize(
    "filename",
    [
        "dependency_cycle.json",
        "fixed_overlap.json",
        "malformed.json",
        "unknown_references.json",
    ],
)
def test_every_invalid_example_exits_one(filename: str) -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLES / "invalid" / filename)])

    assert result.exit_code == 1


def test_schema_command_uses_camel_case_contract() -> None:
    result = runner.invoke(app, ["schema"])

    assert result.exit_code == 0
    schema = json.loads(result.stdout)
    assert "scenarioId" in schema["properties"]
    assert "schemaVersion" in schema["properties"]
