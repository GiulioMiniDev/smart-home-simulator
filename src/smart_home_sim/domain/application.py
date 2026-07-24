from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel

APPLICATION_SCHEMA_VERSION = "1.0.0"


class RevisionStatus(StrEnum):
    draft = "draft"
    validating = "validating"
    valid = "valid"
    invalid = "invalid"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


class ExportFormat(StrEnum):
    jsonl = "jsonl"
    csv = "csv"
    xes = "xes"


class GraphicalReference(ContractModel):
    surface: Literal["form", "home", "sensor", "timeline", "artifact"]
    element_id: str = Field(min_length=1)
    property_name: str | None = None


class ApplicationIssue(ContractModel):
    code: str = Field(min_length=1)
    severity: Literal["error", "warning", "info"]
    stage: str = Field(min_length=1)
    path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, JsonValue] = Field(default_factory=dict)
    graphical_reference: GraphicalReference | None = None


class ArtifactDescriptor(ContractModel):
    artifact_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    schema_version: str | None = None
    media_type: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime


class WorkspaceSummary(ContractModel):
    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    format_version: Literal["1.0.0"] = "1.0.0"
    created_at: AwareDatetime
    updated_at: AwareDatetime
    diagnostic_mode: bool = False
    home_count: int = Field(ge=0)
    resident_count: int = Field(ge=0)
    run_count: int = Field(ge=0)
    active_job_count: int = Field(ge=0)
    artifact_count: int = Field(ge=0)


class HomeSummary(ContractModel):
    home_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    resident_count: int = Field(ge=0)
    run_count: int = Field(ge=0)
    issue_count: int = Field(ge=0)
    current_home_artifact_id: str | None = None
    current_sensor_artifact_id: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ResidentSummary(ContractModel):
    resident_id: str = Field(min_length=1)
    home_id: str = Field(min_length=1)
    source_resident_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    scenario_artifact_id: str | None = None
    behavior_artifact_id: str | None = None
    created_at: AwareDatetime


class WorkspaceManifest(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:application-workspace-manifest:1.0.0",
            "title": "Smart Home Application Workspace Manifest 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["application_workspace_manifest"] = "application_workspace_manifest"
    workspace: WorkspaceSummary
    exported_at: AwareDatetime
    homes: list[HomeSummary]
    residents: list[ResidentSummary]
    artifacts: list[ArtifactDescriptor]


class JobProgress(ContractModel):
    phase: str = Field(min_length=1)
    percent: float = Field(ge=0, le=100)
    completed_units: int = Field(default=0, ge=0)
    total_units: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1)


class JobRecord(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:application-job:1.0.0",
            "title": "Smart Home Application Job 1.0.0",
        },
    )

    job_id: str = Field(min_length=1)
    home_id: str | None = None
    kind: Literal["materialization", "simulation", "export", "integrity", "generation"]
    status: JobStatus
    progress: JobProgress
    requested_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    process_id: int | None = Field(default=None, ge=1)
    result_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    seed: int | None = None

    @model_validator(mode="after")
    def check_terminal_state(self) -> JobRecord:
        terminal = self.status in {
            JobStatus.completed,
            JobStatus.failed,
            JobStatus.cancelled,
            JobStatus.interrupted,
        }
        if terminal != (self.finished_at is not None):
            raise ValueError("terminal jobs require finishedAt and active jobs forbid it")
        if self.status is JobStatus.failed and not self.error_code:
            raise ValueError("failed jobs require errorCode")
        return self


class JobEvent(ContractModel):
    job_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    occurred_at: AwareDatetime
    event_type: Literal["status", "progress", "log", "artifact", "issue"]
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class ExportRequest(ContractModel):
    run_id: str = Field(min_length=1)
    formats: list[ExportFormat] = Field(min_length=1)
    roles: list[
        Literal[
            "observable",
            "oracle",
            "activities",
            "actions",
            "movements",
            "state_transitions",
            "resources",
            "runtime_events",
            "plan_deviations",
            "final_state",
        ]
    ] = Field(min_length=1)
    include_start: AwareDatetime | None = None
    include_end: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_request(self) -> ExportRequest:
        if len(self.formats) != len(set(self.formats)):
            raise ValueError("export formats must be unique")
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("export roles must be unique")
        if self.include_start and self.include_end and self.include_start > self.include_end:
            raise ValueError("includeStart must not follow includeEnd")
        return self


class ExportManifestFile(ContractModel):
    role: str = Field(min_length=1)
    format: ExportFormat
    relative_path: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExportManifest(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:application-export-manifest:1.0.0",
            "title": "Smart Home Application Export Manifest 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["application_export_manifest"] = "application_export_manifest"
    export_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    source_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_trace_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int
    created_at: AwareDatetime
    observable_oracle_separated: Literal[True] = True
    files: list[ExportManifestFile] = Field(min_length=1)


class DiaryAction(ContractModel):
    action_execution_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    status: str = Field(min_length=1)
    provider_ids: list[str]


class DiaryEntry(ContractModel):
    activity_execution_id: str = Field(min_length=1)
    source_activity_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    process_model_id: str = Field(min_length=1)
    planned_start: AwareDatetime
    planned_end: AwareDatetime
    actual_start: AwareDatetime
    actual_end: AwareDatetime
    status: str = Field(min_length=1)
    actions: list[DiaryAction]
    movement_ids: list[str]
    deviation_ids: list[str]
    trace_id: str = Field(min_length=1)
    trace_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ObservationCause(ContractModel):
    origin: str = Field(min_length=1)
    cause_type: str = Field(min_length=1)
    cause_ids: list[str]
    resident_ids: list[str]
    activity_execution_ids: list[str]
    action_execution_ids: list[str]


class ObservationView(ContractModel):
    observation_id: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    sensor_type: str = Field(min_length=1)
    observed_at: AwareDatetime
    measurement: str = Field(min_length=1)
    value: JsonValue
    unit: str | None = None
    quality: str = Field(min_length=1)
    oracle_cause: ObservationCause | None = None


class ReplayVerification(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:application-replay:1.0.0",
            "title": "Smart Home Application Replay Verification 1.0.0",
        },
    )

    run_id: str = Field(min_length=1)
    verified_at: AwareDatetime
    matches: bool
    expected_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_semantic_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def utc_now() -> datetime:
    return datetime.now(UTC)
