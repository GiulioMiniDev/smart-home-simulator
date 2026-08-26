from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.behavior import PersonalProcessPackage
from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.plan import CanonicalPlan


class RegionKind(StrEnum):
    room = "room"
    outdoor = "outdoor"
    external = "external"
    transit = "transit"


class ConnectionKind(StrEnum):
    doorway = "doorway"
    passage = "passage"
    transit = "transit"


class TraversalMode(StrEnum):
    walking = "walking"
    transport = "transport"


class Point2D(ContractModel):
    x: float
    y: float


class Polygon2D(ContractModel):
    vertices: list[Point2D] = Field(min_length=3)

    @model_validator(mode="after")
    def check_distinct_vertices(self) -> Polygon2D:
        if len({(point.x, point.y) for point in self.vertices}) < 3:
            raise ValueError("polygon requires at least three distinct vertices")
        return self


class CoordinateSystem(ContractModel):
    unit: Literal["meter"] = "meter"
    axis_convention: Literal["x_east_y_north"] = "x_east_y_north"
    origin_label: str = Field(default="home_local_origin", min_length=1)


class HomeRegion(ContractModel):
    region_id: str = Field(min_length=1)
    kind: RegionKind
    boundary: Polygon2D
    traversable: bool = True


class HomeConnection(ContractModel):
    connection_id: str = Field(min_length=1)
    kind: ConnectionKind
    region_a_id: str = Field(min_length=1)
    region_b_id: str = Field(min_length=1)
    portal_a: Point2D
    portal_b: Point2D
    width_meters: float = Field(gt=0)
    traversal_mode: TraversalMode = TraversalMode.walking
    distance_meters: float | None = Field(default=None, gt=0)
    bidirectional: bool = True
    allowed_mobility_profiles: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_connection_policy(self) -> HomeConnection:
        if self.region_a_id == self.region_b_id:
            raise ValueError("a connection must join two different regions")
        if self.traversal_mode is TraversalMode.transport and self.distance_meters is None:
            raise ValueError("transport connections require distanceMeters")
        if self.traversal_mode is TraversalMode.walking and self.distance_meters is not None:
            raise ValueError("walking connections derive distance from their portals")
        if (
            self.kind in {ConnectionKind.doorway, ConnectionKind.passage}
            and self.traversal_mode is not TraversalMode.walking
        ):
            raise ValueError("doorways and passages use walking traversal")
        if (
            self.kind is ConnectionKind.transit
            and self.traversal_mode is not TraversalMode.transport
        ):
            raise ValueError("transit connections use transport traversal")
        if len(self.allowed_mobility_profiles) != len(set(self.allowed_mobility_profiles)):
            raise ValueError("allowedMobilityProfiles must not contain duplicates")
        return self


class HomeObstacle(ContractModel):
    obstacle_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    boundary: Polygon2D


class InteractionPoint(ContractModel):
    interaction_point_id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    position: Point2D
    approach_radius_meters: float = Field(default=0.35, gt=0)


class EntityCapability(ContractModel):
    capability: str = Field(min_length=1)
    roles: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    supported_operations: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_values(self) -> EntityCapability:
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("capability roles must not contain duplicates")
        if len(self.supported_operations) != len(set(self.supported_operations)):
            raise ValueError("supportedOperations must not contain duplicates")
        return self


class AccessConstraint(ContractModel):
    allowed_resident_ids: list[str] = Field(default_factory=list)
    allowed_mobility_profiles: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_unique_values(self) -> AccessConstraint:
        if len(self.allowed_resident_ids) != len(set(self.allowed_resident_ids)):
            raise ValueError("allowedResidentIds must not contain duplicates")
        if len(self.allowed_mobility_profiles) != len(set(self.allowed_mobility_profiles)):
            raise ValueError("allowedMobilityProfiles must not contain duplicates")
        return self


