from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.environment import Point2D

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
    # Not record streams and never requested: the two shapes the resident profile takes, a single
    # document and the page that reads it. They exist so that everything inside an export is
    # described by its manifest and covered by its digests, including the parts meant for a person.
    json = "json"
    html = "html"


RECORD_FORMATS = frozenset({ExportFormat.jsonl, ExportFormat.csv, ExportFormat.xes})


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


class IntegrityFinding(ContractModel):
    """One disagreement between the persistent catalogue and the workspace folder."""

    kind: Literal["missing", "corrupt", "orphan"]
    relative_path: str = Field(min_length=1)
    artifact_id: str | None = None
    role: str | None = None
    size_bytes: int = Field(default=0, ge=0)
    detail: str = Field(min_length=1)


class WorkspaceIntegrity(ContractModel):
    """The result of comparing every catalogued artifact with the files on disk.

    ``missing`` and ``orphan`` describe a folder a researcher has edited; they are recoverable and
    never justify refusing new work. ``corrupt`` means a file is present with content the catalogue
    does not vouch for, which is the only condition that still enables diagnostic mode.
    """

    checked_at: AwareDatetime
    diagnostic_mode: bool = False
    missing: list[IntegrityFinding] = Field(default_factory=list)
    corrupt: list[IntegrityFinding] = Field(default_factory=list)
    orphans: list[IntegrityFinding] = Field(default_factory=list)
    reclaimable_bytes: int = Field(default=0, ge=0)


class MaintenanceSummary(ContractModel):
    """What a repair or a deletion actually changed, in terms a researcher can check."""

    performed_at: AwareDatetime
    homes_removed: int = Field(default=0, ge=0)
    runs_removed: int = Field(default=0, ge=0)
    exports_removed: int = Field(default=0, ge=0)
    artifacts_pruned: int = Field(default=0, ge=0)
    artifacts_adopted: int = Field(default=0, ge=0)
    files_removed: int = Field(default=0, ge=0)
    bytes_freed: int = Field(default=0, ge=0)
    corrupt_remaining: int = Field(default=0, ge=0)
    details: list[str] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.homes_removed
            or self.runs_removed
            or self.exports_removed
            or self.artifacts_pruned
            or self.artifacts_adopted
            or self.files_removed
        )


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
    # `environment` builds the home and its sensor field and executes nothing, so it is the one
    # completed job kind that legitimately publishes no execution evidence.
    kind: Literal[
        "materialization", "simulation", "export", "integrity", "generation", "environment"
    ]
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
            "habit_ground_truth",
            # Not a projection of a stored artifact but an aggregate computed at export time, and
            # the only role whose files do not follow the requested formats: a profile is a
            # document, a page and a matrix, never a JSONL record stream.
            "resident_profile",
            # The other computed role: one page saying what the dataset is — the flat with its
            # sensors drawn on it, the resident's declared traits, the habit bands in words, the
            # realized behaviour beside them and an index of the export. It reads the home model,
            # the sensor model and the scenario, which no other role publishes at all.
            "summary",
        ]
    ] = Field(min_length=1)
    include_start: AwareDatetime | None = None
    include_end: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_request(self) -> ExportRequest:
        if len(self.formats) != len(set(self.formats)):
            raise ValueError("export formats must be unique")
        if not set(self.formats) <= RECORD_FORMATS:
            raise ValueError("only jsonl, csv and xes can be requested for a role")
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
            "$id": "urn:smart-home-simulator:schema:application-export-manifest:1.1.0",
            "title": "Smart Home Application Export Manifest 1.1.0",
        },
    )

    # 1.1.0 admits the two document formats the resident profile introduced. Manifests written by
    # 1.0.0 are still read: they describe exports that are still on disk, and a workspace that
    # could no longer list its older datasets would have lost them.
    schema_version: Literal["1.0.0", "1.1.0"] = "1.1.0"
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
        frozen=True,
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


ReplayEventKind = Literal[
    "activity",
    "action",
    "movement",
    "observation",
    "state_transition",
    "resource",
    "runtime_event",
    "plan_deviation",
]
ReplayDetailMode = Literal["presentation", "analysis"]
ReplayVisibilityMode = Literal["observable", "oracle"]


