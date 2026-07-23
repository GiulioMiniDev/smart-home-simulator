from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import (
    InitialState,
    Location,
    ModelReferences,
    Resident,
    Resource,
    SimulationWindow,
)


class TimeBand(StrEnum):
    early_morning = "early_morning"
    morning = "morning"
    midday = "midday"
    afternoon = "afternoon"
    evening = "evening"
    night = "night"


class DurationClass(StrEnum):
    brief = "brief"
    short = "short"
    medium = "medium"
    long = "long"
    extended = "extended"


class CalendarDay(ContractModel):
    date: date
    day_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class RoutineRequirement(ContractModel):
    intent: str = Field(min_length=1)
    day_types: list[str] = Field(default_factory=list)
    time_band: TimeBand | None = None
    minimum_occurrences: int = Field(default=1, ge=1, le=4)
    maximum_occurrences: int = Field(default=1, ge=1, le=4)

    @model_validator(mode="after")
    def check_occurrences(self) -> RoutineRequirement:
        if self.maximum_occurrences < self.minimum_occurrences:
            raise ValueError("maximumOccurrences must be >= minimumOccurrences")
        return self


class PlanningCase(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["hybrid_planning_case"] = "hybrid_planning_case"
    case_id: str = Field(min_length=1)
    language: str = Field(default="en", pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    time_zone: str
    planning_window: SimulationWindow
    seed: int
    resident: Resident
    model_references: ModelReferences
    locations: list[Location] = Field(min_length=1)
    resources: list[Resource] = Field(default_factory=list)
    initial_state: InitialState
    calendar: list[CalendarDay] = Field(default_factory=list)
    routine_requirements: list[RoutineRequirement] = Field(default_factory=list)
    context_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_case(self) -> PlanningCase:
        zone = ZoneInfo(self.time_zone)
        start_date = self.planning_window.start.astimezone(zone).date()
        end_date = self.planning_window.end.astimezone(zone).date()
        if self.initial_state.at != self.planning_window.start:
            raise ValueError("initialState.at must equal planningWindow.start")
        if self.planning_window.start.astimezone(zone).time().isoformat() != "00:00:00":
            raise ValueError("planningWindow.start must be local midnight")
        if self.planning_window.end.astimezone(zone).time().isoformat() != "00:00:00":
            raise ValueError("planningWindow.end must be local midnight")
        expected = (end_date - start_date).days
        if expected < 1:
            raise ValueError("planning window must contain at least one local date")
        calendar_dates = [item.date for item in self.calendar]
        if len(calendar_dates) != len(set(calendar_dates)):
            raise ValueError("calendar dates must be unique")
        if any(not start_date <= item < end_date for item in calendar_dates):
            raise ValueError("calendar entries must be inside the planning window")
        resident_ids = {item.resident_id for item in self.initial_state.residents}
        if self.resident.resident_id not in resident_ids:
            raise ValueError("initialState must contain the planning resident")
        return self

    def dates(self) -> list[date]:
        zone = ZoneInfo(self.time_zone)
        current = self.planning_window.start.astimezone(zone).date()
        end = self.planning_window.end.astimezone(zone).date()
        result: list[date] = []
        while current < end:
            result.append(current)
            current += timedelta(days=1)
        return result

    def calendar_day(self, value: date) -> CalendarDay:
        explicit = next((item for item in self.calendar if item.date == value), None)
        if explicit is not None:
            return explicit
        return CalendarDay(date=value, day_type="workday" if value.weekday() < 5 else "weekend")


class WeeklyDayBrief(ContractModel):
    date: date
    day_type: str = Field(min_length=1)
    narrative_intent: str = Field(min_length=1)
    distinctive_goals: list[str] = Field(min_length=1, max_length=5)
    goal_intents: list[str] = Field(default_factory=list, max_length=5)


class WeeklyBrief(ContractModel):
    week_theme: str = Field(min_length=1)
    variety_strategy: list[str] = Field(min_length=2, max_length=8)
    days: list[WeeklyDayBrief] = Field(min_length=1, max_length=7)


class ProposedActivity(ContractModel):
    intent: str = Field(min_length=1)
    location_id: str = Field(min_length=1)
    time_band: TimeBand
    duration_class: DurationClass
    mandatory: bool
    priority: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1)


class DailyProposal(ContractModel):
    date: date
    narrative_intent: str = Field(min_length=1)
    activities: list[ProposedActivity] = Field(min_length=4, max_length=16)


class PlanningMemory(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    through_date: date | None = None
    recent_days: list[dict[str, object]] = Field(default_factory=list, max_length=14)
    intent_frequency: dict[str, int] = Field(default_factory=dict)
    intent_last_seen: dict[str, date] = Field(default_factory=dict)
    day_signatures: list[str] = Field(default_factory=list, max_length=30)


class HybridPlanningConfig(ContractModel):
    model: str = Field(min_length=1)
    base_url: str = "http://127.0.0.1:1234"
    temperature: float = Field(default=0.65, ge=0, le=2)
    top_p: float = Field(default=0.9, gt=0, le=1)
    max_tokens: int = Field(default=4096, ge=256)
    timeout_seconds: int = Field(default=600, ge=1)
    max_structure_repairs: int = Field(default=2, ge=0, le=2)
    max_diversity_repairs: int = Field(default=2, ge=0, le=2)
    max_habit_repairs: int = Field(default=2, ge=0, le=2)


class DiversityMetrics(ContractModel):
    day_count: int = Field(ge=0)
    distinct_day_signatures: int = Field(ge=0)
    mean_pairwise_jaccard: float = Field(ge=0, le=1)
    maximum_pairwise_jaccard: float = Field(ge=0, le=1)
    exact_repeated_day_pairs: int = Field(ge=0)
    passes_gate: bool
    reasons: list[str] = Field(default_factory=list)
