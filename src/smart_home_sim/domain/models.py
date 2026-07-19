from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, field_validator, model_validator

from smart_home_sim.domain.base import ContractModel


class AuthorType(StrEnum):
    human = "human"
    external_llm = "external_llm"
    rule_generator = "rule_generator"
    import_ = "import"


class Provenance(ContractModel):
    author_type: AuthorType
    generator_name: str | None = None
    generator_version: str | None = None
    model_name: str | None = None
    prompt_template_version: str | None = None
    generated_at: AwareDatetime | None = None
    human_reviewed: bool = False
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class SimulationWindow(ContractModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def check_order(self) -> SimulationWindow:
        if self.start >= self.end:
            raise ValueError("simulation window start must be before end")
        return self


class VersionedReference(ContractModel):
    reference_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ModelReferences(ContractModel):
    activity_catalog: VersionedReference
    home_model: VersionedReference
    sensor_model: VersionedReference | None = None


class RepairStep(StrEnum):
    shift_within_window = "shift_within_window"
    shorten_within_range = "shorten_within_range"
    apply_declared_fallback = "apply_declared_fallback"
    drop_optional_activity = "drop_optional_activity"
    reject_day_plan = "reject_day_plan"


class MaterializationPolicy(ContractModel):
    authoritative_state_source: Literal[
        "scenario_initial_then_previous_execution",
        "scenario_initial_only",
    ] = "scenario_initial_then_previous_execution"
    revalidate_before_each_day: bool = True
    require_every_date: bool = True
    allow_local_repair: bool = True
    repair_order: list[RepairStep] = Field(
        default_factory=lambda: [
            RepairStep.shift_within_window,
            RepairStep.shorten_within_range,
            RepairStep.apply_declared_fallback,
            RepairStep.drop_optional_activity,
            RepairStep.reject_day_plan,
        ]
    )


class Resident(ContractModel):
    resident_id: str = Field(min_length=1)
    display_name: str | None = None
    profile: dict[str, JsonValue] = Field(default_factory=dict)


class ExternalPerson(ContractModel):
    external_person_id: str = Field(min_length=1)
    display_name: str | None = None
    relationship_to_residents: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class LocationKind(StrEnum):
    room = "room"
    external = "external"
    transit = "transit"
    composite = "composite"


class Location(ContractModel):
    location_id: str = Field(min_length=1)
    kind: LocationKind
    member_location_ids: list[str] = Field(default_factory=list)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_composite_members(self) -> Location:
        if self.kind is LocationKind.composite and not self.member_location_ids:
            raise ValueError("composite locations require at least one memberLocationId")
        if self.kind is not LocationKind.composite and self.member_location_ids:
            raise ValueError("only composite locations may define memberLocationIds")
        return self


class Resource(ContractModel):
    resource_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    location_id: str = Field(min_length=1)
    capacity: int = Field(default=1, ge=1)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class ResidentInitialState(ContractModel):
    resident_id: str = Field(min_length=1)
    location_id: str = Field(min_length=1)
    facts: dict[str, JsonValue] = Field(default_factory=dict)


class InitialState(ContractModel):
    at: AwareDatetime
    residents: list[ResidentInitialState] = Field(min_length=1)
    environment_facts: dict[str, JsonValue] = Field(default_factory=dict)
    resource_facts: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)


class ConditionOperator(StrEnum):
    truthy = "truthy"
    falsy = "falsy"
    exists = "exists"
    not_exists = "not_exists"
    eq = "eq"
    ne = "ne"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    in_ = "in"
    not_in = "not_in"


class Condition(ContractModel):
    fact: str = Field(min_length=1)
    operator: ConditionOperator = ConditionOperator.truthy
    value: JsonValue | None = None

    @model_validator(mode="after")
    def check_value_policy(self) -> Condition:
        unary = {
            ConditionOperator.truthy,
            ConditionOperator.falsy,
            ConditionOperator.exists,
            ConditionOperator.not_exists,
        }
        if self.operator in unary and self.value is not None:
            raise ValueError(f"operator '{self.operator}' does not accept a value")
        if self.operator not in unary and self.value is None:
            raise ValueError(f"operator '{self.operator}' requires a value")
        numeric = {
            ConditionOperator.gt,
            ConditionOperator.gte,
            ConditionOperator.lt,
            ConditionOperator.lte,
        }
        if self.operator in numeric and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError(f"operator '{self.operator}' requires a numeric value")
        membership = {ConditionOperator.in_, ConditionOperator.not_in}
        if self.operator in membership and not isinstance(self.value, list):
            raise ValueError(f"operator '{self.operator}' requires an array value")
        return self


class EffectOperation(StrEnum):
    set = "set"
    increment = "increment"
    decrement = "decrement"
    append = "append"
    remove = "remove"


