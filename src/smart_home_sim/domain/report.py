from __future__ import annotations

from typing import Literal

from pydantic import Field

from smart_home_sim.domain.base import ContractModel


class ValidationIssue(ContractModel):
    code: str
    severity: Literal["error", "warning"]
    level: Literal["structure", "referential", "temporal", "semantic"]
    path: str
    message: str


class ValidationSummary(ContractModel):
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class ValidationReport(ContractModel):
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
