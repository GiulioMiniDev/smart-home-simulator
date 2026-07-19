import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from smart_home_sim.cli import app

EXAMPLES = Path(__file__).parents[1] / "examples"
runner = CliRunner()


def test_validate_valid_scenario_exits_zero() -> None:
    result = runner.invoke(app, ["validate", str(EXAMPLES / "valid" / "mario_week.json")])

    assert result.exit_code == 0
    assert "VALID: mario_rossi_week_2026_10_12" in result.stdout


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
    assert schema["properties"]["schemaVersion"]["const"] == "1.0.0"


def test_schema_command_can_emit_validation_report_contract() -> None:
    result = runner.invoke(app, ["schema", "--contract", "validation-report"])

    assert result.exit_code == 0
    schema = json.loads(result.stdout)
    assert schema["properties"]["validatorVersion"]["const"] == "1.0.0"


def test_schema_command_can_write_contract(tmp_path: Path) -> None:
    output = tmp_path / "schema.json"

    result = runner.invoke(app, ["schema", "--output", str(output)])

    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["$id"].endswith("scenario:1.0.0")


def test_warning_can_be_promoted_to_failure(tmp_path: Path) -> None:
    payload = json.loads((EXAMPLES / "valid/minimal.json").read_text(encoding="utf-8"))
    payload["declaredConstraints"] = ["same", "same"]
    path = tmp_path / "warning.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    normal = runner.invoke(app, ["validate", str(path)])
    strict = runner.invoke(app, ["validate", str(path), "--warnings-as-errors"])

    assert normal.exit_code == 0
    assert strict.exit_code == 1


def test_validate_can_write_json_report(tmp_path: Path) -> None:
    output = tmp_path / "nested/report.json"
    result = runner.invoke(
        app,
        [
            "validate",
            str(EXAMPLES / "valid/minimal.json"),
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["valid"] is True
