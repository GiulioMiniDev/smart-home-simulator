from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.environment import Point2D, Polygon2D

SENSOR_PROJECTION_ISSUE_CODES = frozenset(
    {
        "FILE_ENCODING_ERROR",
        "FILE_NOT_FOUND",
        "FILE_READ_ERROR",
        "FILE_TOO_LARGE",
        "JSON_NESTING_TOO_DEEP",
        "JSON_SYNTAX",
        "BUNDLE_TRACE_MISMATCH",
        "HOME_SENSOR_MISMATCH",
        "MODEL_TRACE_MISMATCH",
        "OUTPUT_WRITE_ERROR",
        "OUTPUT_CONFLICT",
        "PROJECTION_FAILED",
        "SENSOR_REFERENCE_INVALID",
        "STRUCTURE_INVALID",
        "TRACE_DIGEST_MISMATCH",
        "UNSUPPORTED_SCHEMA_VERSION",
    }
)


class SensorTiming(ContractModel):
    latency_milliseconds: float = Field(default=0, ge=0)
    clock_jitter_milliseconds: float = Field(default=0, ge=0)
    cooldown_milliseconds: float = Field(default=0, ge=0)


class SensorErrorModel(ContractModel):
    dropout_probability: float = Field(default=0, ge=0, le=1)
    false_negative_probability: float = Field(default=0, ge=0, le=1)
    false_positive_probability_per_day: float = Field(default=0, ge=0, le=1)
    measurement_noise_standard_deviation: float = Field(default=0, ge=0)