class ReplayWaypoint(ContractModel):
    at: AwareDatetime
    region_id: str = Field(min_length=1)
    position: Point2D
    traversal_mode: str = Field(min_length=1)


class ReplayEventView(ContractModel):
    at: AwareDatetime
    end: AwareDatetime | None = None
    kind: ReplayEventKind
    event_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str | None = None
    actor_id: str | None = None
    sensor_id: str | None = None
    waypoints: list[ReplayWaypoint] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ReplayEventWindow(ContractModel):
    items: list[ReplayEventView] = Field(max_length=5000)
    total: int = Field(ge=0)
    trace_start: AwareDatetime
    trace_end: AwareDatetime
    window_start: AwareDatetime
    window_end: AwareDatetime


class ReplayResidentFrame(ContractModel):
    resident_id: str = Field(min_length=1)
    region_id: str | None = None
    position: Point2D | None = None
    posture: str | None = None
    execution_state: str = Field(min_length=1)
    activity_execution_id: str | None = None
    action_execution_id: str | None = None
    held_resource_ids: list[str] = Field(default_factory=list)
    facts: dict[str, JsonValue] = Field(default_factory=dict)


class ReplaySensorFrame(ContractModel):
    observation_id: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    sensor_type: str = Field(min_length=1)
    observed_at: AwareDatetime
    measurement: str = Field(min_length=1)
    value: JsonValue
    unit: str | None = None
    quality: str = Field(min_length=1)
    changed: bool = False
    oracle_cause: ObservationCause | None = None


class ReplayFrame(ContractModel):
    model_config = ConfigDict(**ContractModel.model_config, frozen=True)

    run_id: str = Field(min_length=1)
    at: AwareDatetime
    trace_start: AwareDatetime
    trace_end: AwareDatetime
    residents: list[ReplayResidentFrame]
    sensor_states: list[ReplaySensorFrame]
    entity_states: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    environment_facts: dict[str, JsonValue] = Field(default_factory=dict)
    resource_available_units: dict[str, int] = Field(default_factory=dict)
    active_event_ids: list[str] = Field(default_factory=list)


class ReplayFilters(ContractModel):
    event_kinds: list[ReplayEventKind] = Field(default_factory=list)
    actor_ids: list[str] = Field(default_factory=list)
    sensor_ids: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    detail_mode: ReplayDetailMode = "presentation"
    visibility_mode: ReplayVisibilityMode = "observable"
    speed: float = Field(default=1, ge=0.25, le=32)
    selected_resident_id: str | None = None


class ReplaySessionState(ContractModel):
    model_config = ConfigDict(**ContractModel.model_config, frozen=True)

    replay_id: str | None = None
    run_id: str = Field(min_length=1)
    verified_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    playable: bool = False
    position_at: AwareDatetime | None = None
    filters: ReplayFilters = Field(default_factory=ReplayFilters)
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


_OBSERVABLE_REPLAY_KEY_TOKEN = re.compile(
    r"[A-Z]+(?=[A-Z][a-z]|[^A-Za-z]|$)|[A-Z]?[a-z]+|[0-9]+"
)
_OBSERVABLE_REPLAY_IDENTITY_PREFIXES = ("source", "current", "target", "parent")
_OBSERVABLE_REPLAY_IDENTITY_SUBJECTS = frozenset({"resident", "actor", "activity", "action"})
_OBSERVABLE_REPLAY_IDENTITY_SUFFIXES = (
    "identities",
    "identifiers",
    "identity",
    "identifier",
    "idlists",
    "idlist",
    "ids",
    "id",
)


def _observable_replay_key_tokens(key: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _OBSERVABLE_REPLAY_KEY_TOKEN.findall(key))


def _normalized_observable_replay_key(key: str) -> str:
    return "".join(_observable_replay_key_tokens(key))


def _strip_observable_replay_identity_prefixes(value: str) -> str:
    while prefix := next(
        (prefix for prefix in _OBSERVABLE_REPLAY_IDENTITY_PREFIXES if value.startswith(prefix)),
        None,
    ):
        value = value.removeprefix(prefix)
    return value