class StateEffect(ContractModel):
    fact: str = Field(min_length=1)
    operation: EffectOperation
    value: JsonValue

    @model_validator(mode="after")
    def check_value_type(self) -> StateEffect:
        if self.operation in {EffectOperation.increment, EffectOperation.decrement} and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError(f"operation '{self.operation}' requires a numeric value")
        return self


class DateTimeWindow(ContractModel):
    earliest: AwareDatetime
    preferred: AwareDatetime
    latest: AwareDatetime

    @model_validator(mode="after")
    def check_order(self) -> DateTimeWindow:
        if not self.earliest <= self.preferred <= self.latest:
            raise ValueError("window must satisfy earliest <= preferred <= latest")
        return self


class DurationRange(ContractModel):
    minimum_minutes: float = Field(gt=0)
    preferred_minutes: float = Field(gt=0)
    maximum_minutes: float = Field(gt=0)

    @model_validator(mode="after")
    def check_order(self) -> DurationRange:
        if not self.minimum_minutes <= self.preferred_minutes <= self.maximum_minutes:
            raise ValueError(
                "duration must satisfy minimumMinutes <= preferredMinutes <= maximumMinutes"
            )
        return self


class DependencyMode(StrEnum):
    all = "all"
    any = "any"


class DependencyGroup(ContractModel):
    mode: DependencyMode = DependencyMode.all
    activity_ids: list[str] = Field(min_length=1)
    minimum_lag_minutes: float = Field(default=0, ge=0)
    maximum_lag_minutes: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_lag(self) -> DependencyGroup:
        if (
            self.maximum_lag_minutes is not None
            and self.maximum_lag_minutes < self.minimum_lag_minutes
        ):
            raise ValueError("maximumLagMinutes must be >= minimumLagMinutes")
        return self


class ActivationMode(StrEnum):
    always = "always"
    conditional = "conditional"
    fallback = "fallback"


class FallbackTrigger(StrEnum):
    precondition_failed = "precondition_failed"
    activity_cancelled = "activity_cancelled"
    activity_replaced = "activity_replaced"


class ActivationRule(ContractModel):
    mode: ActivationMode = ActivationMode.always
    condition: Condition | None = None
    fallback_for_activity_id: str | None = None
    fallback_trigger: FallbackTrigger | None = None

    @model_validator(mode="after")
    def check_mode_fields(self) -> ActivationRule:
        if self.mode is ActivationMode.always:
            if any(
                value is not None
                for value in (
                    self.condition,
                    self.fallback_for_activity_id,
                    self.fallback_trigger,
                )
            ):
                raise ValueError("always activation cannot define condition or fallback fields")
        elif self.mode is ActivationMode.conditional:
            if self.condition is None:
                raise ValueError("conditional activation requires condition")
            if self.fallback_for_activity_id is not None or self.fallback_trigger is not None:
                raise ValueError("conditional activation cannot define fallback fields")
        elif self.mode is ActivationMode.fallback:
            if self.fallback_for_activity_id is None or self.fallback_trigger is None:
                raise ValueError("fallback activation requires target and trigger")
            if self.condition is not None:
                raise ValueError("fallback activation cannot define condition")
        return self


class ResourceRequirement(ContractModel):
    resource_id: str = Field(min_length=1)
    units: int = Field(default=1, ge=1)


class Activity(ContractModel):
    activity_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    location_ids: list[str] = Field(min_length=1)
    start_window: DateTimeWindow | None = None
    end_window: DateTimeWindow | None = None
    duration: DurationRange | None = None
    mandatory: bool = True
    priority: int = Field(default=50, ge=0, le=100)
    can_overlap_for_actor: bool = False
    allow_boundary_truncation: bool = False
    dependency_groups: list[DependencyGroup] = Field(default_factory=list)
    participant_ids: list[str] = Field(default_factory=list)
    required_resources: list[ResourceRequirement] = Field(default_factory=list)
    preconditions: list[Condition] = Field(default_factory=list)
    effects: list[StateEffect] = Field(default_factory=list)
    activation: ActivationRule = Field(default_factory=ActivationRule)
    commitment_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    extensions: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_timing_completeness(self) -> Activity:
        has_dependency = bool(self.dependency_groups)
        is_fallback = self.activation.mode is ActivationMode.fallback
        if self.start_window is None and not has_dependency and not is_fallback:
            raise ValueError(
                "activity requires startWindow, dependencyGroups, or fallback activation"
            )
        if self.duration is None and self.end_window is None:
            raise ValueError("activity requires duration or endWindow")
        if self.duration is not None and self.end_window is not None:
            raise ValueError("activity cannot define both duration and endWindow")
        if self.start_window is None and self.end_window is not None:
            raise ValueError("endWindow requires startWindow")
        if (
            self.start_window is not None
            and self.end_window is not None
            and self.start_window.earliest >= self.end_window.latest
        ):
            raise ValueError("activity start window must precede end window")
        if (
            self.start_window is not None
            and self.end_window is not None
            and self.start_window.preferred >= self.end_window.preferred
        ):
            raise ValueError("preferred activity start must precede preferred end")
        return self


