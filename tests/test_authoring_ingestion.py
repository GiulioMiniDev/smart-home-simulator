from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from smart_home_sim.authoring.service import (
    ingest_authoring_file,
    prepare_authoring_repair_file,
    validate_authoring_file,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/authoring/minimal.authoring-bundle.json"


def _payload() -> dict[str, object]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_valid_bundle_is_published_as_two_valid_canonical_documents(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated/mario"

    report = ingest_authoring_file(EXAMPLE, output_dir)

    assert report.valid
    assert report.scenario_id == "minimal_valid_scenario"
    assert report.package_id == "minimal_valid_scenario__behavior"
    assert report.ingestor_version == "1.1.0"
    assert report.canonical_plan_sha256 is not None
    assert report.summary.compilation_error_count == 0
    assert {item.filename for item in report.artifacts} == {
        "scenario.json",
        "personal-process-package.json",
    }
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "personal-process-package.json",
        "scenario.json",
    ]
    scenario = json.loads((output_dir / "scenario.json").read_text(encoding="utf-8"))
    behavior = json.loads(
        (output_dir / "personal-process-package.json").read_text(encoding="utf-8")
    )
    assert scenario["scenarioId"] == behavior["sourceScenarioId"]
    for artifact in report.artifacts:
        content = (output_dir / artifact.filename).read_bytes()
        assert b"\r\n" not in content
        assert sha256(content).hexdigest() == artifact.sha256


def test_validation_is_deterministic_and_does_not_write(tmp_path: Path) -> None:
    first = validate_authoring_file(EXAMPLE)
    second = validate_authoring_file(EXAMPLE)

    assert first == second
    assert list(tmp_path.iterdir()) == []


def test_invalid_scenario_blocks_behavior_validation_and_output(tmp_path: Path) -> None:
    payload = _payload()
    payload["scenario"]["residents"] = []  # type: ignore[index]
    path = tmp_path / "invalid-scenario.json"
    _write(path, payload)
    output_dir = tmp_path / "output"

    report = ingest_authoring_file(path, output_dir)

    assert not report.valid
    assert not output_dir.exists()
    assert report.summary.scenario_error_count > 0
    assert report.summary.compilation_error_count == 1
    assert {item.code for item in report.issues} >= {
        "STRUCTURE_INVALID",
        "COMPILATION_VALIDATION_SKIPPED",
        "BEHAVIOR_VALIDATION_SKIPPED",
    }


def test_compilation_failure_rejects_bundle_even_when_nested_contracts_are_valid(
    tmp_path: Path,
) -> None:
    payload = _payload()
    first_activity = payload["scenario"]["days"][0]["activities"][0]  # type: ignore[index]
    first_activity["activation"] = {
        "mode": "conditional",
        "condition": {"fact": "rain", "operator": "truthy"},
    }
    path = tmp_path / "cross-branch.json"
    _write(path, payload)
    output_dir = tmp_path / "output"

    report = ingest_authoring_file(path, output_dir)

    assert not report.valid
    assert report.summary.scenario_error_count == 0
    assert report.summary.compilation_error_count > 0
    assert report.summary.behavior_error_count == 0
    assert "CROSS_BRANCH_DEPENDENCY" in {item.code for item in report.issues}
    assert all(
        item.path.startswith("$.scenario") for item in report.issues if item.stage == "compilation"
    )
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("invalid_package", "expected_code"),
    [
        ("missing_binding.json", "MISSING_PROCESS_BINDING"),
        ("unbounded_cycle.json", "GRAPH_CYCLE_UNBOUNDED"),
        ("unknown_action.json", "UNKNOWN_ACTION_TYPE"),
    ],
)
def test_behavior_failures_reject_whole_bundle(
    tmp_path: Path,
    invalid_package: str,
    expected_code: str,
) -> None:
    payload = _payload()
    payload["personalProcessPackage"] = json.loads(
        (ROOT / "examples/behavior/invalid" / invalid_package).read_text(encoding="utf-8")
    )
    path = tmp_path / invalid_package
    _write(path, payload)
    output_dir = tmp_path / "output"

    report = ingest_authoring_file(path, output_dir)

    assert not report.valid
    assert not output_dir.exists()
    assert expected_code in {item.code for item in report.issues}
    assert all(
        item.path.startswith("$.personalProcessPackage")
        for item in report.issues
        if item.stage == "behavior"
    )