def _strip_observable_replay_identity_suffix(value: str) -> str | None:
    for suffix in _OBSERVABLE_REPLAY_IDENTITY_SUFFIXES:
        if value.endswith(suffix):
            return value.removesuffix(suffix)
    return None


def _is_observable_replay_redacted_key(key: str) -> bool:
    value = _strip_observable_replay_identity_prefixes(_normalized_observable_replay_key(key))
    stem = _strip_observable_replay_identity_suffix(value)
    if stem is not None:
        if stem in _OBSERVABLE_REPLAY_IDENTITY_SUBJECTS | {"execution", "cause", "oraclecause"}:
            return True
        return any(
            stem == f"{subject}execution"
            for subject in _OBSERVABLE_REPLAY_IDENTITY_SUBJECTS
        )
    return value in {"cause", "oraclecause"}


def _observable_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _observable_json_value(item)
            for key, item in value.items()
            if not _is_observable_replay_redacted_key(key)
        }
    if isinstance(value, list):
        return [_observable_json_value(item) for item in value]
    return value


def _observable_json_mapping(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        key: _observable_json_value(item)
        for key, item in value.items()
        if not _is_observable_replay_redacted_key(key)
    }


class ObservableReplayEventView(ContractModel):
    at: AwareDatetime
    end: AwareDatetime | None = None
    kind: ReplayEventKind
    event_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str | None = None
    sensor_id: str | None = None
    waypoints: list[ReplayWaypoint] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @classmethod
    def from_event(cls, event: ReplayEventView) -> ObservableReplayEventView:
        return cls(
            at=event.at,
            end=event.end,
            kind=event.kind,
            event_id=event.event_id,
            label=event.label,
            status=event.status,
            sensor_id=event.sensor_id,
            waypoints=event.waypoints,
            details=_observable_json_mapping(event.details),
        )


class ObservableReplayEventWindow(ContractModel):
    items: list[ObservableReplayEventView] = Field(max_length=5000)
    total: int = Field(ge=0)
    trace_start: AwareDatetime
    trace_end: AwareDatetime
    window_start: AwareDatetime
    window_end: AwareDatetime

    @classmethod
    def from_window(cls, window: ReplayEventWindow) -> ObservableReplayEventWindow:
        return cls(
            items=[ObservableReplayEventView.from_event(item) for item in window.items],
            total=window.total,
            trace_start=window.trace_start,
            trace_end=window.trace_end,
            window_start=window.window_start,
            window_end=window.window_end,
        )


class ObservableReplayResidentFrame(ContractModel):
    region_id: str | None = None
    position: Point2D | None = None
    posture: str | None = None
    execution_state: str = Field(min_length=1)
    held_resource_ids: list[str] = Field(default_factory=list)
    facts: dict[str, JsonValue] = Field(default_factory=dict)

    @classmethod
    def from_resident(cls, resident: ReplayResidentFrame) -> ObservableReplayResidentFrame:
        return cls(
            region_id=resident.region_id,
            position=resident.position,
            posture=resident.posture,
            execution_state=resident.execution_state,
            held_resource_ids=resident.held_resource_ids,
            facts=_observable_json_mapping(resident.facts),
        )


class ObservableReplaySensorFrame(ContractModel):
    observation_id: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    sensor_type: str = Field(min_length=1)
    observed_at: AwareDatetime
    measurement: str = Field(min_length=1)
    value: JsonValue
    unit: str | None = None
    quality: str = Field(min_length=1)
    changed: bool = False

    @classmethod
    def from_sensor(cls, sensor: ReplaySensorFrame) -> ObservableReplaySensorFrame:
        return cls(
            observation_id=sensor.observation_id,
            sensor_id=sensor.sensor_id,
            sensor_type=sensor.sensor_type,
            observed_at=sensor.observed_at,
            measurement=sensor.measurement,
            value=sensor.value,
            unit=sensor.unit,
            quality=sensor.quality,
            changed=sensor.changed,
        )


