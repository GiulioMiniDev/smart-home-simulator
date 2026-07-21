from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.environment import HomeModel
from smart_home_sim.domain.sensors import SensorModel


class HomeGenerationPolicy(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:home-generation-policy:1.0.0",
            "title": "Smart Home Deterministic Home Generation Policy 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["home_generation_policy"] = "home_generation_policy"
    policy_id: Literal["compact-grid"] = "compact-grid"
    policy_version: Literal["1.1.0"] = "1.1.0"
    room_width_meters: float = Field(default=6.0, ge=4.0, le=20.0)
    room_height_meters: float = Field(default=6.0, ge=4.0, le=20.0)
    external_spacing_meters: float = Field(default=12.0, ge=8.0, le=1000.0)
    doorway_width_meters: float = Field(default=1.0, ge=0.8, le=3.0)
    transport_distance_meters: float = Field(default=500.0, gt=0, le=1_000_000.0)


class SensorDeploymentPolicy(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:sensor-deployment-policy:1.0.0",
            "title": "Smart Home Deterministic Sensor Deployment Policy 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["sensor_deployment_policy"] = "sensor_deployment_policy"
    policy_version: Literal["1.1.0"] = "1.1.0"
    preset: Literal["minimal", "room_coverage", "dense"] = "room_coverage"
    pir_hold_milliseconds: float = Field(default=5_000, gt=0)
    pir_cooldown_milliseconds: float = Field(default=750, ge=0)
    contact_pulse_milliseconds: float = Field(default=1000, gt=0)
    temperature_baseline_celsius: float = Field(default=20.0, ge=-100, le=100)
    temperature_sample_interval_seconds: float = Field(default=900, gt=0)
    temperature_source_delta_celsius: float = Field(default=0.5, gt=0, le=20)
    dropout_probability: float = Field(default=0.0, ge=0, le=1)
    false_negative_probability: float = Field(default=0.0, ge=0, le=1)
    false_positive_probability_per_day: float = Field(default=0.0, ge=0, le=1)
    temperature_noise_standard_deviation: float = Field(default=0.0, ge=0)


class MaterializationIssue(ContractModel):
    code: str = Field(min_length=1)
    stage: Literal[
        "input", "home", "compile", "bundle", "sensor", "simulation", "projection", "output"
    ]
    path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class HomeGenerationSummary(ContractModel):
    region_count: int = Field(ge=0)
    connection_count: int = Field(ge=0)
    entity_count: int = Field(ge=0)
    location_binding_count: int = Field(ge=0)
    resource_binding_count: int = Field(ge=0)
    error_count: int = Field(ge=0)


class HomeGenerationReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:home-generation-report:1.0.0",
            "title": "Smart Home Deterministic Home Generation Report 1.0.0",
        },
    )

    report_version: Literal["1.0.0"] = "1.0.0"
    generator_name: Literal["smart-home-sim-home-generator"] = "smart-home-sim-home-generator"
    generator_version: Literal["1.1.0"] = "1.1.0"
    success: bool
    policy_id: str
    policy_version: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_scenario_id: str
    source_scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_behavior_package_id: str
    source_behavior_package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    home_id: str | None = None
    home_version: str | None = None
    home_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issues: list[MaterializationIssue] = Field(default_factory=list)
    summary: HomeGenerationSummary

    @model_validator(mode="after")
    def check_result(self) -> HomeGenerationReport:
        errors = len(self.issues)
        if self.summary.error_count != errors or self.success != (errors == 0):
            raise ValueError("home generation status does not match its issues")
        if self.success != all((self.home_id, self.home_version, self.home_sha256)):
            raise ValueError("home generation provenance is incomplete")
        return self


class HomeGenerationResult(ContractModel):
    report: HomeGenerationReport
    home: HomeModel | None = None

    @model_validator(mode="after")
    def check_artifact(self) -> HomeGenerationResult:
        if self.report.success != (self.home is not None):
            raise ValueError("home generation result and report disagree")
        return self


class SensorDeploymentSummary(ContractModel):
    sensor_count: int = Field(ge=0)
    pir_count: int = Field(ge=0)
    contact_count: int = Field(ge=0)
    temperature_count: int = Field(ge=0)
    error_count: int = Field(ge=0)


class SensorDeploymentReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:sensor-deployment-report:1.0.0",
            "title": "Smart Home Deterministic Sensor Deployment Report 1.0.0",
        },
    )

    report_version: Literal["1.0.0"] = "1.0.0"
    generator_name: Literal["smart-home-sim-sensor-deployer"] = "smart-home-sim-sensor-deployer"
    generator_version: Literal["1.1.0"] = "1.1.0"
    success: bool
    preset: str
    policy_version: str
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_bundle_id: str
    source_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_home_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sensor_model_id: str | None = None
    sensor_model_version: str | None = None
    sensor_model_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issues: list[MaterializationIssue] = Field(default_factory=list)
    summary: SensorDeploymentSummary

    @model_validator(mode="after")
    def check_result(self) -> SensorDeploymentReport:
        errors = len(self.issues)
        if self.summary.error_count != errors or self.success != (errors == 0):
            raise ValueError("sensor deployment status does not match its issues")
        if self.success != all(
            (self.sensor_model_id, self.sensor_model_version, self.sensor_model_sha256)
        ):
            raise ValueError("sensor deployment provenance is incomplete")
        counts = (
            self.summary.pir_count + self.summary.contact_count + self.summary.temperature_count
        )
        if counts != self.summary.sensor_count:
            raise ValueError("sensor deployment counts are inconsistent")
        return self


class SensorDeploymentResult(ContractModel):
    report: SensorDeploymentReport
    sensor_model: SensorModel | None = None

    @model_validator(mode="after")
    def check_artifact(self) -> SensorDeploymentResult:
        if self.report.success != (self.sensor_model is not None):
            raise ValueError("sensor deployment result and report disagree")
        return self


class WorkspaceArtifact(ContractModel):
    role: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SyntheticWorkspaceManifest(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:synthetic-workspace-manifest:1.0.0",
            "title": "Smart Home Synthetic Workspace Manifest 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["synthetic_workspace_manifest"] = "synthetic_workspace_manifest"
    workflow_version: Literal["scenario-first-1.0.0"] = "scenario-first-1.0.0"
    success: Literal[True] = True
    scenario_id: str
    bundle_id: str
    trace_id: str
    sensor_log_id: str
    artifacts: list[WorkspaceArtifact] = Field(min_length=1)

    @model_validator(mode="after")
    def check_artifacts(self) -> SyntheticWorkspaceManifest:
        roles = [item.role for item in self.artifacts]
        paths = [item.relative_path for item in self.artifacts]
        if len(roles) != len(set(roles)) or len(paths) != len(set(paths)):
            raise ValueError("workspace artifact roles and paths must be unique")
        return self