# What a piece of furniture is actually for. Every entity used to receive the same list — the union
# of everything the scenario needed — so a sofa declared `food_preparation`, a radio declared
# `personal_care_support` and a storage cabinet declared `work_support`.
#
# `RESOURCE_ROLE_ALIASES` already steers the bindings whose process model names a role, which is why
# `consume` on `prepared_meal` finds the fridge. But `perform_work` and `leisure` name no role, so
# every entity matched and the binder fell back to `candidates[0]`, alphabetical by entity id. In
# the twelve-month home that made `cabinet_living` the winner for both: the resident worked nine
# hours a day at the storage cabinet, and read there too, while the scenario's own world declared a
# "Grande tavolo-scrivania ibrido" and a "Poltrona senape" standing unused beside her. Both landed
# under one detector, which is a large part of why three sensors carry 57% of the log.
#
# A type absent from this table keeps every capability. Scenarios name their own resource types and
# an unrecognised one must not become unsimulable — better a permissive sofa than a run that cannot
# bind. The per-region service point keeps the full set for the same reason, and
# `_entity_candidates` now prefers real furniture over it.
# Anything that holds things can be opened, looked into, taken from, put back into and organised.
_CONTAINER = frozenset(
    {"openable", "inspectable", "storage_support", "storable", "graspable", "cleanable"}
)
ENTITY_TYPE_CAPABILITIES: dict[str, frozenset[str]] = {
    "bathtub": frozenset({"personal_care_support", "cleanable", "openable"}),
    "bed": frozenset({"leisure_support", "cleanable"}),
    "chair": frozenset({"leisure_support", "consumable", "cleanable"}),
    "coffee_machine": frozenset(
        {"food_preparation", "consumable", "switchable", "inspectable", "cleanable"}
    ),
    "desk": frozenset({"work_support", "storable", "graspable", "cleanable"}),
    "drying_rack": frozenset({"laundry_support", "cleanable"}),
    "kettle": frozenset({"food_preparation", "switchable", "inspectable", "cleanable"}),
    "lamp": frozenset({"switchable"}),
    # `RESOURCE_ROLE_ALIASES` routes every medication role to a cabinet, so a cabinet must be able
    # to hold medicine even when the scenario never names a dedicated one.
    "medicine_cabinet": _CONTAINER | frozenset({"medication_support"}),
    "microwave": frozenset(
        {"food_preparation", "openable", "switchable", "inspectable", "cleanable"}
    ),
    "moka_coffee_maker": frozenset(
        {"food_preparation", "consumable", "switchable", "graspable", "inspectable", "cleanable"}
    ),
    "oven": frozenset({"food_preparation", "openable", "switchable", "inspectable", "cleanable"}),
    "radio": frozenset({"switchable", "communication", "leisure_support"}),
    "refrigerator": _CONTAINER | frozenset({"consumable"}),
    "shower": frozenset({"personal_care_support", "switchable", "cleanable"}),
    # A tap is where drinking water comes from, which is why it pours; it is not a hob.
    "sink": frozenset({"consumable", "switchable", "cleanable"}),
    "sofa": frozenset({"leisure_support", "consumable", "communication", "cleanable"}),
    "storage_cabinet": _CONTAINER | frozenset({"medication_support"}),
    "stove": frozenset({"food_preparation", "switchable", "inspectable", "cleanable"}),
    # You eat and work at a table; you cook on a hob. Leaving `food_preparation` here made the table
    # a candidate for every meal, and since `prepare_food` names no role the tie fell to the
    # alphabet rather than to the appliance the process had just switched on.
    "table": frozenset({"work_support", "consumable", "storable", "graspable", "cleanable"}),
    "television": frozenset({"switchable", "leisure_support", "communication"}),
    "toilet": frozenset({"personal_care_support", "cleanable"}),
    # The wardrobe is also where worn clothes wait for the wash: `laundry_collection` is its role.
    "wardrobe": _CONTAINER | frozenset({"wearable", "laundry_support"}),
    "washbasin": frozenset({"personal_care_support", "switchable", "cleanable"}),
    "washing_machine": frozenset(
        {"laundry_support", "openable", "switchable", "inspectable", "cleanable"}
    ),
}
# Every entity is somewhere a body can stand, whatever else it is or is not for.
UNIVERSAL_ENTITY_CAPABILITIES = frozenset({"interaction_point", "reachable", "transport_reachable"})


def capabilities_for_entity_type(entity_type: str) -> frozenset[str] | None:
    """What this kind of furniture is for, according to the active vocabulary pack.

    `None` keeps its old meaning and is not the same as an empty set: a type nothing declares keeps
    every capability, because a scenario naming an unrecognised resource must stay simulable. An
    author who adds furniture states its capabilities in the pack, which is how a new object stops
    being permissive and starts being a specific thing.

    The table above stays as the built-in values the default pack is derived from.
    """
    from smart_home_sim.vocabulary import views
    from smart_home_sim.vocabulary.active import active_pack

    return views.entity_type_capabilities(active_pack()).get(entity_type)


