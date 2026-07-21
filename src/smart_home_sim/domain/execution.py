from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.environment import Point2D

SIMULATION_ISSUE_CODES = frozenset(
    {
        "ACTION_EXECUTION_FAILED",
        "BUNDLE_INVALID",
        "DAY_REPAIR_FAILED",
        "FILE_ENCODING_ERROR",
        "FILE_NOT_FOUND",
        "FILE_READ_ERROR",
        "FILE_TOO_LARGE",
        "JSON_NESTING_TOO_DEEP",
        "JSON_SYNTAX",
        "OUTPUT_CONFLICT",
        "OUTPUT_WRITE_ERROR",
        "PRECONDITION_FAILED",
        "PROCESS_EXECUTION_FAILED",
        "RESOURCE_DEADLOCK",
        "SIMULATION_FAILED",
        "STRUCTURE_INVALID",
        "TRACE_INVARIANT_FAILED",
        "UNSUPPORTED_SCHEMA_VERSION",
    }
)


class EngineMetadata(ContractModel):
    engine_name: Literal["smart-home-sim-engine"] = "smart-home-sim-engine"
    engine_version: Literal["1.0.0"] = "1.0.0"
    event_backend: Literal["simpy"] = "simpy"
    event_backend_version: Literal["4.1.1"] = "4.1.1"
    time_resolution: Literal["microsecond"] = "microsecond"
    random_stream_policy: Literal["sha256-named-streams-1.0.0"] = "sha256-named-streams-1.0.0"
    repair_policy_version: Literal["local-repair-1.0.0"] = "local-repair-1.0.0"


class TraceCausality(ContractModel):
    cause_type: Literal[
        "plan",
        "process_edge",
        "action_effect",
        "runtime_event",
        "resource",
        "local_repair",
    ]
    cause_id: str = Field(min_length=1)


class StateTransition(ContractModel):
    transition_id: str = Field(min_length=1)
    at: AwareDatetime
    subject_type: Literal["resident", "entity", "resource", "environment"]
    subject_id: str = Field(min_length=1)
    fact: str = Field(min_length=1)
    previous_value: JsonValue | None = None
    value: JsonValue | None = None
    operation: Literal["set", "increment", "decrement", "append", "remove", "invalidate"]
    causality: TraceCausality


class TrajectoryWaypoint(ContractModel):
    at: AwareDatetime
    region_id: str = Field(min_length=1)
    position: Point2D
    traversal_mode: Literal["walking", "transport"]


class MovementExecution(ContractModel):
    movement_id: str = Field(min_length=1)
    action_execution_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    origin_region_id: str = Field(min_length=1)
    destination_region_id: str = Field(min_length=1)
    distance_meters: float = Field(ge=0)
    duration_microseconds: int = Field(ge=0)
    waypoints: list[TrajectoryWaypoint] = Field(min_length=1)

    @model_validator(mode="after")
    def check_interval(self) -> MovementExecution:
        if self.started_at > self.ended_at:
            raise ValueError("movement start must not follow its end")
        return self


class ActionExecution(ContractModel):
    action_execution_id: str = Field(min_length=1)
    activity_execution_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    occurrence_index: int = Field(ge=0)
    action_type: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    status: Literal["completed", "interrupted", "failed"]
    resolved_arguments: dict[str, JsonValue] = Field(default_factory=dict)
    provider_ids: list[str] = Field(default_factory=list)
    selected_edge_target_id: str | None = None
    failure_code: str | None = None

    @model_validator(mode="after")
    def check_failure(self) -> ActionExecution:
        if self.started_at > self.ended_at:
            raise ValueError("action start must not follow its end")
        if (self.status == "failed") != (self.failure_code is not None):
            raise ValueError("only failed actions require failureCode")
        return self


class ResourceEvent(ContractModel):
    resource_event_id: str = Field(min_length=1)
    at: AwareDatetime
    resource_id: str = Field(min_length=1)
    activity_execution_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    operation: Literal["requested", "acquired", "preempted", "released"]
    units: int = Field(ge=1)
    available_units_after: int = Field(ge=0)


class RuntimeEventExecution(ContractModel):
    event_execution_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    sampled: bool
    occurred: bool
    evaluated_at: AwareDatetime
    trigger_activity_id: str | None = None
    sampled_amounts: list[float] = Field(default_factory=list)
    outcome: Literal["not_sampled", "precondition_failed", "applied"]


