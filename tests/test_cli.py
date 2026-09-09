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


@pytest.mark.parametrize(
    ("contract", "property_name"),
    [
        ("canonical-plan", "planVersion"),
        ("compilation-report", "compilerVersion"),
    ],
)
def test_schema_command_emits_compiler_contracts(
    contract: str,
    property_name: str,
) -> None:
    result = runner.invoke(app, ["schema", "--contract", contract])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["properties"][property_name]["const"] == "1.0.0"


def test_schema_command_can_write_contract(tmp_path: Path) -> None:
    output = tmp_path / "schema.json"

    result = runner.invoke(app, ["schema", "--output", str(output)])

    assert result.exit_code == 0
    assert b"\r\n" not in output.read_bytes()
    assert json.loads(output.read_text(encoding="utf-8"))["$id"].endswith("scenario:1.0.0")


def test_project_sensors_writes_three_separated_outputs(tmp_path: Path) -> None:
    observable = tmp_path / "observable.json"
    oracle = tmp_path / "oracle.json"
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "project-sensors",
            str(EXAMPLES / "execution/mario_week.execution-trace.json"),
            str(EXAMPLES / "sensors/mario_monteverde.sensor-model.json"),
            "--bundle",
            str(EXAMPLES / "bundles/mario_week.simulation-bundle-behavior-1.1.0.json"),
            "--output",
            str(observable),
            "--oracle-output",
            str(oracle),
            "--report-output",
            str(report),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(observable.read_text())["documentType"] == "observable_sensor_log"
    assert json.loads(oracle.read_text())["documentType"] == "oracle_mapping"
    assert json.loads(report.read_text())["success"] is True


def test_project_sensors_rejects_conflicting_outputs_and_invalid_input(tmp_path: Path) -> None:
    trace = EXAMPLES / "execution/mario_week.execution-trace.json"
    model = EXAMPLES / "sensors/mario_monteverde.sensor-model.json"
    conflict = runner.invoke(
        app,
        [
            "project-sensors",
            str(trace),
            str(model),
            "--bundle",
            str(EXAMPLES / "bundles/mario_week.simulation-bundle-behavior-1.1.0.json"),
            "--output",
            str(trace),
            "--oracle-output",
            str(tmp_path / "oracle"),
            "--report-output",
            str(tmp_path / "report"),
        ],
    )
    assert conflict.exit_code != 0
    failed = runner.invoke(
        app,
        [
            "project-sensors",
            str(tmp_path / "missing"),
            str(model),
            "--bundle",
            str(EXAMPLES / "bundles/mario_week.simulation-bundle-behavior-1.1.0.json"),
            "--output",
            str(tmp_path / "observable"),
            "--oracle-output",
            str(tmp_path / "oracle"),
            "--report-output",
            str(tmp_path / "report"),
        ],
    )
    assert failed.exit_code == 1
    assert json.loads((tmp_path / "report").read_text())["success"] is False


def test_project_sensors_does_not_publish_partial_success_on_output_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_outputs: object) -> None:
        raise OSError("synthetic output failure")

    monkeypatch.setattr("smart_home_sim.cli._atomic_write_many", fail)
    observable = tmp_path / "observable.json"
    oracle = tmp_path / "oracle.json"
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "project-sensors",
            str(EXAMPLES / "execution/mario_week.execution-trace.json"),
            str(EXAMPLES / "sensors/mario_monteverde.sensor-model.json"),
            "--bundle",
            str(EXAMPLES / "bundles/mario_week.simulation-bundle-behavior-1.1.0.json"),
            "--output",
            str(observable),
            "--oracle-output",
            str(oracle),
            "--report-output",
            str(report),
        ],
    )
    assert result.exit_code == 1
    assert not observable.exists()
    assert not oracle.exists()
    failure = json.loads(report.read_text())
    assert failure["success"] is False
    assert failure["issues"][0]["code"] == "OUTPUT_WRITE_ERROR"


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