class HomeEntity(ContractModel):
    entity_id: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    interaction_point_id: str = Field(min_length=1)
    capabilities: list[EntityCapability] = Field(min_length=1)
    initial_state: dict[str, JsonValue] = Field(default_factory=dict)
    access: AccessConstraint = Field(default_factory=AccessConstraint)

    @model_validator(mode="after")
    def check_capability_state(self) -> HomeEntity:
        capabilities = {item.capability for item in self.capabilities}
        if "openable" in capabilities and not isinstance(self.initial_state.get("open"), bool):
            raise ValueError("openable entities require boolean initialState.open")
        if "switchable" in capabilities and not isinstance(self.initial_state.get("active"), bool):
            raise ValueError("switchable entities require boolean initialState.active")
        return self


class LocationBinding(ContractModel):
    scenario_location_id: str = Field(min_length=1)
    region_ids: list[str] = Field(min_length=1)
    anchor_interaction_point_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_regions(self) -> LocationBinding:
        if len(self.region_ids) != len(set(self.region_ids)):
            raise ValueError("location binding regionIds must not contain duplicates")
        return self


class ResourceBinding(ContractModel):
    scenario_resource_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)


class KinematicDefaults(ContractModel):
    body_radius_meters: float = Field(default=0.25, gt=0)
    minimum_walking_speed_meters_per_second: float = Field(default=0.2, gt=0)
    default_walking_speed_meters_per_second: float = Field(default=1.2, gt=0)
    posture_transition_seconds: dict[Literal["standing", "walking", "sitting", "lying"], float] = (
        Field(
            default_factory=lambda: {
                "standing": 1.5,
                "walking": 0.5,
                "sitting": 2.0,
                "lying": 3.0,
            }
        )
    )

    @model_validator(mode="after")
    def check_posture_transitions(self) -> KinematicDefaults:
        required = {"standing", "walking", "sitting", "lying"}
        if set(self.posture_transition_seconds) != required or any(
            value <= 0 for value in self.posture_transition_seconds.values()
        ):
            raise ValueError("postureTransitionSeconds requires four positive posture durations")
        return self


