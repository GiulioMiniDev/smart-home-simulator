from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from smart_home_sim.domain.authoring import (
    AUTHORING_ISSUE_CODES,
    AuthoringIngestionReport,
    AuthoringRepairRequest,
    SimulationAuthoringBundle,
)
from smart_home_sim.domain.batch import SimulationBatchManifest, SimulationBatchReport
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    ActivityCatalog,
    PersonalProcessPackage,
    VariableCatalog,
)
from smart_home_sim.domain.behavior_report import (
    BEHAVIOR_ISSUE_CODES,
    BehaviorValidationReport,
)
from smart_home_sim.domain.compilation import COMPILATION_ISSUE_CODES, CompilationReport
from smart_home_sim.domain.environment import (
    ENVIRONMENT_ISSUE_CODES,
    EnvironmentValidationReport,
    HomeModel,
    SimulationBundle,
)
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan
from smart_home_sim.domain.report import ValidationReport
from smart_home_sim.validation.codes import STABLE_ISSUE_CODES

PROJECT_ROOT = Path(__file__).parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas/scenario-1.0.0.schema.json"
REPORT_SCHEMA_PATH = PROJECT_ROOT / "schemas/validation-report-1.0.0.schema.json"
PLAN_SCHEMA_PATH = PROJECT_ROOT / "schemas/canonical-plan-1.0.0.schema.json"
COMPILATION_SCHEMA_PATH = PROJECT_ROOT / "schemas/compilation-report-1.0.0.schema.json"
BEHAVIOR_SCHEMAS = {
    "activity-catalog-1.0.0.schema.json": ActivityCatalog,
    "variable-catalog-1.0.0.schema.json": VariableCatalog,
    "action-catalog-1.0.0.schema.json": ActionCatalog,
    "personal-process-package-1.0.0.schema.json": PersonalProcessPackage,
    "behavior-validation-report-1.0.0.schema.json": BehaviorValidationReport,
}
AUTHORING_SCHEMAS = {
    "simulation-authoring-bundle-1.0.0.schema.json": SimulationAuthoringBundle,
    "authoring-ingestion-report-1.1.0.schema.json": AuthoringIngestionReport,
    "authoring-repair-request-1.0.0.schema.json": AuthoringRepairRequest,
}
HISTORICAL_AUTHORING_REPORT_SCHEMA = (
    PROJECT_ROOT / "schemas/authoring-ingestion-report-1.0.0.schema.json"
)
ENVIRONMENT_SCHEMAS = {
    "home-model-1.0.0.schema.json": HomeModel,
    "environment-validation-report-1.0.0.schema.json": EnvironmentValidationReport,
    "simulation-bundle-1.0.0.schema.json": SimulationBundle,
}
BATCH_SCHEMAS = {
    "simulation-batch-manifest-1.0.0.schema.json": SimulationBatchManifest,
    "simulation-batch-report-1.0.0.schema.json": SimulationBatchReport,
}


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
        *(PROJECT_ROOT / "schemas" / name for name in BEHAVIOR_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in AUTHORING_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in ENVIRONMENT_SCHEMAS),
        *(PROJECT_ROOT / "schemas" / name for name in BATCH_SCHEMAS),
        HISTORICAL_AUTHORING_REPORT_SCHEMA,
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


def test_behavior_schemas_match_models_and_are_valid() -> None:
    for filename, model in BEHAVIOR_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
    report_schema = json.loads(
        (PROJECT_ROOT / "schemas/behavior-validation-report-1.0.0.schema.json").read_text()
    )
    assert (
        set(report_schema["$defs"]["BehaviorValidationIssue"]["properties"]["code"]["enum"])
        == BEHAVIOR_ISSUE_CODES
    )


def test_distributed_catalogs_and_behavior_examples_satisfy_schemas() -> None:
    catalog_files = {
        "activity-catalog-1.0.0.json": "activity-catalog-1.0.0.schema.json",
        "variable-catalog-1.0.0.json": "variable-catalog-1.0.0.schema.json",
        "action-catalog-1.0.0.json": "action-catalog-1.0.0.schema.json",
    }
    for catalog_name, schema_name in catalog_files.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / schema_name).read_text())
        payload = json.loads(
            (PROJECT_ROOT / "src/smart_home_sim/catalogs" / catalog_name).read_text()
        )
        assert list(Draft202012Validator(schema).iter_errors(payload)) == []

    package_schema = json.loads(
        (PROJECT_ROOT / "schemas/personal-process-package-1.0.0.schema.json").read_text()
    )
    for path in sorted((PROJECT_ROOT / "examples/behavior").glob("*.json")):
        payload = json.loads(path.read_text())
        assert list(Draft202012Validator(package_schema).iter_errors(payload)) == [], path


def test_authoring_schemas_match_models_and_example_bundle() -> None:
    for filename, model in AUTHORING_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
    report_schema = json.loads(
        (PROJECT_ROOT / "schemas/authoring-ingestion-report-1.1.0.schema.json").read_text()
    )
    assert (
        set(report_schema["$defs"]["AuthoringIngestionIssue"]["properties"]["code"]["enum"])
        == AUTHORING_ISSUE_CODES
    )
    bundle_schema = json.loads(
        (PROJECT_ROOT / "schemas/simulation-authoring-bundle-1.0.0.schema.json").read_text()
    )
    bundle = json.loads(
        (PROJECT_ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text()
    )
    assert list(Draft202012Validator(bundle_schema).iter_errors(bundle)) == []
    historical_report_schema = json.loads(
        HISTORICAL_AUTHORING_REPORT_SCHEMA.read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(historical_report_schema)
    assert historical_report_schema["properties"]["ingestorVersion"]["const"] == "1.0.0"


def test_environment_schemas_match_models_and_golden_artifacts() -> None:
    for filename, model in ENVIRONMENT_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
    report_schema = json.loads(
        (PROJECT_ROOT / "schemas/environment-validation-report-1.0.0.schema.json").read_text()
    )
    assert (
        set(report_schema["$defs"]["EnvironmentValidationIssue"]["properties"]["code"]["enum"])
        == ENVIRONMENT_ISSUE_CODES
    )
    artifacts = [
        ("home-model-1.0.0.schema.json", "examples/environment/mario_monteverde.home.json"),
        (
            "environment-validation-report-1.0.0.schema.json",
            "examples/bundles/mario_week.environment-report.json",
        ),
        (
            "simulation-bundle-1.0.0.schema.json",
            "examples/bundles/mario_week.simulation-bundle.json",
        ),
    ]
    for schema_name, artifact_name in artifacts:
        schema = json.loads((PROJECT_ROOT / "schemas" / schema_name).read_text())
        payload = json.loads((PROJECT_ROOT / artifact_name).read_text())
        assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_batch_schemas_match_models_and_manifest_example() -> None:
    for filename, model in BATCH_SCHEMAS.items():
        schema = json.loads((PROJECT_ROOT / "schemas" / filename).read_text())
        assert schema == model.model_json_schema(by_alias=True)
        Draft202012Validator.check_schema(schema)
    manifest_schema = json.loads(
        (PROJECT_ROOT / "schemas/simulation-batch-manifest-1.0.0.schema.json").read_text()
    )
    manifest = json.loads((PROJECT_ROOT / "examples/batch/mario_week.seed-sweep.json").read_text())
    assert list(Draft202012Validator(manifest_schema).iter_errors(manifest)) == []