def test_ingest_authoring_output_writes_both_canonical_inputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "authoring-output"
    result = runner.invoke(
        app,
        [
            "ingest-authoring-output",
            str(EXAMPLES / "authoring/minimal.authoring-bundle.json"),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "VALID: authoring bundle" in result.stdout
    assert (output_dir / "scenario.json").is_file()
    assert (output_dir / "personal-process-package.json").is_file()


def test_run_authoring_bundle_materializes_what_ingest_and_run_synthetic_would(
    tmp_path: Path,
) -> None:
    """One command, one solve, and the same artifacts as the two-command route.

    Ingesting a bundle and then running it compiles the scenario twice: once for the validation's
    deterministic-precondition gate and once inside the materializer, which has no way to be
    handed the first result across a process boundary. Chaining them here is only worth having if
    what lands on disk is indistinguishable from the long way round.
    """
    bundle = EXAMPLES / "authoring/minimal.authoring-bundle.json"

    ingested = tmp_path / "ingested"
    ingest = runner.invoke(
        app, ["ingest-authoring-output", str(bundle), "--output-dir", str(ingested)]
    )
    assert ingest.exit_code == 0, ingest.output
    separately = tmp_path / "separately"
    run = runner.invoke(
        app,
        [
            "run-synthetic",
            str(ingested / "scenario.json"),
            str(ingested / "personal-process-package.json"),
            "--output-dir",
            str(separately),
        ],
    )
    assert run.exit_code == 0, run.output

    together = tmp_path / "together"
    inputs = tmp_path / "inputs"
    chained = runner.invoke(
        app,
        [
            "run-authoring-bundle",
            str(bundle),
            "--output-dir",
            str(together),
            "--inputs-dir",
            str(inputs),
        ],
    )
    assert chained.exit_code == 0, chained.output
    assert "VALID: authoring bundle" in chained.stdout
    assert (inputs / "scenario.json").read_bytes() == (ingested / "scenario.json").read_bytes()
    assert (inputs / "personal-process-package.json").read_bytes() == (
        ingested / "personal-process-package.json"
    ).read_bytes()

    produced = sorted(item.name for item in together.iterdir())
    assert produced == sorted(item.name for item in separately.iterdir())
    for name in produced:
        assert (together / name).read_bytes() == (separately / name).read_bytes(), name


def test_run_authoring_bundle_writes_its_report_and_refuses_to_overwrite_a_run(
    tmp_path: Path,
) -> None:
    """The report can go to a file, and a second run never lands on the first one's directory."""
    bundle = EXAMPLES / "authoring/minimal.authoring-bundle.json"
    report = tmp_path / "reports/ingestion.txt"
    output = tmp_path / "environment"

    first = runner.invoke(
        app,
        [
            "run-authoring-bundle",
            str(bundle),
            "--output-dir",
            str(output),
            "--environment-only",
            "--report-output",
            str(report),
        ],
    )
    assert first.exit_code == 0, first.output
    assert "VALID: authoring bundle" in report.read_text(encoding="utf-8")
    assert "VALID: authoring bundle" not in first.stdout
    assert "Environment written to" in first.stdout
    assert not (output / "execution-trace.json").exists()

    again = runner.invoke(
        app,
        ["run-authoring-bundle", str(bundle), "--output-dir", str(output), "--environment-only"],
    )
    assert again.exit_code == 2


def test_run_authoring_bundle_reports_a_transactional_failure_without_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **options: object) -> None:
        raise RuntimeError("home generation failed")

    monkeypatch.setattr("smart_home_sim.cli.materialize_workspace", explode)
    result = runner.invoke(
        app,
        [
            "run-authoring-bundle",
            str(EXAMPLES / "authoring/minimal.authoring-bundle.json"),
            "--output-dir",
            str(tmp_path / "never"),
        ],
    )

    assert result.exit_code == 1
    assert "failed transactionally" in result.output
    assert not (tmp_path / "never").exists()


def test_run_authoring_bundle_refuses_a_bundle_no_gate_accepted(tmp_path: Path) -> None:
    payload = json.loads(
        (EXAMPLES / "authoring/minimal.authoring-bundle.json").read_text(encoding="utf-8")
    )
    payload["personalProcessPackage"]["bindings"] = []
    bundle_path = tmp_path / "invalid.json"
    bundle_path.write_text(json.dumps(payload), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run-authoring-bundle",
            str(bundle_path),
            "--output-dir",
            str(tmp_path / "must-not-exist"),
        ],
    )

    assert result.exit_code == 1
    assert not (tmp_path / "must-not-exist").exists()


