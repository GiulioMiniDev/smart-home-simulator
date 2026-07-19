from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.codes import STABLE_ISSUE_CODES


class ValidationIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(STABLE_ISSUE_CODES)})
    severity: Literal["error", "warning"]
    level: Literal["structure", "referential", "temporal", "semantic"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ValidationSummary(ContractModel):
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class ValidationReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:validation-report:1.0.0",
            "title": "Smart Home Validation Report 1.0.0",
        },
    )

    validator_version: Literal["1.0.0"] = "1.0.0"
    valid: bool
    schema_version: str | None
    scenario_id: str | None
    issues: list[ValidationIssue]
    summary: ValidationSummary

    @classmethod
    def from_issues(
        cls,
        issues: list[ValidationIssue],
        schema_version: str | None = None,
        scenario_id: str | None = None,
    ) -> ValidationReport:
        error_count = sum(issue.severity == "error" for issue in issues)
        warning_count = sum(issue.severity == "warning" for issue in issues)
        return cls(
            valid=error_count == 0,
            schema_version=schema_version,
            scenario_id=scenario_id,
            issues=issues,
            summary=ValidationSummary(
                error_count=error_count,
                warning_count=warning_count,
            ),
        )
