from __future__ import annotations

from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, JsonValue, field_validator, model_validator

from smart_home_sim.domain.base import ContractModel


class Provenance(ContractModel):
    author_type: Literal["human", "external_llm", "rule_generator", "import"]
    generator_name: str | None = None
    prompt_template_version: str | None = None


class Resident(ContractModel):
    resident_id: str = Field(min_length=1)
    initial_location_id: str = Field(min_length=1)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class Location(ContractModel):
    location_id: str = Field(min_length=1)
    kind: Literal["room", "external", "transit"]
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class Resource(ContractModel):
    resource_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    location_id: str = Field(min_length=1)
    capacity: int = Field(default=1, ge=1)


class TimeWindow(ContractModel):
    earliest: time
    preferred: time
    latest: time

    @model_validator(mode="after")
    def check_order(self) -> TimeWindow:
        if not self.earliest <= self.preferred <= self.latest:
            raise ValueError("start times must satisfy earliest <= preferred <= latest")
        return self


class DurationRange(ContractModel):
    minimum_minutes: float = Field(gt=0)
    preferred_minutes: float = Field(gt=0)
    maximum_minutes: float = Field(gt=0)

    @model_validator(mode="after")
    def check_order(self) -> DurationRange:
        if not self.minimum_minutes <= self.preferred_minutes <= self.maximum_minutes:
            raise ValueError(
                "durations must satisfy minimumMinutes <= preferredMinutes <= maximumMinutes"
            )
        return self


class ActivityTiming(ContractModel):
    start: TimeWindow
    duration: DurationRange


class Activity(ContractModel):
    activity_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    timing: ActivityTiming
    mandatory: bool = True
    after: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    required_resources: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)


class DayPlan(ContractModel):
    date: date
    activities: list[Activity] = Field(default_factory=list)
    context: dict[str, JsonValue] = Field(default_factory=dict)


class Scenario(ContractModel):
    schema_version: Literal["0.1.0"]
    scenario_id: str = Field(min_length=1)
    time_zone: str
    start_date: date
    end_date: date
    seed: int
    provenance: Provenance
    residents: list[Resident] = Field(min_length=1)
    locations: list[Location] = Field(min_length=1)
    resources: list[Resource] = Field(default_factory=list)
    days: list[DayPlan] = Field(min_length=1)

    @field_validator("time_zone")
    @classmethod
    def check_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA time zone: {value}") from error
        return value

    @model_validator(mode="after")
    def check_date_range(self) -> Scenario:
        if self.start_date > self.end_date:
            raise ValueError("startDate must be on or before endDate")
        return self