class SensorFailureWindow(ContractModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def check_interval(self) -> SensorFailureWindow:
        if self.starts_at >= self.ends_at:
            raise ValueError("sensor failure startsAt must precede endsAt")
        return self


class SensorBase(ContractModel):
    sensor_id: str = Field(min_length=1)
    position: Point2D
    timing: SensorTiming = Field(default_factory=SensorTiming)
    error_model: SensorErrorModel = Field(default_factory=SensorErrorModel)
    failure_windows: list[SensorFailureWindow] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_failure_windows(self) -> SensorBase:
        ordered = sorted(self.failure_windows, key=lambda item: item.starts_at)
        if any(
            left.ends_at > right.starts_at
            for left, right in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("sensor failureWindows must not overlap")
        return self


class PirSensor(SensorBase):
    sensor_type: Literal["pir"] = "pir"
    region_ids: list[str] = Field(min_length=1)
    coverage: Polygon2D
    hold_milliseconds: float = Field(default=30_000, gt=0)
    hold_log_sigma: float = Field(default=0.0, ge=0, le=2)

    @model_validator(mode="after")
    def check_regions(self) -> PirSensor:
        if len(self.region_ids) != len(set(self.region_ids)):
            raise ValueError("PIR regionIds must not contain duplicates")
        if self.error_model.measurement_noise_standard_deviation != 0:
            raise ValueError("PIR sensors do not support measurement noise")
        return self


class ContactSensor(SensorBase):
    sensor_type: Literal["contact"] = "contact"
    entity_id: str = Field(min_length=1)
    fact: str | None = Field(default="open", min_length=1)
    action_types: list[str] = Field(default_factory=list)
    action_trigger: Literal["started", "ended"] = "ended"
    pulse_milliseconds: float = Field(default=1000, gt=0)
    pulse_log_sigma: float = Field(default=0.0, ge=0, le=2)
    open_value: JsonValue = True
    closed_value: JsonValue = False

    @model_validator(mode="after")
    def check_values(self) -> ContactSensor:
        if self.open_value == self.closed_value:
            raise ValueError("contact openValue and closedValue must differ")
        if (self.fact is None) == (not self.action_types):
            raise ValueError("contact sensors require exactly one fact or actionTypes source")
        if len(self.action_types) != len(set(self.action_types)):
            raise ValueError("contact actionTypes must not contain duplicates")
        if self.error_model.measurement_noise_standard_deviation != 0:
            raise ValueError("contact sensors do not support measurement noise")
        return self


class TemperatureSource(ContractModel):
    entity_id: str = Field(min_length=1)
    fact: str = Field(min_length=1)
    active_value: JsonValue = True
    delta_celsius: float
    response_delay_seconds: float = Field(default=0, ge=0)
    rise_duration_seconds: float = Field(default=0, ge=0)
    decay_duration_seconds: float = Field(default=0, ge=0)
    sample_interval_seconds: float = Field(default=60, gt=0)

    @model_validator(mode="after")
    def check_response(self) -> TemperatureSource:
        if self.delta_celsius == 0:
            raise ValueError("temperature deltaCelsius must not be zero")
        return self


class TemperatureSensor(SensorBase):
    sensor_type: Literal["temperature"] = "temperature"
    region_id: str = Field(min_length=1)
    baseline_celsius: float = Field(ge=-100, le=100)
    climate_profile: Literal["fixed", "city_seasonal"] = "fixed"
    room_offset_celsius: float = Field(default=0.0, ge=-10, le=10)
    thermal_time_constant_hours: float = Field(default=0.0, ge=0, le=72)
    quantization_celsius: float = Field(default=0.5, gt=0, le=10)
    sample_phase_seconds: float = Field(default=0.0, ge=0)
    sources: list[TemperatureSource] = Field(min_length=1)

    @model_validator(mode="after")
    def check_sources(self) -> TemperatureSensor:
        keys = [(item.entity_id, item.fact) for item in self.sources]
        if len(keys) != len(set(keys)):
            raise ValueError("temperature sources must be unique by entityId and fact")
        return self


SensorDefinition = Annotated[
    PirSensor | ContactSensor | TemperatureSensor,
    Field(discriminator="sensor_type"),
]


class SensorModel(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:sensor-model:1.0.0",
            "title": "Smart Home Sensor Model 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["sensor_model"] = "sensor_model"
    sensor_model_id: str = Field(min_length=1)
    sensor_model_version: str = Field(min_length=1)
    source_bundle_id: str = Field(min_length=1)
    source_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int
    region_ids: list[str] = Field(min_length=1)
    entity_ids: list[str] = Field(min_length=1)
    sensors: list[SensorDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def check_sensor_ids(self) -> SensorModel:
        identifiers = [item.sensor_id for item in self.sensors]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("sensorId values must be unique")
        if len(self.region_ids) != len(set(self.region_ids)):
            raise ValueError("regionIds must not contain duplicates")
        if len(self.entity_ids) != len(set(self.entity_ids)):
            raise ValueError("entityIds must not contain duplicates")
        known_regions = set(self.region_ids)
        known_entities = set(self.entity_ids)
        for sensor in self.sensors:
            referenced_regions = (
                set(sensor.region_ids)
                if isinstance(sensor, PirSensor)
                else {sensor.region_id}
                if isinstance(sensor, TemperatureSensor)
                else set()
            )
            referenced_entities = (
                {sensor.entity_id}
                if isinstance(sensor, ContactSensor)
                else {source.entity_id for source in sensor.sources}
                if isinstance(sensor, TemperatureSensor)
                else set()
            )
            if not referenced_regions <= known_regions:
                raise ValueError(f"sensor '{sensor.sensor_id}' references an unknown region")
            if not referenced_entities <= known_entities:
                raise ValueError(f"sensor '{sensor.sensor_id}' references an unknown entity")
        return self


class ObservableSensorRecord(ContractModel):
    observation_id: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    sensor_type: Literal["pir", "contact", "temperature"]
    observed_at: AwareDatetime
    measurement: Literal["motion", "contact", "temperature"]
    value: JsonValue
    unit: Literal["celsius"] | None = None
    quality: Literal["nominal", "noisy"] = "nominal"

    @model_validator(mode="after")
    def check_measurement(self) -> ObservableSensorRecord:
        if self.sensor_type == "pir":
            valid = self.measurement == "motion" and self.value in ("ON", "OFF")
            valid = valid and self.unit is None
        elif self.sensor_type == "contact":
            valid = self.measurement == "contact" and self.value in ("OPEN", "CLOSED")
            valid = valid and self.unit is None
        else:
            valid = (
                self.measurement == "temperature"
                and isinstance(self.value, (int, float))
                and not isinstance(self.value, bool)
                and self.unit == "celsius"
            )
        if not valid:
            raise ValueError("sensor type, measurement, value and unit are inconsistent")
        return self


class ObservableSensorLog(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:observable-sensor-log:1.0.0",
            "title": "Smart Home Observable Sensor Log 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["observable_sensor_log"] = "observable_sensor_log"
    log_id: str = Field(min_length=1)
    sensor_model_id: str = Field(min_length=1)
    sensor_model_version: str = Field(min_length=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    records: list[ObservableSensorRecord]
    semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_records(self) -> ObservableSensorLog:
        if self.started_at > self.ended_at:
            raise ValueError("sensor log start must not follow its end")
        if any(record.observed_at < self.started_at for record in self.records):
            raise ValueError("sensor records must not precede startedAt")
        identifiers = [item.observation_id for item in self.records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("observationId values must be unique")
        if self.records != sorted(
            self.records,
            key=lambda item: (item.observed_at, item.sensor_id, item.observation_id),
        ):
            raise ValueError("sensor records must be sorted by time, sensorId and observationId")
        semantic = {
            "sensorModelId": self.sensor_model_id,
            "sensorModelVersion": self.sensor_model_version,
            "records": [item.model_dump(mode="json", by_alias=True) for item in self.records],
        }
        digest = _canonical_sha256(semantic)
        if self.semantic_digest != digest or self.log_id != f"sensor_log_{digest[:16]}":
            raise ValueError("sensor log identifiers do not match its semantic content")
        return self


class OracleObservationLink(ContractModel):
    observation_id: str = Field(min_length=1)
    origin: Literal["simulated_cause", "environment_model", "false_positive", "initial_state"]
    cause_type: Literal["movement", "state_transition", "action_execution", "trace", "noise"]
    cause_ids: list[str] = Field(default_factory=list)
    resident_ids: list[str] = Field(default_factory=list)
    activity_execution_ids: list[str] = Field(default_factory=list)
    action_execution_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_cause(self) -> OracleObservationLink:
        if self.origin == "false_positive" and (self.cause_type != "noise" or self.cause_ids):
            raise ValueError("false positives require a noise cause without simulated causeIds")
        if self.origin != "false_positive" and not self.cause_ids:
            raise ValueError("non-noise oracle links require at least one causeId")
        if self.origin == "initial_state" and self.cause_type != "trace":
            raise ValueError("initial-state links require a trace cause")
        if self.origin == "environment_model" and self.cause_type != "trace":
            raise ValueError("environment-model links require a trace cause")
        if self.origin == "simulated_cause" and self.cause_type not in {
            "movement",
            "state_transition",
            "action_execution",
        }:
            raise ValueError("simulated observations require an executed cause")
        return self


class OracleMapping(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:oracle-mapping:1.0.0",
            "title": "Smart Home Sensor Oracle Mapping 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["oracle_mapping"] = "oracle_mapping"
    mapping_id: str = Field(min_length=1)
    observable_log_id: str = Field(min_length=1)
    source_trace_id: str = Field(min_length=1)
    source_trace_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    links: list[OracleObservationLink]

    @model_validator(mode="after")
    def check_links(self) -> OracleMapping:
        identifiers = [item.observation_id for item in self.links]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("oracle observationId values must be unique")
        digest = _canonical_sha256([item.model_dump(mode="json") for item in self.links])
        if self.mapping_id != f"oracle_{digest[:16]}":
            raise ValueError("oracle mappingId does not match its links")
        return self


class SensorProjectionIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(SENSOR_PROJECTION_ISSUE_CODES)})
    severity: Literal["error", "warning"] = "error"
    stage: Literal["input", "compatibility", "projection", "output"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_code(self) -> SensorProjectionIssue:
        if self.code not in SENSOR_PROJECTION_ISSUE_CODES:
            raise ValueError(f"unknown sensor projection issue code '{self.code}'")
        return self


class SensorProjectionSensorSummary(ContractModel):
    sensor_id: str = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    dropout_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    cooldown_suppressed_count: int = Field(ge=0)
    failure_suppressed_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    noisy_observation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def check_counts(self) -> SensorProjectionSensorSummary:
        accounted = (
            self.observation_count
            + self.dropout_count
            + self.false_negative_count
            + self.cooldown_suppressed_count
            + self.failure_suppressed_count
        )
        if accounted != self.candidate_count:
            raise ValueError("sensor candidate count is not fully accounted")
        if (
            self.false_positive_count > self.observation_count
            or self.noisy_observation_count > self.observation_count
            or self.false_positive_count > self.noisy_observation_count
        ):
            raise ValueError("sensor noise counts are inconsistent")
        return self


class SensorProjectionSummary(ContractModel):
    sensor_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    dropout_count: int = Field(ge=0)
    false_negative_count: int = Field(ge=0)
    cooldown_suppressed_count: int = Field(ge=0)
    failure_suppressed_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    noisy_observation_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class SensorProjectionReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:sensor-projection-report:1.0.0",
            "title": "Smart Home Sensor Projection Report 1.0.0",
        },
    )

    report_version: Literal["1.0.0"] = "1.0.0"
    projector_name: Literal["smart-home-sim-sensor-projector"] = "smart-home-sim-sensor-projector"
    projector_version: Literal["1.0.0", "1.1.0"] = "1.1.0"
    projection_policy_version: Literal[
        "event-driven-sensors-1.0.0",
        "event-driven-sensors-1.1.0",
        "event-driven-sensors-1.2.0",
    ] = "event-driven-sensors-1.0.0"
    random_stream_policy: Literal["sha256-named-streams-1.0.0"] = "sha256-named-streams-1.0.0"
    success: bool
    source_bundle_id: str | None = None
    source_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_home_id: str | None = None
    source_home_version: str | None = None
    source_home_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_trace_id: str | None = None
    source_trace_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_trace_semantic_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    sensor_model_id: str | None = None
    sensor_model_version: str | None = None
    sensor_model_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observable_log_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    oracle_mapping_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    projected_at: AwareDatetime
    issues: list[SensorProjectionIssue] = Field(default_factory=list)
    sensors: list[SensorProjectionSensorSummary] = Field(default_factory=list)
    summary: SensorProjectionSummary

    @model_validator(mode="after")
    def check_report(self) -> SensorProjectionReport:
        totals = {
            name: sum(getattr(item, name) for item in self.sensors)
            for name in (
                "candidate_count",
                "observation_count",
                "dropout_count",
                "false_negative_count",
                "cooldown_suppressed_count",
                "failure_suppressed_count",
                "false_positive_count",
                "noisy_observation_count",
            )
        }
        if self.summary.sensor_count != len(self.sensors) or any(
            getattr(self.summary, name) != value for name, value in totals.items()
        ):
            raise ValueError("projection summary does not match per-sensor counts")
        errors = sum(item.severity == "error" for item in self.issues)
        warnings = sum(item.severity == "warning" for item in self.issues)
        if self.summary.error_count != errors or self.summary.warning_count != warnings:
            raise ValueError("projection issue counts do not match issues")
        successful_metadata = (
            self.source_bundle_id,
            self.source_bundle_sha256,
            self.source_home_id,
            self.source_home_version,
            self.source_home_sha256,
            self.source_trace_id,
            self.source_trace_sha256,
            self.source_trace_semantic_digest,
            self.sensor_model_id,
            self.sensor_model_version,
            self.sensor_model_sha256,
            self.observable_log_sha256,
            self.oracle_mapping_sha256,
        )
        if self.success != (errors == 0):
            raise ValueError("projection success is inconsistent with errors")
        if self.success and not all(successful_metadata):
            raise ValueError("successful projection requires complete provenance")
        if not self.success and (
            self.observable_log_sha256 is not None or self.oracle_mapping_sha256 is not None
        ):
            raise ValueError("failed projection cannot claim successful output artifacts")
        return self


class SensorProjectionResult(ContractModel):
    report: SensorProjectionReport
    observable_log: ObservableSensorLog | None = None
    oracle_mapping: OracleMapping | None = None

    @model_validator(mode="after")
    def check_artifacts(self) -> SensorProjectionResult:
        if not self.report.success:
            if self.observable_log is not None or self.oracle_mapping is not None:
                raise ValueError("failed projections must not contain data artifacts")
            return self
        if self.observable_log is None or self.oracle_mapping is None:
            raise ValueError("successful projections require observable and oracle artifacts")
        observable_ids = [item.observation_id for item in self.observable_log.records]
        oracle_ids = [item.observation_id for item in self.oracle_mapping.links]
        if (
            observable_ids != oracle_ids
            or self.oracle_mapping.observable_log_id != self.observable_log.log_id
            or self.report.observable_log_sha256 != _canonical_sha256(self.observable_log)
            or self.report.oracle_mapping_sha256 != _canonical_sha256(self.oracle_mapping)
        ):
            raise ValueError("projection artifacts are not mutually consistent")
        return self


def _canonical_sha256(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)  # type: ignore[union-attr]
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
