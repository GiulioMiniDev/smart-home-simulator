from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from smart_home_sim import cli
from smart_home_sim.behavior import service

ROOT = Path(__file__).parents[1]
runner = CliRunner()


def test_behavior_cli_text_and_json() -> None:
    args = [
        "validate-behavior",
        str(ROOT / "examples/behavior/minimal_valid_scenario.behavior.json"),
        str(ROOT / "examples/valid/minimal.json"),
    ]
    text_result = runner.invoke(cli.app, args)
    json_result = runner.invoke(cli.app, [*args, "--format", "json"])

    assert text_result.exit_code == 0
    assert "VALID: minimal_valid_scenario__behavior" in text_result.stdout
    assert json.loads(json_result.stdout)["summary"]["coveredActivityCount"] == 2


def test_behavior_cli_can_write_report_and_custom_catalogs(tmp_path: Path) -> None:
    output = tmp_path / "nested/report.json"
    result = runner.invoke(
        cli.app,
        [
            "validate-behavior",
            str(ROOT / "examples/behavior/minimal_valid_scenario.behavior.json"),
            str(ROOT / "examples/valid/minimal.json"),
            "--activity-catalog",
            str(ROOT / "src/smart_home_sim/catalogs/activity-catalog-1.0.0.json"),
            "--variable-catalog",
            str(ROOT / "src/smart_home_sim/catalogs/variable-catalog-1.0.0.json"),
            "--action-catalog",
            str(ROOT / "src/smart_home_sim/catalogs/action-catalog-1.0.0.json"),
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text())["valid"] is True


def test_behavior_cli_invalid_package_exits_one(tmp_path: Path) -> None:
    package = json.loads(
        (ROOT / "examples/behavior/minimal_valid_scenario.behavior.json").read_text()
    )
    package["bindings"] = package["bindings"][1:]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(package), encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["validate-behavior", str(path), str(ROOT / "examples/valid/minimal.json")],
    )

    assert result.exit_code == 1
    assert "MISSING_PROCESS_BINDING" in result.stdout


def test_invalid_source_scenario_is_rejected() -> None:
    report = service.validate_behavior_files(
        ROOT / "examples/behavior/minimal_valid_scenario.behavior.json",
        ROOT / "examples/invalid/unknown_references.json",
    )

    assert not report.valid
    assert report.issues[0].code == "INPUT_SCENARIO_INVALID"


def test_missing_and_malformed_behavior_files(tmp_path: Path) -> None:
    missing = service.validate_behavior_files(
        tmp_path / "missing.json",
        ROOT / "examples/valid/minimal.json",
    )
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{bad", encoding="utf-8")
    malformed = service.validate_behavior_files(
        malformed_path,
        ROOT / "examples/valid/minimal.json",
    )

    assert missing.issues[0].code == "FILE_NOT_FOUND"
    assert malformed.issues[0].code == "JSON_SYNTAX"


def test_json_reader_rejects_duplicate_nonfinite_encoding_nesting_and_size(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cases = {
        "duplicate.json": b'{"a":1,"a":2}',
        "nonfinite.json": b'{"a":NaN}',
        "encoding.json": b"\xff",
        "nesting.json": ("[" * 257 + "]" * 257).encode(),
    }
    expected = {
        "duplicate.json": "JSON_SYNTAX",
        "nonfinite.json": "JSON_SYNTAX",
        "encoding.json": "FILE_ENCODING_ERROR",
        "nesting.json": "JSON_NESTING_TOO_DEEP",
    }
    for name, content in cases.items():
        path = tmp_path / name
        path.write_bytes(content)
        _, issue = service._read_json(path, "test")
        assert issue is not None
        assert issue.code == expected[name]

    large = tmp_path / "large.json"
    large.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(service, "MAX_SCENARIO_BYTES", 1)
    _, issue = service._read_json(large, "test")
    assert issue is not None and issue.code == "FILE_TOO_LARGE"


def test_json_reader_reports_operating_system_error(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "unreadable.json"
    path.write_text("{}", encoding="utf-8")

    def fail(_self):
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_bytes", fail)
    _, issue = service._read_json(path, "test")
    assert issue is not None and issue.code == "FILE_READ_ERROR"


def test_payload_validation_rejects_invalid_scenario_and_structure() -> None:
    catalog_root = ROOT / "src/smart_home_sim/catalogs"
    activity = json.loads((catalog_root / "activity-catalog-1.0.0.json").read_text())
    variable = json.loads((catalog_root / "variable-catalog-1.0.0.json").read_text())
    action = json.loads((catalog_root / "action-catalog-1.0.0.json").read_text())
    scenario = json.loads((ROOT / "examples/valid/minimal.json").read_text())

    invalid_scenario = dict(scenario)
    invalid_scenario["schemaVersion"] = "wrong"
    report = service.validate_behavior_payloads({}, invalid_scenario, activity, variable, action)
    assert report.issues[0].code == "INPUT_SCENARIO_INVALID"

    for package in ([], {"schemaVersion": "wrong"}, {"schemaVersion": "1.0.0"}):
        report = service.validate_behavior_payloads(package, scenario, activity, variable, action)
        assert not report.valid
        assert report.issues[0].code in {"STRUCTURE_INVALID", "UNSUPPORTED_SCHEMA_VERSION"}


def test_schema_cli_emits_all_behavior_contracts() -> None:
    contracts = {
        "activity-catalog": "activity_catalog",
        "variable-catalog": "variable_catalog",
        "action-catalog": "action_catalog",
        "personal-process-package": "personal_process_package",
        "behavior-validation-report": None,
    }
    for contract, document_type in contracts.items():
        result = runner.invoke(cli.app, ["schema", "--contract", contract])
        schema = json.loads(result.stdout)
        assert result.exit_code == 0
        if document_type:
            assert schema["properties"]["documentType"]["const"] == document_type
        else:
            assert schema["properties"]["validatorVersion"]["const"] == "1.0.0"