class DayContext(ContractModel):
    day_type: str = Field(min_length=1)
    narrative_intent: str | None = None
    facts: dict[str, JsonValue] = Field(default_factory=dict)


class DayPlan(ContractModel):
    date: date
    context: DayContext
    activities: list[Activity] = Field(default_factory=list)


class Commitment(ContractModel):
    commitment_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    participant_ids: list[str] = Field(min_length=1)
    location_id: str = Field(min_length=1)
    start: AwareDatetime
    end: AwareDatetime
    mandatory: bool = True
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_interval(self) -> Commitment:
        if self.start >= self.end:
            raise ValueError("commitment start must be before end")
        return self


class RuntimeEventOperation(StrEnum):
    delay_activity_start = "delay_activity_start"
    extend_activity_duration = "extend_activity_duration"
    interrupt_actor = "interrupt_actor"
    invalidate_fact = "invalidate_fact"
    set_fact = "set_fact"


class RuntimeEventEffect(ContractModel):
    operation: RuntimeEventOperation
    target_id: str
    minimum_amount: float | None = None
    maximum_amount: float | None = None
    value: JsonValue | None = None

    @model_validator(mode="after")
    def check_parameters(self) -> RuntimeEventEffect:
        amount_operations = {
            RuntimeEventOperation.delay_activity_start,
            RuntimeEventOperation.extend_activity_duration,
            RuntimeEventOperation.interrupt_actor,
        }
        if self.operation in amount_operations:
            if self.minimum_amount is None or self.maximum_amount is None:
                raise ValueError(f"operation '{self.operation}' requires an amount range")
            if self.minimum_amount < 0 or self.maximum_amount < self.minimum_amount:
                raise ValueError("event amount range is invalid")
            if self.value is not None:
                raise ValueError(f"operation '{self.operation}' does not accept value")
        elif self.operation is RuntimeEventOperation.set_fact:
            if self.value is None:
                raise ValueError(f"operation '{self.operation}' requires value")
            if self.minimum_amount is not None or self.maximum_amount is not None:
                raise ValueError(f"operation '{self.operation}' does not accept an amount range")
        else:
            if self.value is not None:
                raise ValueError(f"operation '{self.operation}' does not accept value")
            if self.minimum_amount is not None or self.maximum_amount is not None:
                raise ValueError(f"operation '{self.operation}' does not accept an amount range")
        return self


class RuntimeEventCandidate(ContractModel):
    event_id: str = Field(min_length=1)
    eligible_window: DateTimeWindow
    occurrence_probability: float = Field(ge=0, le=1)
    trigger_activity_id: str | None = None
    preconditions: list[Condition] = Field(default_factory=list)
    effects: list[RuntimeEventEffect] = Field(min_length=1)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class RequestedOutputs(ContractModel):
    observable_sensor_log: bool = True
    oracle_ground_truth: bool = True
    executed_activity_trace: bool = True
    plan_execution_diff: bool = True
    final_daily_diaries: bool = True
    final_scenario_state: bool = True
    formats: list[Literal["jsonl", "csv", "xes"]] = Field(default_factory=lambda: ["jsonl"])


class Scenario(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:scenario:1.0.0",
            "title": "Smart Home Life Scenario 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"]
    document_type: Literal["life_scenario"] = "life_scenario"
    scenario_id: str = Field(min_length=1)
    title: str | None = None
    language: str = Field(default="en", pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    time_zone: str
    simulation_window: SimulationWindow
    seed: int
    provenance: Provenance
    model_references: ModelReferences
    materialization_policy: MaterializationPolicy = Field(default_factory=MaterializationPolicy)
    residents: list[Resident] = Field(min_length=1)
    external_people: list[ExternalPerson] = Field(default_factory=list)
    locations: list[Location] = Field(min_length=1)
    resources: list[Resource] = Field(default_factory=list)
    initial_state: InitialState
    commitments: list[Commitment] = Field(default_factory=list)
    days: list[DayPlan] = Field(min_length=1)
    runtime_event_candidates: list[RuntimeEventCandidate] = Field(default_factory=list)
    declared_constraints: list[str] = Field(default_factory=list)
    requested_outputs: RequestedOutputs = Field(default_factory=RequestedOutputs)
    extensions: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("time_zone")
    @classmethod
    def check_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA time zone: {value}") from error
        return value
