from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.batch import RUN_ID_PATTERN
from smart_home_sim.domain.execution import SIMULATION_ISSUE_CODES, FinalWorldState

LONGITUDINAL_ISSUE_CODES = frozenset(
    {
        *SIMULATION_ISSUE_CODES,
        "LONGITUDINAL_MANIFEST_INVALID",
        "LONGITUDINAL_SEQUENCE_INVALID",
        "LONGITUDINAL_WORKER_FAILED",
        "RESUME_INVALID",
        "HANDOFF_INVALID",
        "INITIAL_WORLD_STATE_INVALID",
    }
)


def _is_safe_relative_path(path_str: str) -> bool:
    if path_str.startswith("/") or path_str.startswith("\\"):
        return False
    p = Path(path_str)
    if p.is_absolute():
        return False
    if ".." in p.parts:
        return False
    return True


class LongitudinalSimulationIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(LONGITUDINAL_ISSUE_CODES)})
    severity: Literal["error", "warning"] = "error"
    stage: Literal["input", "preflight", "execution", "invariant", "output"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class LongitudinalSimulationManifest(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:longitudinal-simulation-manifest:1.0.0",
            "title": "Smart Home Longitudinal Simulation Manifest 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["longitudinal_simulation_manifest"] = (
        "longitudinal_simulation_manifest"
    )
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    scenario_paths: list[str] = Field(min_length=1)
    personal_process_package_path: str = Field(min_length=1)
    home_policy_path: str | None = None
    sensor_policy_path: str | None = None
    seed: int

    @model_validator(mode="after")
    def validate_paths(self) -> LongitudinalSimulationManifest:
        if len(self.scenario_paths) != len(set(self.scenario_paths)):
            raise ValueError("scenarioPaths must be unique")

        for scenario_path in self.scenario_paths:
            if not _is_safe_relative_path(scenario_path):
                raise ValueError(
                    f"scenarioPath must be a safe relative path without '..': {scenario_path}"
                )

        if not _is_safe_relative_path(self.personal_process_package_path):
            raise ValueError(
                "personalProcessPackagePath must be a safe relative path without '..'"
            )

        if self.home_policy_path is not None and not _is_safe_relative_path(
            self.home_policy_path
        ):
            raise ValueError("homePolicyPath must be a safe relative path without '..'")

        if self.sensor_policy_path is not None and not _is_safe_relative_path(
            self.sensor_policy_path
        ):
            raise ValueError("sensorPolicyPath must be a safe relative path without '..'")

        return self


class LongitudinalChunkRecord(ContractModel):
    chunk_index: int = Field(ge=1)
    scenario_path: str = Field(min_length=1)
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_state_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    artifact_path: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    terminal_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sensor_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    oracle_mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LongitudinalCheckpoint(ContractModel):
    checkpoint_version: Literal["1.0.0"] = "1.0.0"
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_chunk_count: int = Field(ge=0)
    random_stream_policy: Literal["sha256-named-streams-1.0.0"] = (
        "sha256-named-streams-1.0.0"
    )
    terminal_state: FinalWorldState | None = None
    chunks: list[LongitudinalChunkRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_checkpoint(self) -> LongitudinalCheckpoint:
        if self.completed_chunk_count != len(self.chunks):
            raise ValueError("completedChunkCount must match the number of chunk records")

        chunk_indices = [c.chunk_index for c in self.chunks]
        if chunk_indices != list(range(1, len(self.chunks) + 1)):
            raise ValueError("chunk records must have 1-based sequential indices")

        if self.completed_chunk_count > 0 and self.terminal_state is None:
            raise ValueError("completed checkpoint requires a terminal state")

        return self


class LongitudinalSimulationReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:longitudinal-simulation-report:1.0.0",
            "title": "Smart Home Longitudinal Simulation Report 1.0.0",
        },
    )

    report_version: Literal["1.0.0"] = "1.0.0"
    success: bool
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: AwareDatetime
    ended_at: AwareDatetime
    chunks: list[LongitudinalChunkRecord] = Field(default_factory=list)
    issues: list[LongitudinalSimulationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report(self) -> LongitudinalSimulationReport:
        if self.started_at > self.ended_at:
            raise ValueError("startedAt cannot be after endedAt")
        if self.success and self.issues:
            raise ValueError("successful longitudinal report cannot contain issues")
        if not self.success and not self.issues:
            raise ValueError("failed longitudinal report requires at least one issue")
        return self
