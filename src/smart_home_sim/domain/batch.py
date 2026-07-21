from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.execution import SIMULATION_ISSUE_CODES

RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
BATCH_ISSUE_CODES = frozenset(
    {
        *SIMULATION_ISSUE_CODES,
        "BATCH_MANIFEST_INVALID",
        "BATCH_WORKER_FAILED",
        "RESUME_INVALID",
    }
)


class SimulationBatchIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(BATCH_ISSUE_CODES)})
    severity: Literal["error", "warning"] = "error"
    stage: Literal["input", "preflight", "execution", "invariant", "output"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class SimulationBatchRun(ContractModel):
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    bundle_path: str = Field(min_length=1)
    seed: int | None = None


class SimulationBatchManifest(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:simulation-batch-manifest:1.0.0",
            "title": "Smart Home Simulation Batch Manifest 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["simulation_batch_manifest"] = "simulation_batch_manifest"
    experiment_id: str = Field(pattern=RUN_ID_PATTERN)
    runs: list[SimulationBatchRun] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def unique_run_ids(self) -> SimulationBatchManifest:
        identifiers = [run.run_id for run in self.runs]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("batch runId values must be unique")
        return self


class SimulationBatchRunResult(ContractModel):
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    status: Literal["completed", "reused", "failed"]
    input_bundle_path: str = Field(min_length=1)
    input_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    effective_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    effective_seed: int | None = None
    effective_bundle_path: str | None = None
    trace_path: str | None = None
    simulation_report_path: str = Field(min_length=1)
    semantic_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    trace_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    elapsed_seconds: float = Field(ge=0)
    worker_pid: int | None = Field(default=None, ge=1)
    issues: list[SimulationBatchIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_status(self) -> SimulationBatchRunResult:
        successful = self.status in {"completed", "reused"}
        if successful and (
            self.semantic_digest is None
            or self.trace_sha256 is None
            or self.trace_path is None
            or self.effective_bundle_path is None
            or self.issues
        ):
            raise ValueError("completed and reused runs require complete artifact metadata")
        if self.status == "failed" and not self.issues:
            raise ValueError("failed runs require at least one issue")
        return self


class SimulationBatchSummary(ContractModel):
    requested_run_count: int = Field(ge=1)
    completed_run_count: int = Field(ge=0)
    reused_run_count: int = Field(ge=0)
    failed_run_count: int = Field(ge=0)
    worker_count: int = Field(ge=1)
    elapsed_seconds: float = Field(ge=0)


class SimulationBatchReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:simulation-batch-report:1.0.0",
            "title": "Smart Home Simulation Batch Report 1.0.0",
        },
    )

    report_version: Literal["1.0.0"] = "1.0.0"
    success: bool
    experiment_id: str = Field(pattern=RUN_ID_PATTERN)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: AwareDatetime
    ended_at: AwareDatetime
    output_directory: str = Field(min_length=1)
    runs: list[SimulationBatchRunResult] = Field(min_length=1)
    summary: SimulationBatchSummary

    @model_validator(mode="after")
    def check_summary(self) -> SimulationBatchReport:
        completed = sum(run.status == "completed" for run in self.runs)
        reused = sum(run.status == "reused" for run in self.runs)
        failed = sum(run.status == "failed" for run in self.runs)
        if (
            self.summary.requested_run_count != len(self.runs)
            or self.summary.completed_run_count != completed
            or self.summary.reused_run_count != reused
            or self.summary.failed_run_count != failed
            or self.success != (failed == 0)
            or self.started_at > self.ended_at
        ):
            raise ValueError("batch report summary is inconsistent with its runs")
        return self
