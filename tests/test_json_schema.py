from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from smart_home_sim.domain.compilation import COMPILATION_ISSUE_CODES, CompilationReport
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.domain.report import ValidationReport
from smart_home_sim.validation.codes import STABLE_ISSUE_CODES

PROJECT_ROOT = Path(__file__).parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas/scenario-1.0.0.schema.json"
REPORT_SCHEMA_PATH = PROJECT_ROOT / "schemas/validation-report-1.0.0.schema.json"
PLAN_SCHEMA_PATH = PROJECT_ROOT / "schemas/canonical-plan-1.0.0.schema.json"
COMPILATION_SCHEMA_PATH = PROJECT_ROOT / "schemas/compilation-report-1.0.0.schema.json"


def load_schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_distributed_schema_is_valid_draft_2020_12() -> None:
    schema = load_schema()

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "urn:smart-home-simulator:schema:scenario:1.0.0"


def test_distributed_schema_exactly_matches_the_models() -> None:
    assert load_schema() == Scenario.model_json_schema(by_alias=True)
    report_schema = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert report_schema == ValidationReport.model_json_schema(by_alias=True)
    Draft202012Validator.check_schema(report_schema)
    assert set(report_schema["$defs"]["ValidationIssue"]["properties"]["code"]["enum"]) == (
        STABLE_ISSUE_CODES
    )


def test_frozen_schema_checksums_match() -> None:
    for schema_path in (
        SCHEMA_PATH,
        REPORT_SCHEMA_PATH,
        PLAN_SCHEMA_PATH,
        COMPILATION_SCHEMA_PATH,
    ):
        checksum_path = schema_path.with_suffix(".sha256")
        expected = checksum_path.read_text(encoding="utf-8").split()[0]
        assert sha256(schema_path.read_bytes()).hexdigest() == expected


def test_golden_report_satisfies_its_distributed_schema() -> None:
    schema = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(
        (PROJECT_ROOT / "tests/golden/unknown_references.report.json").read_text(encoding="utf-8")
    )

    assert list(Draft202012Validator(schema).iter_errors(report)) == []


def test_compiler_schemas_match_models_and_compiled_examples() -> None:
    plan_schema = json.loads(PLAN_SCHEMA_PATH.read_text())
    report_schema = json.loads(COMPILATION_SCHEMA_PATH.read_text())
    assert plan_schema == CanonicalPlan.model_json_schema(by_alias=True)
    assert report_schema == CompilationReport.model_json_schema(by_alias=True)
    Draft202012Validator.check_schema(plan_schema)
    Draft202012Validator.check_schema(report_schema)
    assert set(report_schema["$defs"]["CompilationIssue"]["properties"]["code"]["enum"]) == (
        COMPILATION_ISSUE_CODES
    )
    plan = json.loads((PROJECT_ROOT / "examples/compiled/mario_week.plan.json").read_text())
    report = json.loads(
        (PROJECT_ROOT / "examples/compiled/mario_week.compilation-report.json").read_text()
    )
    assert list(Draft202012Validator(plan_schema).iter_errors(plan)) == []
    assert list(Draft202012Validator(report_schema).iter_errors(report)) == []


def test_both_valid_examples_satisfy_distributed_schema() -> None:
    validator = Draft202012Validator(load_schema())

    for path in sorted((PROJECT_ROOT / "examples/valid").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert list(validator.iter_errors(payload)) == [], path


def test_distributed_schema_forbids_unknown_properties() -> None:
    validator = Draft202012Validator(load_schema())
    payload = json.loads((PROJECT_ROOT / "examples/valid/minimal.json").read_text())
    payload["typo"] = True

    assert any(
        error.validator == "additionalProperties" for error in validator.iter_errors(payload)
    )