class PlanDeviation(ContractModel):
    deviation_id: str = Field(min_length=1)
    activity_execution_id: str = Field(min_length=1)
    kind: Literal[
        "delayed_start",
        "extended_duration",
        "interrupted",
        "shifted_by_local_repair",
        "shortened_by_local_repair",
        "fallback_applied",
        "optional_dropped",
    ]
    amount_microseconds: int = Field(default=0, ge=0)
    cause_id: str = Field(min_length=1)


class ActivityExecution(ContractModel):
    activity_execution_id: str = Field(min_length=1)
    source_activity_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    process_model_id: str = Field(min_length=1)
    planned_start: AwareDatetime
    planned_end: AwareDatetime
    actual_start: AwareDatetime
    actual_end: AwareDatetime
    status: Literal["completed", "deviated", "failed", "dropped"]
    action_execution_ids: list[str] = Field(default_factory=list)
    deviation_ids: list[str] = Field(default_factory=list)
    failure_code: str | None = None

    @model_validator(mode="after")
    def check_status(self) -> ActivityExecution:
        if self.actual_start > self.actual_end:
            raise ValueError("activity start must not follow its end")
        if (self.status == "failed") != (self.failure_code is not None):
            raise ValueError("only failed activities require failureCode")
        return self


class ResidentFinalState(ContractModel):
    resident_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    position: Point2D
    posture: Literal["standing", "walking", "sitting", "lying"]
    execution_state: Literal["idle", "moving", "performing_activity", "interrupted"]
    facts: dict[str, JsonValue] = Field(default_factory=dict)
    held_resource_ids: list[str] = Field(default_factory=list)


class FinalWorldState(ContractModel):
    at: AwareDatetime
    residents: list[ResidentFinalState] = Field(min_length=1)
    entity_states: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    environment_facts: dict[str, JsonValue] = Field(default_factory=dict)
    resource_available_units: dict[str, int] = Field(default_factory=dict)


class DailyExecutionSummary(ContractModel):
    date: date
    completed_activity_count: int = Field(ge=0)
    deviated_activity_count: int = Field(ge=0)
    failed_activity_count: int = Field(ge=0)
    dropped_activity_count: int = Field(ge=0)


class ExecutionTrace(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:execution-trace:1.0.0",
            "title": "Smart Home Authoritative Execution Trace 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["execution_trace"] = "execution_trace"
    trace_id: str = Field(min_length=1)
    source_bundle_id: str = Field(min_length=1)
    source_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int
    engine: EngineMetadata = Field(default_factory=EngineMetadata)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    status: Literal["completed"] = "completed"
    activity_executions: list[ActivityExecution]
    action_executions: list[ActionExecution]
    movements: list[MovementExecution]
    state_transitions: list[StateTransition]
    resource_events: list[ResourceEvent]
    runtime_events: list[RuntimeEventExecution]
    plan_deviations: list[PlanDeviation]
    daily_summaries: list[DailyExecutionSummary]
    final_state: FinalWorldState
    semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class SimulationIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(SIMULATION_ISSUE_CODES)})
    severity: Literal["error", "warning"] = "error"
    stage: Literal["input", "preflight", "execution", "invariant", "output"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class SimulationSummary(ContractModel):
    planned_activity_count: int = Field(ge=0)
    completed_activity_count: int = Field(ge=0)
    deviated_activity_count: int = Field(ge=0)
    failed_activity_count: int = Field(ge=0)
    dropped_activity_count: int = Field(ge=0)
    action_execution_count: int = Field(ge=0)
    movement_count: int = Field(ge=0)
    state_transition_count: int = Field(ge=0)
    runtime_event_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class SimulationReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:simulation-report:1.0.0",
            "title": "Smart Home Simulation Report 1.0.0",
        },
    )

    report_version: Literal["1.0.0"] = "1.0.0"
    success: bool
    source_bundle_id: str | None = None
    source_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    trace_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    semantic_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issues: list[SimulationIssue] = Field(default_factory=list)
    summary: SimulationSummary


class ReplayReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:replay-report:1.0.0",
            "title": "Smart Home Deterministic Replay Report 1.0.0",
        },
    )

    report_version: Literal["1.0.0"] = "1.0.0"
    matches: bool
    source_bundle_id: str
    expected_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_semantic_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    simulation_report: SimulationReport


class SimulationResult(ContractModel):
    report: SimulationReport
    trace: ExecutionTrace | None = None
