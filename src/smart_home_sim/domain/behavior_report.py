from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from smart_home_sim.domain.base import ContractModel

BEHAVIOR_ISSUE_CODES = frozenset(
    {
        "ACTION_ARGUMENT_TYPE_MISMATCH",
        "AMBIGUOUS_PROCESS_BINDING",
        "CATALOG_REFERENCE_MISMATCH",
        "CHOICE_BRANCH_INVALID",
        "DUPLICATE_ACTION_PARAMETER",
        "DUPLICATE_BINDING_ID",
        "DUPLICATE_CATALOG_ENTRY",
        "DUPLICATE_EDGE",
        "DUPLICATE_NODE_ID",
        "DUPLICATE_PROCESS_MODEL_ID",
        "FILE_ENCODING_ERROR",
        "FILE_NOT_FOUND",
        "FILE_READ_ERROR",
        "FILE_TOO_LARGE",
        "GRAPH_CYCLE_UNBOUNDED",
        "GRAPH_END_INVALID",
        "GRAPH_NODE_DEAD",
        "GRAPH_START_INVALID",
        "INPUT_SCENARIO_INVALID",
        "INVALID_ACTION_ARGUMENTS",
        "INVALID_GRAPH_DEGREE",
        "INVALID_LITERAL_REFERENCE",
        "INVALID_VARIABLE_VALUE",
        "JSON_NESTING_TOO_DEEP",
        "JSON_SYNTAX",
        "LOOP_BRANCH_INVALID",
        "MISSING_PROCESS_BINDING",
        "PACKAGE_SCENARIO_MISMATCH",
        "PARALLEL_JOIN_MISSING",
        "PROCESS_MODEL_RESIDENT_MISMATCH",
        "PROCESS_MOVEMENT_MISSING",
        "PROCESS_COMPONENT_MISMATCH",
        "REQUIRED_VARIABLE_MISSING",
        "STRUCTURE_INVALID",
        "UNKNOWN_ACTION_TYPE",
        "UNKNOWN_ACTIVITY_COMPONENT",
        "UNKNOWN_EDGE_NODE",
        "UNKNOWN_INTENT",
        "UNKNOWN_PROCESS_MODEL",
        "UNKNOWN_RESIDENT",
        "UNKNOWN_VARIABLE",
        "UNSUPPORTED_SCHEMA_VERSION",
        "VARIABLE_SOURCE_TYPE_MISMATCH",
        "VARIABLE_SOURCE_VALUE_INVALID",
    }
)


class BehaviorValidationIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(BEHAVIOR_ISSUE_CODES)})
    severity: Literal["error", "warning"] = "error"
    stage: Literal["structure", "catalog", "graph", "compatibility"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class BehaviorValidationSummary(ContractModel):
    process_model_count: int = Field(ge=0)
    binding_count: int = Field(ge=0)
    covered_activity_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class BehaviorValidationReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:behavior-validation-report:1.0.0",
            "title": "Smart Home Behavior Validation Report 1.0.0",
        },
    )

    validator_version: Literal["1.0.0"] = "1.0.0"
    valid: bool
    package_version: str | None = None
    package_id: str | None = None
    scenario_id: str | None = None
    package_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issues: list[BehaviorValidationIssue] = Field(default_factory=list)
    summary: BehaviorValidationSummary

    @classmethod
    def from_issues(
        cls,
        issues: list[BehaviorValidationIssue],
        *,
        package_version: str | None = None,
        package_id: str | None = None,
        scenario_id: str | None = None,
        package_sha256: str | None = None,
        process_model_count: int = 0,
        binding_count: int = 0,
        covered_activity_count: int = 0,
    ) -> BehaviorValidationReport:
        error_count = sum(item.severity == "error" for item in issues)
        warning_count = sum(item.severity == "warning" for item in issues)
        return cls(
            valid=error_count == 0,
            package_version=package_version,
            package_id=package_id,
            scenario_id=scenario_id,
            package_sha256=package_sha256,
            issues=issues,
            summary=BehaviorValidationSummary(
                process_model_count=process_model_count,
                binding_count=binding_count,
                covered_activity_count=covered_activity_count,
                error_count=error_count,
                warning_count=warning_count,
            ),
        )