class ObservableReplayFrame(ContractModel):
    run_id: str = Field(min_length=1)
    at: AwareDatetime
    trace_start: AwareDatetime
    trace_end: AwareDatetime
    residents: list[ObservableReplayResidentFrame]
    sensor_states: list[ObservableReplaySensorFrame]
    entity_states: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    environment_facts: dict[str, JsonValue] = Field(default_factory=dict)
    resource_available_units: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_frame(cls, frame: ReplayFrame) -> ObservableReplayFrame:
        return cls(
            run_id=frame.run_id,
            at=frame.at,
            trace_start=frame.trace_start,
            trace_end=frame.trace_end,
            residents=[
                ObservableReplayResidentFrame.from_resident(item) for item in frame.residents
            ],
            sensor_states=[
                ObservableReplaySensorFrame.from_sensor(item) for item in frame.sensor_states
            ],
            entity_states={
                entity_id: _observable_json_mapping(state)
                for entity_id, state in frame.entity_states.items()
            },
            environment_facts=_observable_json_mapping(frame.environment_facts),
            resource_available_units=frame.resource_available_units,
        )


class ObservableReplayFilters(ContractModel):
    event_kinds: list[ReplayEventKind] = Field(default_factory=list)
    sensor_ids: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    detail_mode: ReplayDetailMode = "presentation"
    visibility_mode: ReplayVisibilityMode = "observable"
    speed: float = Field(default=1, ge=0.25, le=32)

    @classmethod
    def from_filters(cls, filters: ReplayFilters) -> ObservableReplayFilters:
        return cls(
            event_kinds=filters.event_kinds,
            sensor_ids=filters.sensor_ids,
            statuses=filters.statuses,
            detail_mode=filters.detail_mode,
            visibility_mode="observable",
            speed=filters.speed,
        )


class ObservableReplaySessionState(ContractModel):
    replay_id: str | None = None
    run_id: str = Field(min_length=1)
    verified_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    playable: bool = False
    position_at: AwareDatetime | None = None
    filters: ObservableReplayFilters = Field(default_factory=ObservableReplayFilters)
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None

    @classmethod
    def from_session(cls, session: ReplaySessionState) -> ObservableReplaySessionState:
        return cls(
            replay_id=session.replay_id,
            run_id=session.run_id,
            verified_digest=session.verified_digest,
            playable=session.playable,
            position_at=session.position_at,
            filters=ObservableReplayFilters.from_filters(session.filters),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )


class ObservableApplicationReplayContract(ContractModel):
    verification: ReplayVerification
    event_window: ObservableReplayEventWindow
    frame: ObservableReplayFrame
    session: ObservableReplaySessionState


class ApplicationReplayContract(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        frozen=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:application-replay:1.1.0",
            "title": "Smart Home Application Replay 1.1.0",
        },
    )

    verification: ReplayVerification
    event_window: ReplayEventWindow
    frame: ReplayFrame
    session: ReplaySessionState

    @model_validator(mode="after")
    def check_playable_session_verification(self) -> ApplicationReplayContract:
        if not self.session.playable:
            return self
        if self.session.run_id != self.verification.run_id:
            raise ValueError("playable replay session must match the verification run")
        if self.frame.run_id != self.session.run_id:
            raise ValueError("playable replay session frame run must match the verification run")
        if not self.verification.matches:
            raise ValueError("playable replay session requires a matching verification")
        if self.session.verified_digest is None:
            raise ValueError("playable replay session requires a verified digest")
        if self.verification.actual_semantic_digest != self.session.verified_digest:
            raise ValueError("playable replay session digest must match the verification digest")
        return self

    def playback_payload(
        self, *, include_oracle: bool = False
    ) -> ApplicationReplayContract | ObservableApplicationReplayContract:
        if include_oracle:
            return self
        return ObservableApplicationReplayContract(
            verification=self.verification,
            event_window=ObservableReplayEventWindow.from_window(self.event_window),
            frame=ObservableReplayFrame.from_frame(self.frame),
            session=ObservableReplaySessionState.from_session(self.session),
        )

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        copied = super().model_copy(update=update, deep=deep)
        if not update:
            copied.check_playable_session_verification()
            return copied
        return type(self).model_validate(copied.model_dump(round_trip=True))


def utc_now() -> datetime:
    return datetime.now(UTC)
