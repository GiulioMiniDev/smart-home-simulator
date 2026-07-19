from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class ResidentConfig(ContractModel):
    resident_id: str
    initial_room: str
    walking_speed_meters_per_second: float = Field(default=1.25, gt=0)


class RoomConfig(ContractModel):
    room_id: str
    connections: list[str] = Field(default_factory=list)


class PirSensorConfig(ContractModel):
    sensor_id: str
    type: Literal["pir"] = "pir"
    room: str
    reset_seconds: float = Field(default=6.0, gt=0)
    cooldown_seconds: float = Field(default=1.0, ge=0)
    false_negative_probability: float = Field(default=0.0, ge=0, le=1)


class ActivityPlan(ContractModel):
    activity_id: str
    actor_id: str
    intent: str
    destination: str
    start_minute: float = Field(ge=0, lt=1440)
    duration_minutes: float = Field(gt=0)


class Scenario(ContractModel):
    schema_version: Literal["0.1"]
    scenario_id: str
    simulation_date: date
    time_zone: str = "Europe/Rome"
    seed: int = 0
    resident: ResidentConfig
    rooms: list[RoomConfig]
    sensors: list[PirSensorConfig]
    activities: list[ActivityPlan]


class RawSensorEvent(ContractModel):
    timestamp: datetime
    sensor_id: str
    value: Literal["ON", "OFF"]


class GroundTruthEvent(ContractModel):
    start: datetime
    end: datetime
    actor_id: str
    activity_id: str
    primitive: str
    room: str


class ActivityExecution(ContractModel):
    activity_id: str
    planned_start: datetime
    actual_start: datetime
    actual_end: datetime


class SimulationResult(ContractModel):
    scenario_id: str
    raw_sensor_events: list[RawSensorEvent]
    ground_truth: list[GroundTruthEvent]
    activity_executions: list[ActivityExecution]