class HomeModel(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:home-model:1.0.0",
            "title": "Smart Home Executable Home Model 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["home_model"] = "home_model"
    home_id: str = Field(min_length=1)
    home_version: str = Field(min_length=1)
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    regions: list[HomeRegion] = Field(min_length=1)
    connections: list[HomeConnection] = Field(default_factory=list)
    obstacles: list[HomeObstacle] = Field(default_factory=list)
    interaction_points: list[InteractionPoint] = Field(min_length=1)
    entities: list[HomeEntity] = Field(min_length=1)
    location_bindings: list[LocationBinding] = Field(min_length=1)
    resource_bindings: list[ResourceBinding] = Field(default_factory=list)
    kinematic_defaults: KinematicDefaults = Field(default_factory=KinematicDefaults)


class ArtifactDigest(ContractModel):
    artifact_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResolvedKinematics(ContractModel):
    resident_id: str = Field(min_length=1)
    mobility_profile: str = Field(min_length=1)
    walking_speed_meters_per_second: float = Field(gt=0)
    body_radius_meters: float = Field(gt=0)
    posture_transition_seconds: dict[str, float]


class ResolvedCapabilityBinding(ContractModel):
    role: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    provider_type: Literal["entity", "location", "resident"]
    provider_id: str = Field(min_length=1)
    interaction_point_id: str | None = None


class ResolvedActionBinding(ContractModel):
    source_activity_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    process_model_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    resolved_arguments: dict[str, JsonValue] = Field(default_factory=dict)
    capability_bindings: list[ResolvedCapabilityBinding] = Field(default_factory=list)
    destination_region_ids: list[str] = Field(default_factory=list)
    destination_interaction_point_id: str | None = None


class SimulationBundle(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:simulation-bundle:1.0.0",
            "title": "Smart Home Fully Resolved Simulation Bundle 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["simulation_bundle"] = "simulation_bundle"
    bundle_id: str = Field(min_length=1)
    seed: int
    scenario: Scenario
    canonical_plan: CanonicalPlan
    behavior_package: PersonalProcessPackage
    home_model: HomeModel
    digests: list[ArtifactDigest] = Field(min_length=4, max_length=4)
    resident_kinematics: list[ResolvedKinematics] = Field(min_length=1)
    action_bindings: list[ResolvedActionBinding] = Field(min_length=1)

    @model_validator(mode="after")
    def check_embedded_artifacts(self) -> SimulationBundle:
        if self.canonical_plan.source_scenario_id != self.scenario.scenario_id:
            raise ValueError("canonical plan and scenario identifiers do not match")
        if self.behavior_package.source_scenario_id != self.scenario.scenario_id:
            raise ValueError("behavior package and scenario identifiers do not match")
        home_reference = self.scenario.model_references.home_model
        if (
            home_reference.reference_id != self.home_model.home_id
            or home_reference.version != self.home_model.home_version
        ):
            raise ValueError("home model does not match the scenario reference")
        expected = {
            self.scenario.scenario_id: _canonical_sha256(self.scenario),
            f"plan:{self.scenario.scenario_id}": _canonical_sha256(self.canonical_plan),
            self.behavior_package.package_id: _canonical_sha256(self.behavior_package),
            self.home_model.home_id: _canonical_sha256(self.home_model),
        }
        actual = {item.artifact_id: item.sha256 for item in self.digests}
        if actual != expected:
            raise ValueError("embedded artifact digests are missing, duplicated, or inconsistent")
        return self

    @classmethod
    def model_json_schema(cls, *args: object, **kwargs: object) -> dict[str, object]:
        schema = super().model_json_schema(*args, **kwargs)  # type: ignore[arg-type]
        for definition in schema.get("$defs", {}).values():
            if isinstance(definition, dict):
                # Nested public contracts retain their fields, but their standalone base URI
                # would incorrectly re-scope local $refs inside this aggregate schema.
                definition.pop("$id", None)
                definition.pop("$schema", None)
        return schema


ENVIRONMENT_ISSUE_CODES = frozenset(
    {
        "ACTION_BINDING_UNRESOLVED",
        "ARTIFACT_DIGEST_MISMATCH",
        "BEHAVIOR_INVALID",
        "CONNECTION_INVALID",
        "DUPLICATE_IDENTIFIER",
        "ENTITY_INVALID",
        "FILE_ENCODING_ERROR",
        "FILE_NOT_FOUND",
        "FILE_READ_ERROR",
        "FILE_TOO_LARGE",
        "GEOMETRY_INVALID",
        "HOME_REFERENCE_MISMATCH",
        "INPUT_PLAN_INVALID",
        "INPUT_SCENARIO_INVALID",
        "INTERACTION_POINT_INVALID",
        "JSON_NESTING_TOO_DEEP",
        "JSON_SYNTAX",
        "LOCATION_BINDING_INVALID",
        "OBSTACLE_INVALID",
        "PATH_UNREACHABLE",
        "PLAN_SCENARIO_MISMATCH",
        "RESOURCE_BINDING_INVALID",
        "STRUCTURE_INVALID",
        "TOPOLOGY_DISCONNECTED",
        "UNSUPPORTED_SCHEMA_VERSION",
    }
)


class EnvironmentValidationIssue(ContractModel):
    code: str = Field(json_schema_extra={"enum": sorted(ENVIRONMENT_ISSUE_CODES)})
    severity: Literal["error", "warning"] = "error"
    stage: Literal["structure", "geometry", "topology", "compatibility", "binding"]
    path: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class EnvironmentValidationSummary(ContractModel):
    region_count: int = Field(ge=0)
    connection_count: int = Field(ge=0)
    entity_count: int = Field(ge=0)
    interaction_point_count: int = Field(ge=0)
    action_binding_count: int = Field(ge=0)
    route_check_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class EnvironmentValidationReport(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:environment-validation-report:1.0.0",
            "title": "Smart Home Environment Validation Report 1.0.0",
        },
    )

    validator_version: Literal["1.0.0"] = "1.0.0"
    valid: bool
    home_id: str | None = None
    home_version: str | None = None
    home_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issues: list[EnvironmentValidationIssue] = Field(default_factory=list)
    summary: EnvironmentValidationSummary

    @classmethod
    def from_issues(
        cls,
        issues: list[EnvironmentValidationIssue],
        *,
        home: HomeModel | None = None,
        home_sha256: str | None = None,
        bundle_sha256: str | None = None,
        action_binding_count: int = 0,
        route_check_count: int = 0,
    ) -> EnvironmentValidationReport:
        return cls(
            valid=not any(issue.severity == "error" for issue in issues),
            home_id=home.home_id if home else None,
            home_version=home.home_version if home else None,
            home_sha256=home_sha256,
            bundle_sha256=bundle_sha256,
            issues=issues,
            summary=EnvironmentValidationSummary(
                region_count=len(home.regions) if home else 0,
                connection_count=len(home.connections) if home else 0,
                entity_count=len(home.entities) if home else 0,
                interaction_point_count=len(home.interaction_points) if home else 0,
                action_binding_count=action_binding_count,
                route_check_count=route_check_count,
                error_count=sum(issue.severity == "error" for issue in issues),
                warning_count=sum(issue.severity == "warning" for issue in issues),
            ),
        )


class BundleBuildResult(ContractModel):
    report: EnvironmentValidationReport
    bundle: SimulationBundle | None = None


def _canonical_sha256(value: ContractModel) -> str:
    encoded = json.dumps(
        value.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