def test_ingest_authoring_output_emits_json_failure_report(tmp_path: Path) -> None:
    payload = json.loads(
        (EXAMPLES / "authoring/minimal.authoring-bundle.json").read_text(encoding="utf-8")
    )
    payload["personalProcessPackage"]["bindings"] = []
    bundle_path = tmp_path / "invalid.json"
    bundle_path.write_text(json.dumps(payload), encoding="utf-8")
    output_dir = tmp_path / "must-not-exist"

    result = runner.invoke(
        app,
        [
            "ingest-authoring-output",
            str(bundle_path),
            "--output-dir",
            str(output_dir),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["valid"] is False
    assert report["summary"]["behaviorErrorCount"] > 0
    assert report["summary"]["compilationErrorCount"] == 0
    assert not output_dir.exists()


def test_ingestion_failure_can_emit_repair_request_for_next_llm_pass(
    tmp_path: Path,
) -> None:
    payload = json.loads(
        (EXAMPLES / "authoring/minimal.authoring-bundle.json").read_text(encoding="utf-8")
    )
    payload["personalProcessPackage"]["bindings"] = []
    bundle_path = tmp_path / "invalid.json"
    bundle_path.write_text(json.dumps(payload), encoding="utf-8")
    repair_path = tmp_path / "repair/request.json"

    result = runner.invoke(
        app,
        [
            "ingest-authoring-output",
            str(bundle_path),
            "--output-dir",
            str(tmp_path / "must-not-exist"),
            "--repair-request-output",
            str(repair_path),
            "--repair-attempt",
            "3",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["valid"] is False
    assert "Authoring repair request written to" in result.stderr
    assert repair_path.is_file()
    request = json.loads(repair_path.read_text(encoding="utf-8"))
    assert request["documentType"] == "simulation_authoring_repair_request"
    assert request["attempt"] == 3
    assert request["repairRequestId"].endswith("_attempt_3")
    assert request["validationReport"]["valid"] is False
    assert json.loads(request["source"]["bundleText"]) == payload


def test_prepare_authoring_repair_command_writes_standalone_request(tmp_path: Path) -> None:
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{not-json", encoding="utf-8")
    output = tmp_path / "repair.json"

    result = runner.invoke(
        app,
        [
            "prepare-authoring-repair",
            str(malformed_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    request = json.loads(output.read_text(encoding="utf-8"))
    assert request["source"]["bundleText"] == "{not-json"
    assert request["validationReport"]["issues"][0]["code"] == "JSON_SYNTAX"


def test_prepare_authoring_repair_answers_an_accepted_bundle_s_warnings(
    tmp_path: Path,
) -> None:
    """The minimal bundle passes every gate and still warns that the resident never goes out."""
    valid_path = EXAMPLES / "authoring/minimal.authoring-bundle.json"
    output = tmp_path / "repair.json"
    accepted = runner.invoke(
        app,
        ["prepare-authoring-repair", str(valid_path), "--output", str(output)],
    )
    assert accepted.exit_code == 0
    request = json.loads(output.read_text(encoding="utf-8"))
    assert request["validationReport"]["valid"] is True
    assert [issue["code"] for issue in request["validationReport"]["issues"]] == [
        "RESIDENT_NEVER_LEAVES_HOME"
    ]
    assert any("This bundle was accepted" in line for line in request["instructions"])


def test_prepare_authoring_repair_refuses_in_place_output(tmp_path: Path) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")
    in_place = runner.invoke(
        app,
        ["prepare-authoring-repair", str(invalid_path), "--output", str(invalid_path)],
    )
    assert in_place.exit_code != 0
    assert invalid_path.read_text(encoding="utf-8") == "{not-json"


def test_compile_writes_plan_and_report(tmp_path: Path) -> None:
    plan_path = tmp_path / "nested/plan.json"
    report_path = tmp_path / "nested/report.json"
    result = runner.invoke(
        app,
        [
            "compile",
            str(EXAMPLES / "valid/minimal.json"),
            "--output",
            str(plan_path),
            "--report-output",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(plan_path.read_text())["documentType"] == "canonical_plan"
    assert json.loads(report_path.read_text())["success"] is True


def test_compile_invalid_input_returns_report_and_exit_one() -> None:
    result = runner.invoke(
        app,
        ["compile", str(EXAMPLES / "invalid/unknown_references.json")],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["issues"][0]["code"] == "INPUT_SCENARIO_INVALID"


def test_resident_profile_writes_document_page_and_matrix(tmp_path: Path) -> None:
    document = tmp_path / "nested/profile.json"

    result = runner.invoke(
        app,
        [
            "resident-profile",
            str(EXAMPLES / "execution/mario_week.execution-trace.json"),
            "--output",
            str(document),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(document.read_text(encoding="utf-8"))
    assert payload["documentType"] == "resident_profile"
    assert payload["residents"][0]["residentId"] == "resident_mario_rossi"
    assert (tmp_path / "nested/profile.html").read_text(encoding="utf-8").startswith("<!doctype")
    assert "residentId,dayType,measure" in (tmp_path / "nested/profile-heatmap.csv").read_text(
        encoding="utf-8"
    )
    assert "sleep:" in result.stdout


def test_resident_profile_reports_a_trace_it_cannot_read(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"documentType":"execution_trace"}', encoding="utf-8")

    result = runner.invoke(
        app,
        ["resident-profile", str(broken), "--output", str(tmp_path / "profile.json")],
    )

    assert result.exit_code == 1
    assert "Cannot profile this trace" in result.output