def test_existing_output_directory_is_never_modified(tmp_path: Path) -> None:
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    sentinel = output_dir / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")

    report = ingest_authoring_file(EXAMPLE, output_dir)

    assert not report.valid
    assert [item.code for item in report.issues] == ["OUTPUT_DIRECTORY_EXISTS"]
    assert sentinel.read_text(encoding="utf-8") == "user data"
    assert sorted(path.name for path in output_dir.iterdir()) == ["keep.txt"]


def test_publish_failure_removes_temporary_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "result"

    def fail_rename(source: Path, destination: Path) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr("smart_home_sim.authoring.service.os.rename", fail_rename)

    report = ingest_authoring_file(EXAMPLE, output_dir)

    assert not report.valid
    assert [item.code for item in report.issues] == ["OUTPUT_WRITE_ERROR"]
    assert not output_dir.exists()
    assert list(tmp_path.glob(".result.tmp-*")) == []


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '{"schemaVersion":"1.0.0","schemaVersion":"1.0.0"}',
        '{"value":NaN}',
    ],
)
def test_unsafe_or_malformed_json_is_rejected_without_output(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(raw, encoding="utf-8")
    output_dir = tmp_path / "output"

    report = ingest_authoring_file(path, output_dir)

    assert not report.valid
    assert not output_dir.exists()
    assert report.issues[0].stage == "bundle"


def test_envelope_rejects_unknown_and_missing_properties(tmp_path: Path) -> None:
    payload = _payload()
    del payload["documentType"]
    payload["explanation"] = "not allowed"
    path = tmp_path / "wrong-envelope.json"
    _write(path, payload)

    report = validate_authoring_file(path).report

    assert not report.valid
    paths = {item.path for item in report.issues}
    assert "$.documentType" in paths
    assert "$.explanation" in paths


def test_distributed_prompt_1_2_is_single_self_contained_authoring_request() -> None:
    prompt = (ROOT / "prompts/generate-simulation-inputs-1.2.0.md").read_text(encoding="utf-8")

    assert "{{BUNDLE_SCHEMA_JSON}}" not in prompt
    assert "{{ACTIVITY_CATALOG_JSON}}" not in prompt
    assert "{{VARIABLE_CATALOG_JSON}}" not in prompt
    assert "{{ACTION_CATALOG_JSON}}" not in prompt
    assert "{{PERSON_AND_CASE_DESCRIPTION}}" in prompt
    assert "Return exactly one JSON object and nothing else." in prompt
    assert "`generatorVersion`: `1.2.0`" in prompt
    assert "A fallback may replace only an activity whose activation mode is `always`." in prompt
    assert "Do not return a wake-up model" in prompt
    assert "full plan compilation" in prompt
    assert "Mandatory ValueExpression and reference-kind compatibility" in prompt
    assert "A scenario resource is not automatically a" in prompt
    assert '"itemRole": {"source": "literal", "value": "coffee_preparation_item"}' in prompt
    assert '"itemRole": {"source": "activity_resource", "index": 0}' in prompt
    assert "zero `ACTION_ARGUMENT_TYPE_MISMATCH` possibilities" in prompt
    compact_schema = json.dumps(
        json.loads((ROOT / "schemas/simulation-authoring-bundle-1.0.0.schema.json").read_text()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert compact_schema in prompt
    for filename in (
        "activity-catalog-1.0.0.json",
        "variable-catalog-1.0.0.json",
        "action-catalog-1.0.0.json",
    ):
        compact = json.dumps(
            json.loads((ROOT / "src/smart_home_sim/catalogs" / filename).read_text()),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert compact in prompt


def test_invalid_bundle_produces_deterministic_self_contained_repair_request(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["personalProcessPackage"]["bindings"] = []  # type: ignore[index]
    path = tmp_path / "rejected.json"
    _write(path, payload)

    first = prepare_authoring_repair_file(path, attempt=2)
    second = prepare_authoring_repair_file(path, attempt=2)

    assert first == second
    assert not first.report.valid
    assert first.request is not None
    request = first.request
    assert request.attempt == 2
    assert request.repair_request_id.endswith("_attempt_2")
    assert request.source.bundle_text == path.read_text(encoding="utf-8")
    assert request.source.sha256 == sha256(path.read_bytes()).hexdigest()
    assert request.validation_report == first.report
    assert request.policy.preserve_valid_content is True
    assert request.policy.return_complete_bundle is True
    assert request.policy.return_json_only is True
    assert "STRUCTURE_INVALID" in {issue.code for issue in request.validation_report.issues}
    assert request.authoritative_context.simulation_authoring_bundle_schema["$id"].endswith(
        "simulation-authoring-bundle:1.0.0"
    )
    assert request.authoritative_context.action_catalog["catalogId"] == "smart_home_action_catalog"
    serialized = request.model_dump_json(by_alias=True)
    assert "source.bundleText" in request.instructions[0]
    assert "Return exactly one JSON object and nothing else." in serialized
    repair_schema = json.loads(
        (ROOT / "schemas/authoring-repair-request-1.0.0.schema.json").read_text()
    )
    assert list(Draft202012Validator(repair_schema).iter_errors(json.loads(serialized))) == []


def test_repair_request_supports_malformed_but_bounded_utf8_json(tmp_path: Path) -> None:
    path = tmp_path / "malformed.json"
    path.write_text('{"schemaVersion":"1.0.0",', encoding="utf-8")

    preparation = prepare_authoring_repair_file(path)

    assert preparation.request is not None
    assert preparation.request.source.bundle_text == path.read_text(encoding="utf-8")
    assert [issue.code for issue in preparation.request.validation_report.issues] == ["JSON_SYNTAX"]


def test_valid_or_unembeddable_bundle_does_not_create_repair_request(tmp_path: Path) -> None:
    valid = prepare_authoring_repair_file(EXAMPLE)
    assert valid.request is None
    assert valid.report.valid
    assert "already valid" in (valid.unavailable_reason or "")

    non_utf8_path = tmp_path / "binary.json"
    non_utf8_path.write_bytes(b"\xff")
    non_utf8 = prepare_authoring_repair_file(non_utf8_path)
    assert non_utf8.request is None
    assert not non_utf8.report.valid
    assert "not UTF-8" in (non_utf8.unavailable_reason or "")


def test_repair_attempt_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        prepare_authoring_repair_file(EXAMPLE, attempt=0)


def test_repaired_full_bundle_reenters_normal_ingestion(tmp_path: Path) -> None:
    payload = _payload()
    valid_bindings = payload["personalProcessPackage"]["bindings"]  # type: ignore[index]
    payload["personalProcessPackage"]["bindings"] = []  # type: ignore[index]
    rejected_path = tmp_path / "rejected.json"
    _write(rejected_path, payload)

    preparation = prepare_authoring_repair_file(rejected_path)
    assert preparation.request is not None

    repaired_payload = json.loads(preparation.request.source.bundle_text)
    repaired_payload["personalProcessPackage"]["bindings"] = valid_bindings
    repaired_path = tmp_path / "repaired.json"
    _write(repaired_path, repaired_payload)

    report = ingest_authoring_file(repaired_path, tmp_path / "accepted")
    assert report.valid
    assert report.summary.error_count == 0
