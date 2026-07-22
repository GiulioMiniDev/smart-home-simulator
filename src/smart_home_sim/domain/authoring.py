from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, JsonValue
from pydantic.json_schema import (
    DEFAULT_REF_TEMPLATE,
    GenerateJsonSchema,
    JsonSchemaMode,
    JsonSchemaValue,
)

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.behavior_report import BEHAVIOR_ISSUE_CODES
from smart_home_sim.domain.codes import STABLE_ISSUE_CODES
from smart_home_sim.domain.compilation import COMPILATION_ISSUE_CODES
from smart_home_sim.domain.models import Scenario

AUTHORING_ISSUE_CODES = frozenset(
    {
        *STABLE_ISSUE_CODES,
        *BEHAVIOR_ISSUE_CODES,
        *COMPILATION_ISSUE_CODES,
        "BEHAVIOR_VALIDATION_SKIPPED",
        "BUNDLE_STRUCTURE_INVALID",
        "COMPILATION_VALIDATION_SKIPPED",
        "DETERMINISTIC_PRECONDITION_FAILED",
        "OUTPUT_DIRECTORY_EXISTS",
        "OUTPUT_WRITE_ERROR",
    }
)


def _remove_nested_resource_ids(value: object, *, root: bool = False) -> None:
    """Keep composed JSON Schemas in one resource so local refs resolve at the root."""
    if isinstance(value, dict):
        if not root:
            value.pop("$id", None)
            value.pop("$schema", None)
        for nested in value.values():
            _remove_nested_resource_ids(nested)
    elif isinstance(value, list):
        for nested in value:
            _remove_nested_resource_ids(nested)


class SimulationAuthoringBundle(ContractModel):
    """Transport envelope returned by an external LLM.

    The nested contracts remain independently authoritative. This envelope only makes a
    two-document chatbot response unambiguous and machine-readable.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:simulation-authoring-bundle:1.0.0",
            "title": "Smart Home Simulation Authoring Bundle 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["simulation_authoring_bundle"] = "simulation_authoring_bundle"
    scenario: Scenario
    personal_process_package: PersonalProcessPackage

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
    ) -> JsonSchemaValue:
        schema = super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
        )

        _remove_nested_resource_ids(schema, root=True)
        return schema


class AuthoringIngestionIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(AUTHORING_ISSUE_CODES)})
    severity: Literal["error", "warning"] = "error"
    stage: Literal["bundle", "scenario", "compilation", "behavior", "output"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class AuthoringArtifact(ContractModel):
    filename: Literal["scenario.json", "personal-process-package.json"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AuthoringIngestionSummary(ContractModel):
    scenario_error_count: int = Field(ge=0)
    compilation_error_count: int = Field(ge=0)
    behavior_error_count: int = Field(ge=0)
    output_error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    error_count: int = Field(ge=0)


class AuthoringIngestionReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:authoring-ingestion-report:1.1.0",
            "title": "Smart Home Authoring Ingestion Report 1.1.0",
        },
    )

    ingestor_version: Literal["1.1.0"] = "1.1.0"
    valid: bool
    bundle_version: str | None = None
    scenario_id: str | None = None
    package_id: str | None = None
    canonical_plan_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issues: list[AuthoringIngestionIssue] = Field(default_factory=list)
    artifacts: list[AuthoringArtifact] = Field(default_factory=list)
    summary: AuthoringIngestionSummary

    @classmethod
    def from_issues(
        cls,
        issues: list[AuthoringIngestionIssue],
        *,
        bundle_version: str | None = None,
        scenario_id: str | None = None,
        package_id: str | None = None,
        canonical_plan_sha256: str | None = None,
        artifacts: list[AuthoringArtifact] | None = None,
    ) -> AuthoringIngestionReport:
        error_count = sum(item.severity == "error" for item in issues)
        return cls(
            valid=error_count == 0,
            bundle_version=bundle_version,
            scenario_id=scenario_id,
            package_id=package_id,
            canonical_plan_sha256=canonical_plan_sha256,
            issues=issues,
            artifacts=artifacts or [],
            summary=AuthoringIngestionSummary(
                scenario_error_count=sum(
                    item.severity == "error" and item.stage == "scenario" for item in issues
                ),
                compilation_error_count=sum(
                    item.severity == "error" and item.stage == "compilation" for item in issues
                ),
                behavior_error_count=sum(
                    item.severity == "error" and item.stage == "behavior" for item in issues
                ),
                output_error_count=sum(
                    item.severity == "error" and item.stage == "output" for item in issues
                ),
                warning_count=sum(item.severity == "warning" for item in issues),
                error_count=error_count,
            ),
        )


class AuthoringRepairPolicy(ContractModel):
    """Non-negotiable constraints for one external-LLM repair pass."""

    preserve_valid_content: Literal[True] = True
    smallest_coherent_change: Literal[True] = True
    resolve_every_reported_error: Literal[True] = True
    do_not_redefine_contracts_or_catalogs: Literal[True] = True
    return_complete_bundle: Literal[True] = True
    return_json_only: Literal[True] = True


class AuthoringRepairSource(ContractModel):
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_text: str


class AuthoringRepairContext(ContractModel):
    simulation_authoring_bundle_schema: dict[str, JsonValue]
    activity_catalog: dict[str, JsonValue]
    variable_catalog: dict[str, JsonValue]
    action_catalog: dict[str, JsonValue]


class AuthoringRepairRequest(ContractModel):
    """Self-contained request for repairing one rejected authoring bundle.

    The artifact is sent to an external LLM. It embeds the rejected source verbatim,
    deterministic diagnostics and the authoritative contracts needed to repair it without
    regenerating valid content from scratch.
    """

    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:authoring-repair-request:1.0.0",
            "title": "Smart Home Authoring Repair Request 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["simulation_authoring_repair_request"] = (
        "simulation_authoring_repair_request"
    )
    repair_prompt_version: Literal["1.0.0"] = "1.0.0"
    repair_request_id: str = Field(pattern=r"^repair_[0-9a-f]{16}_attempt_[1-9][0-9]*$")
    attempt: int = Field(ge=1)
    task: Literal[
        "Repair the rejected simulation authoring bundle using the diagnostics and "
        "authoritative context in this request."
    ] = (
        "Repair the rejected simulation authoring bundle using the diagnostics and "
        "authoritative context in this request."
    )
    instructions: list[str] = Field(min_length=1)
    policy: AuthoringRepairPolicy = Field(default_factory=AuthoringRepairPolicy)
    source: AuthoringRepairSource
    validation_report: AuthoringIngestionReport
    authoritative_context: AuthoringRepairContext

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
    ) -> JsonSchemaValue:
        schema = super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
        )
        _remove_nested_resource_ids(schema, root=True)
        return schema
