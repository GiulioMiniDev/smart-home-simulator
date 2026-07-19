from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import (
    ActivationRule,
    Condition,
    ResourceRequirement,
    SimulationWindow,
    StateEffect,
)


class CompilerMetadata(ContractModel):
    compiler_name: Literal["smart-home-sim-plan-compiler"] = "smart-home-sim-plan-compiler"
    compiler_version: Literal["1.0.0"] = "1.0.0"
    solver_backend: Literal["or-tools-cp-sat"] = "or-tools-cp-sat"
    solver_version: Literal["9.15.6755"] = "9.15.6755"
    optimization_policy_version: Literal["priority-preference-1.0.0"] = "priority-preference-1.0.0"
    time_resolution: Literal["microsecond"] = "microsecond"


class ObjectiveValues(ContractModel):
    optional_priority_score: int = Field(ge=0)
    optional_activity_count: int = Field(ge=0)
    duration_deviation_microseconds: int = Field(ge=0)
    temporal_deviation_microseconds: int = Field(ge=0)
    scheduled_start_sum_microseconds: int = Field(ge=0)


class CanonicalActivity(ContractModel):
    source_activity_id: str = Field(min_length=1)
    sequence_index: int = Field(ge=0)
    actor_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    location_ids: list[str] = Field(min_length=1)
    scheduled_start: AwareDatetime
    scheduled_end: AwareDatetime
    duration_microseconds: int = Field(gt=0)
    mandatory: bool
    priority: int = Field(ge=0, le=100)
    can_overlap_for_actor: bool
    participant_ids: list[str] = Field(default_factory=list)
    required_resources: list[ResourceRequirement] = Field(default_factory=list)
    selected_dependency_ids: list[str] = Field(default_factory=list)
    preconditions: list[Condition] = Field(default_factory=list)
    effects: list[StateEffect] = Field(default_factory=list)
    activation: ActivationRule
    commitment_id: str | None = None
    truncated_at_simulation_end: bool = False


class OmittedActivity(ContractModel):
    source_activity_id: str = Field(min_length=1)
    reason: Literal[
        "optional_not_selected",
        "contingency_target_not_scheduled",
        "contingency_optional_not_selected",
        "contingency_main_activity_omitted",
    ]


class ContingencyPlan(ContractModel):
    contingency_id: str = Field(min_length=1)
    kind: Literal["fallback", "conditional"]
    activation: ActivationRule
    replaces_activity_id: str | None = None
    activities: list[CanonicalActivity] = Field(default_factory=list)
    rescheduled_activities: list[CanonicalActivity] = Field(default_factory=list)
    omitted_activities: list[OmittedActivity] = Field(default_factory=list)
    objective_values: ObjectiveValues


class CanonicalDay(ContractModel):
    date: date
    activities: list[CanonicalActivity] = Field(default_factory=list)
    contingencies: list[ContingencyPlan] = Field(default_factory=list)
    omitted_activities: list[OmittedActivity] = Field(default_factory=list)


class CanonicalPlan(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:canonical-plan:1.0.0",
            "title": "Smart Home Canonical Plan 1.0.0",
        },
    )

    plan_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["canonical_plan"] = "canonical_plan"
    source_scenario_version: Literal["1.0.0"] = "1.0.0"
    source_scenario_id: str = Field(min_length=1)
    source_scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    time_zone: str
    simulation_window: SimulationWindow
    compiler: CompilerMetadata = Field(default_factory=CompilerMetadata)
    objective_values: ObjectiveValues
    days: list[CanonicalDay] = Field(min_length=1)
