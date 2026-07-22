from __future__ import annotations

import json
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from math import ceil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.behavior.service import default_action_catalog_path
from smart_home_sim.compiler import compile_scenario
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    PersonalProcessPackage,
    ProcessNodeKind,
    ValueSource,
)
from smart_home_sim.domain.environment import (
    ConnectionKind,
    EntityCapability,
    HomeConnection,
    HomeEntity,
    HomeModel,
    HomeRegion,
    InteractionPoint,
    LocationBinding,
    Point2D,
    Polygon2D,
    RegionKind,
    ResourceBinding,
    SimulationBundle,
    TraversalMode,
)
from smart_home_sim.domain.materialization import (
    HomeGenerationPolicy,
    HomeGenerationReport,
    HomeGenerationResult,
    HomeGenerationSummary,
    MaterializationIssue,
    SensorDeploymentPolicy,
    SensorDeploymentReport,
    SensorDeploymentResult,
    SensorDeploymentSummary,
    SyntheticWorkspaceManifest,
    WorkspaceArtifact,
)
from smart_home_sim.domain.models import LocationKind, Scenario
from smart_home_sim.domain.sensors import (
    ContactSensor,
    PirSensor,
    SensorErrorModel,
    SensorModel,
    SensorTiming,
    TemperatureSensor,
    TemperatureSource,
)
from smart_home_sim.environment import build_bundle_files, validate_home_model
from smart_home_sim.sensors import project_sensors
from smart_home_sim.simulation import simulate_bundle


class MaterializationFailure(RuntimeError):
    def __init__(self, phase: str, message: str, issues: list[Any] | None = None) -> None:
        normalized = [
            issue.model_dump(mode="json", by_alias=True)
            if hasattr(issue, "model_dump")
            else dict(issue)
            for issue in (issues or [])
        ]
        if not normalized:
            normalized = [
                {
                    "code": f"{phase.upper()}_FAILED",
                    "severity": "error",
                    "stage": phase,
                    "path": "$",
                    "message": message,
                    "details": {},
                }
            ]
        first = normalized[0]
        super().__init__(message)
        self.phase = phase
        self.code = str(first.get("code") or f"{phase.upper()}_FAILED")
        self.message = str(first.get("message") or message)
        self.issues = normalized


def _rectangle(x: float, y: float, width: float, height: float) -> Polygon2D:
    return Polygon2D(
        vertices=[
            Point2D(x=x, y=y),
            Point2D(x=x + width, y=y),
            Point2D(x=x + width, y=y + height),
            Point2D(x=x, y=y + height),
        ]
    )


def _center(boundary: Polygon2D) -> Point2D:
    xs = [point.x for point in boundary.vertices]
    ys = [point.y for point in boundary.vertices]
    return Point2D(x=(min(xs) + max(xs)) / 2, y=(min(ys) + max(ys)) / 2)


def _distributed_position(boundary: Polygon2D, index: int, count: int) -> Point2D:
    """Place generated objects at stable, distinct in-room interaction points."""
    xs = [point.x for point in boundary.vertices]
    ys = [point.y for point in boundary.vertices]
    minimum_x, maximum_x = min(xs), max(xs)
    minimum_y, maximum_y = min(ys), max(ys)
    columns = min(3, count)
    rows = ceil(count / columns)
    column = index % columns
    row = index // columns
    return Point2D(
        x=minimum_x + (maximum_x - minimum_x) * (column + 1) / (columns + 1),
        y=minimum_y + (maximum_y - minimum_y) * (row + 1) / (rows + 1),
    )


RESOURCE_ROLE_ALIASES: dict[str, frozenset[str]] = {
    "refrigerator": frozenset(
        {
            "food_storage",
            "coffee_and_breakfast_storage",
            "ingredients",
            "prepared_meal",
            "prepared_food_portions",
        }
    ),
    "storage_cabinet": frozenset(
        {
            "medication_cabinet",
            "household_storage",
            "household_supplies",
            "cleaning_products",
            "medication",
        }
    ),
    "wardrobe": frozenset({"clothing_storage", "clothes", "used_clothing", "laundry_collection"}),
    "washing_machine": frozenset({"laundry_equipment", "laundry"}),
    "stove": frozenset({"cooking_appliance", "food_preparation_area"}),
    "moka_coffee_maker": frozenset({"moka_coffee_maker", "coffee_equipment"}),
    "sink": frozenset({"washing_area", "food_preparation_area"}),
    "washbasin": frozenset({"washing_area", "personal_care_fixture"}),
    "shower": frozenset({"shower", "personal_care_fixture"}),
    "toilet": frozenset({"toilet", "personal_care_fixture"}),
    "bed": frozenset({"bed", "sleeping_area"}),
    "chair": frozenset({"chair", "dining_seat"}),
    "table": frozenset({"table", "dining_area"}),
    "sofa": frozenset({"sofa", "seating", "rest_area"}),
    "television": frozenset({"television", "media"}),
    "radio": frozenset({"radio", "media"}),
}
ENTRANCE_CAPABILITIES = frozenset({"home_egress", "home_ingress"})


