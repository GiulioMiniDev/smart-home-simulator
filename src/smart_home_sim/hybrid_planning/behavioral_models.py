from __future__ import annotations

from datetime import date as Date
from enum import StrEnum
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.hybrid_planning.models import TimeBand


class HabitKind(StrEnum):
    anchor = "anchor"
    contextual = "contextual"
    optional = "optional"
    rare = "rare"


class HabitCondition(ContractModel):
    dimension: Literal["calendar_day_type", "season", "weather", "social", "custom"]
    operator: Literal["eq", "not_eq", "in", "not_in"]
    value: JsonValue


class HabitCadence(ContractModel):
    minimum_occurrences: int = Field(ge=0, le=31)
    typical_occurrences: int = Field(ge=1, le=31)
    maximum_occurrences: int = Field(ge=1, le=31)
    period_days: int = Field(ge=1, le=366)

    @model_validator(mode="after")
    def check_bounds(self) -> HabitCadence:
        if not self.minimum_occurrences <= self.typical_occurrences <= self.maximum_occurrences:
            raise ValueError(
                "minimumOccurrences <= typicalOccurrences <= maximumOccurrences is required"
            )
        return self


class HabitDrift(ContractModel):
    effective_from: Date
    rationale: str = Field(min_length=12)
    cadence_override: HabitCadence | None = None
    preferred_time_bands_override: list[TimeBand] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_override(self) -> HabitDrift:
        if self.cadence_override is None and not self.preferred_time_bands_override:
            raise ValueError("habit drift requires a cadence or time-band override")
        return self


class BehavioralHabit(ContractModel):
    habit_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    kind: HabitKind
    rationale: str = Field(min_length=12)
    cadence: HabitCadence
    applicable_day_types: list[str] = Field(default_factory=list)
    preferred_time_bands: list[TimeBand] = Field(min_length=1)
    temporal_jitter_minutes: int = Field(ge=0, le=240)
    execution_probability: float = Field(ge=0, le=1)
    exception_probability: float = Field(ge=0, le=1)
    cooldown_days: int = Field(ge=0, le=366)
    location_ids: list[str] = Field(min_length=1)
    predecessor_intents: list[str] = Field(default_factory=list)
    successor_intents: list[str] = Field(default_factory=list)
    incompatible_habit_ids: list[str] = Field(default_factory=list)
    context_conditions: list[HabitCondition] = Field(default_factory=list)
    seasonality: str = Field(min_length=1)
    mining_difficulty: Literal["easy", "medium", "hard"]
    drifts: list[HabitDrift] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_probabilities(self) -> BehavioralHabit:
        if self.execution_probability + self.exception_probability > 1.000001:
            raise ValueError("executionProbability + exceptionProbability must not exceed 1")
        return self


class BehavioralProfile(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["behavioral_profile"] = "behavioral_profile"
    profile_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    source_case_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    effective_from: Date
    immutable_facts: dict[str, JsonValue]
    synthetic_traits: dict[str, JsonValue] = Field(min_length=6)
    habits: list[BehavioralHabit] = Field(min_length=8, max_length=24)

    @model_validator(mode="after")
    def check_unique_habits(self) -> BehavioralProfile:
        ids = [item.habit_id for item in self.habits]
        intents = [item.intent for item in self.habits]
        if len(ids) != len(set(ids)) or len(intents) != len(set(intents)):
            raise ValueError("habitId and intent must be unique within a behavioral profile")
        return self


class HabitLedgerEntry(ContractModel):
    habit_id: str = Field(min_length=1)
    total_occurrences: int = Field(default=0, ge=0)
    last_seen: Date | None = None
    cadence_carry: float = 0.0


class HabitLedger(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["habit_ledger"] = "habit_ledger"
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    through_date: Date | None = None
    entries: list[HabitLedgerEntry]


class HabitBudgetItem(ContractModel):
    habit_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    required_occurrences: int = Field(ge=0)
    target_occurrences: int = Field(ge=0)
    maximum_occurrences: int = Field(ge=0)
    forbidden_until: Date | None = None


class HabitBudget(ContractModel):
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_date: Date
    end_date: Date
    items: list[HabitBudgetItem]


class HabitViolation(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    date: Date | None = None
    habit_id: str | None = None
    intent: str | None = None


class HabitGateReport(ContractModel):
    valid: bool
    violations: list[HabitViolation] = Field(default_factory=list)


class PlannedHabitOccurrence(ContractModel):
    habit_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    date: Date
    time_band: TimeBand


class HabitTraceMetric(ContractModel):
    habit_id: str = Field(min_length=1)
    expected_occurrences: float = Field(ge=0)
    planned_occurrences: int = Field(ge=0)
    temporal_adherence: float = Field(ge=0, le=1)
    sequence_adherence: float = Field(ge=0, le=1)
    mining_difficulty: Literal["easy", "medium", "hard"]


class PlannedHabitTrace(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["planned_habit_trace"] = "planned_habit_trace"
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurrences: list[PlannedHabitOccurrence]
    metrics: list[HabitTraceMetric]
