from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.plan import ObjectiveValues

COMPILATION_ISSUE_CODES = frozenset(
    {
        "CANONICAL_PLAN_INVALID",
        "CONTINGENCY_PLAN_INFEASIBLE",
        "CONTINGENCY_TARGET_NOT_SCHEDULED",
        "CROSS_BRANCH_DEPENDENCY",
        "HORIZON_EXCEEDS_SOLVER_RANGE",
        "INPUT_SCENARIO_INVALID",
        "MAIN_PLAN_INFEASIBLE",
        "SOLVER_MODEL_INVALID",
        "SOLVER_NOT_OPTIMAL",
        "TIME_PRECISION_UNREPRESENTABLE",
    }
)

COMPILATION_WARNING_CODES = frozenset({"CONTINGENCY_TARGET_NOT_SCHEDULED"})


class CompilationIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(COMPILATION_ISSUE_CODES)})
    severity: Literal["error", "warning"]
    stage: Literal["input", "preflight", "main_plan", "contingency", "output"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class CompilationSummary(ContractModel):
    scheduled_activity_count: int = Field(ge=0)
    omitted_activity_count: int = Field(ge=0)
    contingency_count: int = Field(ge=0)
    contingency_activity_count: int = Field(ge=0)
    rescheduled_activity_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class CompilationReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:compilation-report:1.0.0",
            "title": "Smart Home Compilation Report 1.0.0",
        },
    )

    compiler_version: Literal["1.0.0"] = "1.0.0"
    success: bool
    source_scenario_version: str | None = None
    source_scenario_id: str | None = None
    canonical_plan_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    solver_status: str | None = None
    objective_values: ObjectiveValues | None = None
    issues: list[CompilationIssue] = Field(default_factory=list)
    summary: CompilationSummary