def _resource_roles(resource: Any) -> set[str]:
    return {
        resource.resource_id,
        resource.resource_type,
        *RESOURCE_ROLE_ALIASES.get(resource.resource_type, ()),
    }


def _json(path: Path, model: Any) -> None:
    path.write_text(model.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8")


def _load_model[ModelT](path: Path, model: type[ModelT]) -> ModelT:
    return model.model_validate_json(path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]


def _expanded_regions(scenario: Scenario, location_id: str) -> list[str]:
    locations = {item.location_id: item for item in scenario.locations}
    location = locations[location_id]
    if location.kind is not LocationKind.composite:
        return [location.location_id]
    result: list[str] = []
    for member in location.member_location_ids:
        for region_id in _expanded_regions(scenario, member):
            if region_id not in result:
                result.append(region_id)
    return result


def _required_capabilities(
    scenario: Scenario, package: PersonalProcessPackage
) -> list[EntityCapability]:
    catalog = ActionCatalog.model_validate_json(
        default_action_catalog_path(package.catalogs.action_catalog.version).read_text(
            encoding="utf-8"
        )
    )
    used_actions = {
        node.action_type
        for model in package.process_models
        for node in model.nodes
        if node.kind is ProcessNodeKind.action and node.action_type is not None
    }
    definitions = {item.action_type: item for item in catalog.actions}
    operations: dict[str, set[str]] = defaultdict(set)
    role_values = (
        {item.resource_id for item in scenario.resources}
        | {item.resource_type for item in scenario.resources}
        | {activity.intent for day in scenario.days for activity in day.activities}
    )
    for model in package.process_models:
        for node in model.nodes:
            if node.kind is not ProcessNodeKind.action or node.action_type is None:
                continue
            for expression in node.arguments.values():
                if expression.source is ValueSource.literal and expression.value is not None:
                    role_values.add(str(expression.value))
    for action_type in used_actions:
        definition = definitions[action_type]
        for parameter in definition.parameters:
            role_values.update(str(value) for value in parameter.allowed_values)
        for requirement in definition.required_capabilities:
            if requirement.capability not in {
                "reachable",
                "transport_reachable",
                "posture_control",
            }:
                operations[requirement.capability].add(action_type)
    operations.setdefault("interaction_point", set()).add("move_to_capability")
    roles = sorted(role_values)
    return [
        EntityCapability(
            capability=capability,
            roles=roles,
            supported_operations=sorted(action_types),
        )
        for capability, action_types in sorted(operations.items())
    ]


def _home_failure(
    scenario: Scenario,
    package: PersonalProcessPackage,
    policy: HomeGenerationPolicy,
    issue: MaterializationIssue,
) -> HomeGenerationResult:
    return HomeGenerationResult(
        report=HomeGenerationReport(
            success=False,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_sha256=canonical_sha256(policy),
            source_scenario_id=scenario.scenario_id,
            source_scenario_sha256=canonical_sha256(scenario),
            source_behavior_package_id=package.package_id,
            source_behavior_package_sha256=canonical_sha256(package),
            issues=[issue],
            summary=HomeGenerationSummary(
                region_count=0,
                connection_count=0,
                entity_count=0,
                location_binding_count=0,
                resource_binding_count=0,
                error_count=1,
            ),
        )
    )


def generate_home(
    scenario: Scenario,
    package: PersonalProcessPackage,
    policy: HomeGenerationPolicy | None = None,
) -> HomeGenerationResult:
    policy = policy or HomeGenerationPolicy()
    if package.source_scenario_id != scenario.scenario_id:
        return _home_failure(
            scenario,
            package,
            policy,
            MaterializationIssue(
                code="BEHAVIOR_SCENARIO_MISMATCH",
                stage="input",
                path="$.sourceScenarioId",
                message="Behavior package does not reference the supplied scenario.",
            ),
        )
    primitive = [item for item in scenario.locations if item.kind is not LocationKind.composite]
    if not primitive:
        return _home_failure(
            scenario,
            package,
            policy,
            MaterializationIssue(
                code="NO_PRIMITIVE_LOCATION",
                stage="home",
                path="$.locations",
                message="At least one non-composite scenario location is required.",
            ),
        )

    local = [item for item in primitive if item.kind is LocationKind.room]
    remote = [item for item in primitive if item.kind is not LocationKind.room]
    regions: list[HomeRegion] = []
    for index, location in enumerate(local):
        regions.append(
            HomeRegion(
                region_id=location.location_id,
                kind=RegionKind.room,
                boundary=_rectangle(
                    index * policy.room_width_meters,
                    0,
                    policy.room_width_meters,
                    policy.room_height_meters,
                ),
            )
        )
    remote_y = policy.room_height_meters + policy.external_spacing_meters
    for index, location in enumerate(remote):
        kind = RegionKind.external if location.kind is LocationKind.external else RegionKind.transit
        regions.append(
            HomeRegion(
                region_id=location.location_id,
                kind=kind,
                boundary=_rectangle(
                    index * policy.room_width_meters,
                    remote_y,
                    policy.room_width_meters,
                    policy.room_height_meters,
                ),
            )
        )
    regions_by_id = {item.region_id: item for item in regions}
    connections: list[HomeConnection] = []
    for index, (left, right) in enumerate(zip(local, local[1:], strict=False), start=1):
        boundary_x = index * policy.room_width_meters
        portal_offset = min(0.4, policy.doorway_width_meters / 2)
        connections.append(
            HomeConnection(
                connection_id=f"door_{left.location_id}_{right.location_id}",
                kind=ConnectionKind.doorway,
                region_a_id=left.location_id,
                region_b_id=right.location_id,
                portal_a=Point2D(
                    x=boundary_x - portal_offset,
                    y=policy.room_height_meters / 2,
                ),
                portal_b=Point2D(
                    x=boundary_x + portal_offset,
                    y=policy.room_height_meters / 2,
                ),
                width_meters=policy.doorway_width_meters,
            )
        )
    anchor_id = local[0].location_id if local else remote[0].location_id
    for location in remote:
        if location.location_id == anchor_id:
            continue
        connections.append(
            HomeConnection(
                connection_id=f"transit_{anchor_id}_{location.location_id}",
                kind=ConnectionKind.transit,
                region_a_id=anchor_id,
                region_b_id=location.location_id,
                portal_a=_center(regions_by_id[anchor_id].boundary),
                portal_b=_center(regions_by_id[location.location_id].boundary),
                width_meters=policy.doorway_width_meters,
                traversal_mode=TraversalMode.transport,
                distance_meters=policy.transport_distance_meters,
            )
        )

    interaction_points = [
        InteractionPoint(
            interaction_point_id=f"anchor_{region.region_id}",
            region_id=region.region_id,
            position=_center(region.boundary),
        )
        for region in regions
    ]
    location_bindings: list[LocationBinding] = []
    for location in scenario.locations:
        region_ids = _expanded_regions(scenario, location.location_id)
        location_bindings.append(
            LocationBinding(
                scenario_location_id=location.location_id,
                region_ids=region_ids,
                anchor_interaction_point_id=f"anchor_{region_ids[0]}",
            )
        )

    capabilities = _required_capabilities(scenario, package)
    assigned_semantic_roles = {
        role
        for resource in scenario.resources
        for role in _resource_roles(resource)
        if role not in {resource.resource_id, resource.resource_type}
    }
    entities: list[HomeEntity] = []
    resource_bindings: list[ResourceBinding] = []
    resources_by_region: dict[str, list[Any]] = defaultdict(list)
    for resource in scenario.resources:
        region_id = _expanded_regions(scenario, resource.location_id)[0]
        resources_by_region[region_id].append(resource)
    for region_resources in resources_by_region.values():
        region_resources.sort(key=lambda item: item.resource_id)
    for resource in scenario.resources:
        region_id = _expanded_regions(scenario, resource.location_id)[0]
        region_resources = resources_by_region[region_id]
        position = _distributed_position(
            regions_by_id[region_id].boundary,
            region_resources.index(resource),
            len(region_resources),
        )
        interaction_id = f"point_{resource.resource_id}"
        interaction_points.append(
            InteractionPoint(
                interaction_point_id=interaction_id,
                region_id=region_id,
                position=position,
            )
        )
        state = dict(scenario.initial_state.resource_facts.get(resource.resource_id, {}))
        state.setdefault("open", False)
        state.setdefault("active", False)
        entities.append(
            HomeEntity(
                entity_id=resource.resource_id,
                entity_type=resource.resource_type,
                region_id=region_id,
                interaction_point_id=interaction_id,
                capabilities=[
                    item.model_copy(update={"roles": sorted(_resource_roles(resource))})
                    for item in capabilities
                    if item.capability not in ENTRANCE_CAPABILITIES
                ],
                initial_state=state,
            )
        )
        resource_bindings.append(
            ResourceBinding(
                scenario_resource_id=resource.resource_id,
                entity_id=resource.resource_id,
            )
        )
    entrance_region = local[0].location_id if local else regions[0].region_id
    entrance_boundary = regions_by_id[entrance_region].boundary
    entrance_center = _center(entrance_boundary)
    entrance_x = min(point.x for point in entrance_boundary.vertices) + 0.75
    entrance_point = InteractionPoint(
        interaction_point_id="point_entrance_door",
        region_id=entrance_region,
        position=Point2D(x=entrance_x, y=entrance_center.y),
    )
    interaction_points.append(entrance_point)
    entrance_capabilities = [
        item.model_copy(update={"roles": ["entrance", "home_entrance", "home_exit"]})
        for item in capabilities
        if item.capability in ENTRANCE_CAPABILITIES
    ]
    entrance_capabilities.append(
        EntityCapability(
            capability="openable",
            roles=["entrance", "home_entrance", "home_exit"],
            supported_operations=["enter_home", "leave_home"],
        )
    )
    entities.append(
        HomeEntity(
            entity_id="entrance_door",
            entity_type="entrance_door",
            region_id=entrance_region,
            interaction_point_id=entrance_point.interaction_point_id,
            capabilities=entrance_capabilities,
            initial_state={"open": False},
        )
    )

    for region in regions:
        entity_id = f"service_{region.region_id}"
        interaction_id = f"point_{entity_id}"
        interaction_points.append(
            InteractionPoint(
                interaction_point_id=interaction_id,
                region_id=region.region_id,
                position=_center(region.boundary),
            )
        )
        entities.append(
            HomeEntity(
                entity_id=entity_id,
                entity_type="generated_environment_service",
                region_id=region.region_id,
                interaction_point_id=interaction_id,
                capabilities=[
                    item.model_copy(
                        update={"roles": sorted(set(item.roles) - assigned_semantic_roles)}
                    )
                    for item in capabilities
                    if item.capability not in ENTRANCE_CAPABILITIES
                ],
                initial_state={"open": False, "active": False},
            )
        )

    home = HomeModel(
        home_id=scenario.model_references.home_model.reference_id,
        home_version=scenario.model_references.home_model.version,
        regions=regions,
        connections=connections,
        interaction_points=interaction_points,
        entities=entities,
        location_bindings=location_bindings,
        resource_bindings=resource_bindings,
    )
    validation = validate_home_model(home)
    if not validation.valid:
        first = validation.issues[0]
        return _home_failure(
            scenario,
            package,
            policy,
            MaterializationIssue(
                code=first.code,
                stage="home",
                path=first.path,
                message=first.message,
                details=first.details,
            ),
        )
    report = HomeGenerationReport(
        success=True,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_sha256=canonical_sha256(policy),
        source_scenario_id=scenario.scenario_id,
        source_scenario_sha256=canonical_sha256(scenario),
        source_behavior_package_id=package.package_id,
        source_behavior_package_sha256=canonical_sha256(package),
        home_id=home.home_id,
        home_version=home.home_version,
        home_sha256=canonical_sha256(home),
        summary=HomeGenerationSummary(
            region_count=len(home.regions),
            connection_count=len(home.connections),
            entity_count=len(home.entities),
            location_binding_count=len(home.location_bindings),
            resource_binding_count=len(home.resource_bindings),
            error_count=0,
        ),
    )
    return HomeGenerationResult(report=report, home=home)


def deploy_sensors(
    bundle: SimulationBundle,
    policy: SensorDeploymentPolicy | None = None,
) -> SensorDeploymentResult:
    policy = policy or SensorDeploymentPolicy()
    home = bundle.home_model
    local_regions = [item for item in home.regions if item.kind is RegionKind.room]
    if not local_regions:
        local_regions = home.regions[:1]
    selected = local_regions[:1] if policy.preset == "minimal" else local_regions
    sensors: list[PirSensor | ContactSensor | TemperatureSensor] = []
    pir_error = SensorErrorModel(
        dropout_probability=policy.dropout_probability,
        false_negative_probability=policy.false_negative_probability,
        false_positive_probability_per_day=policy.false_positive_probability_per_day,
    )
    for region in selected:
        positions = [_center(region.boundary)]
        if policy.preset == "dense":
            vertices = region.boundary.vertices
            minimum_x = min(item.x for item in vertices)
            maximum_x = max(item.x for item in vertices)
            center = _center(region.boundary)
            positions = [
                Point2D(x=minimum_x + (maximum_x - minimum_x) / 3, y=center.y),
                Point2D(x=minimum_x + 2 * (maximum_x - minimum_x) / 3, y=center.y),
            ]
        for number, position in enumerate(positions, start=1):
            suffix = f"_{number}" if len(positions) > 1 else ""
            sensors.append(
                PirSensor(
                    sensor_id=f"pir_{region.region_id}{suffix}",
                    position=position,
                    region_ids=[region.region_id],
                    coverage=region.boundary,
                    hold_milliseconds=policy.pir_hold_milliseconds,
                    timing=SensorTiming(cooldown_milliseconds=policy.pir_cooldown_milliseconds),
                    error_model=pir_error,
                )
            )
    entities = {item.entity_id: item for item in home.entities}
    state_contact_entity_ids = {
        capability.provider_id
        for binding in bundle.action_bindings
        if binding.action_type in {"open", "close"}
        for capability in binding.capability_bindings
        if capability.provider_type == "entity"
        and not capability.provider_id.startswith("service_")
        and capability.provider_id != "entrance_door"
    }
    contact_entities = [entities[entity_id] for entity_id in sorted(state_contact_entity_ids)]
    if policy.preset == "minimal":
        contact_entities = []
    points = {item.interaction_point_id: item.position for item in home.interaction_points}
    entrance = entities.get("entrance_door")
    if entrance is not None:
        sensors.append(
            ContactSensor(
                sensor_id="contact_entrance_door",
                position=points[entrance.interaction_point_id],
                entity_id=entrance.entity_id,
                fact=None,
                action_types=["enter_home", "leave_home"],
                pulse_milliseconds=policy.contact_pulse_milliseconds,
                error_model=pir_error,
            )
        )
    for entity in contact_entities:
        sensors.append(
            ContactSensor(
                sensor_id=f"contact_{entity.entity_id}",
                position=points[entity.interaction_point_id],
                entity_id=entity.entity_id,
                pulse_milliseconds=policy.contact_pulse_milliseconds,
                error_model=pir_error,
            )
        )
    entities_by_region: dict[str, list[HomeEntity]] = defaultdict(list)
    for entity in home.entities:
        entities_by_region[entity.region_id].append(entity)
    active_entity_ids = {
        capability.provider_id
        for binding in bundle.action_bindings
        if binding.action_type in {"activate", "deactivate"}
        for capability in binding.capability_bindings
        if capability.provider_type == "entity"
    }
    temperature_regions = selected[:1] if policy.preset == "minimal" else selected
    for region in temperature_regions:
        region_entities = sorted(
            entities_by_region[region.region_id],
            key=lambda item: (item.entity_id.startswith("service_"), item.entity_id),
        )
        active_entities = [
            entity for entity in region_entities if entity.entity_id in active_entity_ids
        ]
        source_entities = active_entities or region_entities[:1]
        sensors.append(
            TemperatureSensor(
                sensor_id=f"temperature_{region.region_id}",
                position=_center(region.boundary),
                region_id=region.region_id,
                baseline_celsius=policy.temperature_baseline_celsius,
                sources=[
                    TemperatureSource(
                        entity_id=source.entity_id,
                        fact="active",
                        delta_celsius=policy.temperature_source_delta_celsius,
                        sample_interval_seconds=policy.temperature_sample_interval_seconds,
                    )
                    for source in source_entities
                ],
                error_model=SensorErrorModel(
                    dropout_probability=policy.dropout_probability,
                    false_negative_probability=policy.false_negative_probability,
                    false_positive_probability_per_day=(policy.false_positive_probability_per_day),
                    measurement_noise_standard_deviation=(
                        policy.temperature_noise_standard_deviation
                    ),
                ),
            )
        )
    model = SensorModel(
        sensor_model_id=f"{home.home_id}__{policy.preset}__sensors",
        sensor_model_version="1.1.0",
        source_bundle_id=bundle.bundle_id,
        source_bundle_sha256=canonical_sha256(bundle),
        seed=bundle.seed,
        region_ids=sorted(item.region_id for item in home.regions),
        entity_ids=sorted(item.entity_id for item in home.entities),
        sensors=sensors,
    )
    counts = defaultdict(int)
    for sensor in sensors:
        counts[sensor.sensor_type] += 1
    report = SensorDeploymentReport(
        success=True,
        preset=policy.preset,
        policy_version=policy.policy_version,
        policy_sha256=canonical_sha256(policy),
        source_bundle_id=bundle.bundle_id,
        source_bundle_sha256=canonical_sha256(bundle),
        source_home_sha256=canonical_sha256(home),
        sensor_model_id=model.sensor_model_id,
        sensor_model_version=model.sensor_model_version,
        sensor_model_sha256=canonical_sha256(model),
        summary=SensorDeploymentSummary(
            sensor_count=len(sensors),
            pir_count=counts["pir"],
            contact_count=counts["contact"],
            temperature_count=counts["temperature"],
            error_count=0,
        ),
    )
    return SensorDeploymentResult(report=report, sensor_model=model)


def _file_digest(path: Path) -> str:
    return canonical_sha256(json.loads(path.read_text(encoding="utf-8")))


def materialize_workspace(
    scenario_path: Path,
    package_path: Path,
    output_directory: Path,
    *,
    home_policy: HomeGenerationPolicy | None = None,
    sensor_policy: SensorDeploymentPolicy | None = None,
    progress: Callable[[str, float, str, dict[str, int]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> SyntheticWorkspaceManifest:
    if output_directory.exists():
        raise FileExistsError(f"output directory already exists: {output_directory}")
    home_policy = home_policy or HomeGenerationPolicy()
    sensor_policy = sensor_policy or SensorDeploymentPolicy()
    scenario = _load_model(scenario_path, Scenario)
    package = _load_model(package_path, PersonalProcessPackage)
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}.", dir=output_directory.parent)
    )

    def emit(
        phase: str, percent: float, message: str, counters: dict[str, int] | None = None
    ) -> None:
        if cancelled is not None and cancelled():
            raise InterruptedError("materialization cancelled")
        if progress is not None:
            progress(phase, percent, message, counters or {})

    try:
        emit("input", 2, "Accepted source artifacts")
        shutil.copyfile(scenario_path, staging / "scenario.json")
        shutil.copyfile(package_path, staging / "personal-process-package.json")
        _json(staging / "home-generation-policy.json", home_policy)
        _json(staging / "sensor-deployment-policy.json", sensor_policy)

        compilation = compile_scenario(scenario)
        _json(staging / "compilation-report.json", compilation.report)
        if compilation.plan is None:
            raise MaterializationFailure(
                "compilation", "Scenario compilation failed.", compilation.report.issues
            )
        _json(staging / "canonical-plan.json", compilation.plan)
        emit(
            "compilation",
            12,
            "Compiled the canonical plan",
            {"activities": compilation.report.summary.scheduled_activity_count},
        )

        home_result = generate_home(scenario, package, home_policy)
        _json(staging / "home-generation-report.json", home_result.report)
        if home_result.home is None:
            raise MaterializationFailure(
                "home", "home generation failed", home_result.report.issues
            )
        _json(staging / "home-model.json", home_result.home)
        emit(
            "home",
            26,
            "Generated and validated the executable home",
            {"regions": home_result.report.summary.region_count},
        )

        bundle_result = build_bundle_files(
            staging / "scenario.json",
            staging / "canonical-plan.json",
            staging / "personal-process-package.json",
            staging / "home-model.json",
        )
        _json(staging / "environment-report.json", bundle_result.report)
        if bundle_result.bundle is None:
            raise MaterializationFailure(
                "binding",
                "Environment bundle validation failed.",
                bundle_result.report.issues,
            )
        _json(staging / "simulation-bundle.json", bundle_result.bundle)
        emit(
            "binding",
            40,
            "Resolved action and route bindings",
            {"bindings": bundle_result.report.summary.action_binding_count},
        )

        sensor_result = deploy_sensors(bundle_result.bundle, sensor_policy)
        _json(staging / "sensor-deployment-report.json", sensor_result.report)
        if sensor_result.sensor_model is None:
            raise MaterializationFailure(
                "sensors", "Sensor deployment failed.", sensor_result.report.issues
            )
        _json(staging / "sensor-model.json", sensor_result.sensor_model)
        emit(
            "sensors",
            50,
            "Deployed and validated sensors",
            {"sensors": sensor_result.report.summary.sensor_count},
        )

        emit("simulation", 52, "Started deterministic execution")
        simulation = simulate_bundle(bundle_result.bundle)
        _json(staging / "simulation-report.json", simulation.report)
        if simulation.trace is None:
            raise MaterializationFailure(
                "simulation", "Simulation failed.", simulation.report.issues
            )
        _json(staging / "execution-trace.json", simulation.trace)
        emit(
            "simulation",
            82,
            "Completed deterministic execution",
            {
                "activities": simulation.report.summary.completed_activity_count,
                "actions": simulation.report.summary.action_execution_count,
                "movements": simulation.report.summary.movement_count,
            },
        )

        emit("projection", 84, "Started observable sensor projection")
        projection = project_sensors(
            simulation.trace, bundle_result.bundle, sensor_result.sensor_model
        )
        _json(staging / "sensor-projection-report.json", projection.report)
        if projection.observable_log is None or projection.oracle_mapping is None:
            raise MaterializationFailure(
                "projection", "Sensor projection failed.", projection.report.issues
            )
        _json(staging / "observable-sensor-log.json", projection.observable_log)
        _json(staging / "oracle-mapping.json", projection.oracle_mapping)
        emit(
            "projection",
            96,
            "Completed observable and oracle projections",
            {"observations": projection.report.summary.observation_count},
        )

        roles = {
            "scenario": "scenario.json",
            "behavior_package": "personal-process-package.json",
            "home_policy": "home-generation-policy.json",
            "home_report": "home-generation-report.json",
            "home": "home-model.json",
            "compilation_report": "compilation-report.json",
            "canonical_plan": "canonical-plan.json",
            "environment_report": "environment-report.json",
            "simulation_bundle": "simulation-bundle.json",
            "sensor_policy": "sensor-deployment-policy.json",
            "sensor_report": "sensor-deployment-report.json",
            "sensor_model": "sensor-model.json",
            "simulation_report": "simulation-report.json",
            "execution_trace": "execution-trace.json",
            "projection_report": "sensor-projection-report.json",
            "observable_sensor_log": "observable-sensor-log.json",
            "oracle_mapping": "oracle-mapping.json",
        }
        manifest = SyntheticWorkspaceManifest(
            scenario_id=scenario.scenario_id,
            bundle_id=bundle_result.bundle.bundle_id,
            trace_id=simulation.trace.trace_id,
            sensor_log_id=projection.observable_log.log_id,
            artifacts=[
                WorkspaceArtifact(
                    role=role,
                    relative_path=relative_path,
                    sha256=_file_digest(staging / relative_path),
                )
                for role, relative_path in roles.items()
            ],
        )
        _json(staging / "workspace-manifest.json", manifest)
        emit("publication", 99, "Verified artifact manifest")
        staging.replace(output_directory)
        if progress is not None:
            progress(
                "completed",
                100,
                "Published the complete synthetic workspace",
                {"artifacts": len(manifest.artifacts)},
            )
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_home_policy(path: Path | None) -> HomeGenerationPolicy:
    if path is None:
        return HomeGenerationPolicy()
    return _load_model(path, HomeGenerationPolicy)


def load_sensor_policy(path: Path | None) -> SensorDeploymentPolicy:
    if path is None:
        return SensorDeploymentPolicy()
    return _load_model(path, SensorDeploymentPolicy)


def load_source_models(
    scenario_path: Path, package_path: Path
) -> tuple[Scenario, PersonalProcessPackage]:
    try:
        return (
            _load_model(scenario_path, Scenario),
            _load_model(package_path, PersonalProcessPackage),
        )
    except (OSError, UnicodeDecodeError, ValidationError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot parse materialization input: {error}") from error
