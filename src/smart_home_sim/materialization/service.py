from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil, sqrt
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.behavior.service import default_action_catalog_path
from smart_home_sim.compiler import CompilationResult, compile_scenario
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    PersonalProcessPackage,
    ProcessNodeKind,
    ValueSource,
)
from smart_home_sim.domain.environment import (
    ENTITY_TYPE_CAPABILITIES,
    UNIVERSAL_ENTITY_CAPABILITIES,
    ConnectionKind,
    EntityCapability,
    HomeConnection,
    HomeEntity,
    HomeModel,
    HomeObstacle,
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
    EnvironmentMaterializationManifest,
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
from smart_home_sim.domain.models import RESOURCE_ROLE_ALIASES, LocationKind, Scenario
from smart_home_sim.domain.sensors import (
    CONTACT_INSTRUMENTED_TYPES,
    ContactSensor,
    PirSensor,
    SensorErrorModel,
    SensorFailureWindow,
    SensorModel,
    SensorTiming,
    TemperatureSensor,
    TemperatureSource,
)
from smart_home_sim.environment import build_bundle_files, validate_home_model
from smart_home_sim.materialization import floorplan
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


_ENTRANCE_PREFERENCE = ("hallway", "corridor", "living_room", "kitchen")


def _entrance_region(local: list[Any], regions: list[HomeRegion]) -> str:
    """Put the front door in a circulation space when the plan has one."""
    available = {item.location_id for item in local}
    for candidate in _ENTRANCE_PREFERENCE:
        if candidate in available:
            return candidate
    return local[0].location_id if local else regions[0].region_id


def _placement_clearance(policy: HomeGenerationPolicy) -> float:
    """Clearance every generated point must keep: the wider of the body and approach radii."""
    return max(policy.body_radius_meters, policy.approach_radius_meters)


def _inset_portal(rect: floorplan.Rect, wall: floorplan.SharedWall, offset: float) -> Point2D:
    """Portals sit *inside* the room, not on the wall: navigable space is the boundary eroded by
    the body radius, so a point on the wall itself is never covered by it."""
    center_x, center_y = rect.center
    if wall.vertical:
        shift = -offset if center_x < wall.x else offset
        return Point2D(x=round(wall.x + shift, 4), y=round(wall.y, 4))
    shift = -offset if center_y < wall.y else offset
    return Point2D(x=round(wall.x, 4), y=round(wall.y + shift, 4))


def _free_anchor(
    region: Any,
    room_rects: dict[str, floorplan.Rect],
    furniture_by_region: dict[str, list[floorplan.PlacedFurniture]],
    policy: HomeGenerationPolicy,
) -> Point2D:
    rect = room_rects.get(region.region_id)
    if rect is None:
        return _center(region.boundary)
    return floorplan.navigable_point(
        rect,
        furniture_by_region.get(region.region_id, []),
        body_radius=_placement_clearance(policy),
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


def _stable_fraction(*parts: str) -> float:
    material = ":".join(parts).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    return value / (2**64 - 1)


ENTRANCE_CAPABILITIES = frozenset({"home_egress", "home_ingress"})


def _entity_capabilities(
    resource_type: str, capabilities: list[EntityCapability]
) -> list[EntityCapability]:
    """The subset of the scenario's capabilities this piece of furniture genuinely offers."""
    allowed = ENTITY_TYPE_CAPABILITIES.get(resource_type)
    return [
        item
        for item in capabilities
        if item.capability not in ENTRANCE_CAPABILITIES
        and (
            allowed is None
            or item.capability in allowed
            or item.capability in UNIVERSAL_ENTITY_CAPABILITIES
        )
    ]


def _resource_roles(resource: Any) -> set[str]:
    return {
        resource.resource_id,
        resource.resource_type,
        *RESOURCE_ROLE_ALIASES.get(resource.resource_type, ()),
    }


def _json(path: Path, model: Any) -> None:
    path.write_text(model.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8")


def _json_document(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def bind_sensor_model(model: SensorModel, bundle: SimulationBundle) -> SensorModel:
    """The same sensor field, its provenance bound to the bundle it is about to observe.

    A field a researcher approved was validated against an earlier bundle — or, for a horizon,
    against no single one. Only its provenance moves; every sensor, position, coverage and error
    parameter is the researcher's, which is the whole point of approving it.
    """
    payload = json.loads(model.model_dump_json(by_alias=True))
    payload["sourceBundleId"] = bundle.bundle_id
    payload["sourceBundleSha256"] = canonical_sha256(bundle)
    payload["seed"] = bundle.seed
    return SensorModel.model_validate_json(json.dumps(payload))


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
    room_rects: dict[str, floorplan.Rect] = {}
    if policy.policy_id == "apartment-plan" and local:
        room_rects = floorplan.layout_rooms([item.location_id for item in local])
        for location in local:
            regions.append(
                HomeRegion(
                    region_id=location.location_id,
                    kind=RegionKind.room,
                    boundary=room_rects[location.location_id].to_polygon(),
                )
            )
    else:
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
    plan_height = (
        max(rect.max_y for rect in room_rects.values()) if room_rects else policy.room_height_meters
    )
    remote_y = plan_height + policy.external_spacing_meters
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
    portal_offset = min(0.4, policy.doorway_width_meters / 2)
    room_portals: dict[str, list[Point2D]] = defaultdict(list)
    if room_rects:
        # Doors follow the walls the tiling actually produced, chosen so private rooms stay leaves.
        walls = floorplan.select_doors(
            [item.location_id for item in local],
            room_rects,
            floorplan.shared_walls(room_rects, minimum_overlap=policy.doorway_width_meters + 0.2),
        )
        for wall in walls:
            portal_a = _inset_portal(room_rects[wall.region_a_id], wall, portal_offset)
            portal_b = _inset_portal(room_rects[wall.region_b_id], wall, portal_offset)
            room_portals[wall.region_a_id].append(portal_a)
            room_portals[wall.region_b_id].append(portal_b)
            connections.append(
                HomeConnection(
                    connection_id=f"door_{wall.region_a_id}_{wall.region_b_id}",
                    kind=ConnectionKind.doorway,
                    region_a_id=wall.region_a_id,
                    region_b_id=wall.region_b_id,
                    portal_a=portal_a,
                    portal_b=portal_b,
                    width_meters=policy.doorway_width_meters,
                )
            )
    else:
        for index, (left, right) in enumerate(zip(local, local[1:], strict=False), start=1):
            boundary_x = index * policy.room_width_meters
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
    resources_by_region: dict[str, list[Any]] = defaultdict(list)
    for resource in scenario.resources:
        resources_by_region[_expanded_regions(scenario, resource.location_id)[0]].append(resource)
    for region_resources in resources_by_region.values():
        region_resources.sort(key=lambda item: item.resource_id)

    # Furniture footprints: entities stop being bare points and become obstacles the visibility
    # planner has to walk around, which is what `environment/navigation.py` was always written for.
    # This runs before any interaction point is placed, because every point now has to dodge them.
    obstacles: list[HomeObstacle] = []
    furniture: dict[str, floorplan.PlacedFurniture] = {}
    furniture_by_region: dict[str, list[floorplan.PlacedFurniture]] = defaultdict(list)
    for region_id, region_resources in sorted(resources_by_region.items()):
        rect = room_rects.get(region_id)
        if rect is None:
            continue
        for item in floorplan.place_furniture(
            rect,
            [(entry.resource_id, entry.resource_type) for entry in region_resources],
            room_portals[region_id],
            body_radius=_placement_clearance(policy),
            doorway_width=policy.doorway_width_meters,
        ):
            furniture[item.entity_id] = item
            furniture_by_region[region_id].append(item)
            obstacles.append(
                HomeObstacle(
                    obstacle_id=f"obstacle_{item.entity_id}",
                    region_id=region_id,
                    boundary=item.footprint.to_polygon(),
                )
            )

    # Every route in and out of the flat leaves from the room that holds the front door. Anchoring
    # it anywhere else (it used to be simply the first room in the scenario) means the resident
    # walks out through the bedroom while the entrance sits in the hall, untouched by any path.
    anchor_id = _entrance_region(local, regions) if local else remote[0].region_id
    anchor_portal = (
        _free_anchor(regions_by_id[anchor_id], room_rects, furniture_by_region, policy)
        if anchor_id in regions_by_id
        else _center(regions_by_id[anchor_id].boundary)
    )
    for location in remote:
        if location.location_id == anchor_id:
            continue
        connections.append(
            HomeConnection(
                connection_id=f"transit_{anchor_id}_{location.location_id}",
                kind=ConnectionKind.transit,
                region_a_id=anchor_id,
                region_b_id=location.location_id,
                portal_a=anchor_portal,
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
            position=_free_anchor(region, room_rects, furniture_by_region, policy),
            approach_radius_meters=policy.approach_radius_meters,
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

    # Anything the placer refused (it would have blocked a doorway or sealed the room) still needs
    # an interaction point for its bindings to resolve, and that point must clear the furniture that
    # *was* placed.
    fallbacks: dict[str, Point2D] = {}
    for region_id, region_resources in sorted(resources_by_region.items()):
        rect = room_rects.get(region_id)
        refused = [item for item in region_resources if item.resource_id not in furniture]
        if rect is None or not refused:
            continue
        points = floorplan.free_fallback_points(
            rect,
            furniture_by_region.get(region_id, []),
            body_radius=_placement_clearance(policy),
            count=len(refused),
        )
        for resource, point in zip(refused, points, strict=False):
            fallbacks[resource.resource_id] = point

    for resource in scenario.resources:
        region_id = _expanded_regions(scenario, resource.location_id)[0]
        region_resources = resources_by_region[region_id]
        placed = furniture.get(resource.resource_id)
        if placed is not None:
            position = placed.approach
        elif resource.resource_id in fallbacks:
            position = fallbacks[resource.resource_id]
        else:
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
                approach_radius_meters=policy.approach_radius_meters,
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
                    for item in _entity_capabilities(resource.resource_type, capabilities)
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
    # The flat's front door belongs in a circulation space, and its point has to clear the
    # furniture like any other; the old fixed offset from the left wall now lands inside a wardrobe.
    entrance_region = anchor_id
    entrance_boundary = regions_by_id[entrance_region].boundary
    entrance_center = _center(entrance_boundary)
    entrance_rect = room_rects.get(entrance_region)
    if entrance_rect is not None:
        entrance_position = floorplan.navigable_point(
            entrance_rect,
            furniture_by_region.get(entrance_region, []),
            body_radius=_placement_clearance(policy),
        )
    else:
        entrance_x = min(point.x for point in entrance_boundary.vertices) + 0.75
        entrance_position = Point2D(x=entrance_x, y=entrance_center.y)
    entrance_point = InteractionPoint(
        interaction_point_id="point_entrance_door",
        region_id=entrance_region,
        position=entrance_position,
        approach_radius_meters=policy.approach_radius_meters,
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
                position=_free_anchor(region, room_rects, furniture_by_region, policy),
                approach_radius_meters=policy.approach_radius_meters,
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
        obstacles=obstacles,
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


# Interaction points a single motion sensor is expected to cover. A worktop, a sink and a stove
# standing together are one zone; the table across the room is another.
_POINTS_PER_ZONE = 3
_MAX_ZONES_PER_ROOM = 4
# Nobody installs two motion detectors a metre apart. Counting only interaction points did exactly
# that: a small bathroom packed with fixtures — toilet, shower, basin, machine, cabinet — hit the
# cap of four, where CASAS Aruba covers its bathroom with one, and the room then reported 2.9 times
# Aruba's rate per hour of occupancy. Floor the area a single zone is allowed to shrink to.
_MINIMUM_ZONE_AREA_SQUARE_METRES = 6.0
# Real detection cones overlap; a grid of disjoint cells means exactly one sensor ever sees the
# resident. Measured, Aruba fires more than one sensor within two seconds 29.5% of the time
# (1.45 distinct sensors on average) against 3.4% here (1.04) — which is most of why a synthetic
# kitchen produces a quarter of the events per hour of presence that a real one does. Each cell is
# grown by this fraction of its own size on every side, so neighbours share their borders.
_ZONE_OVERLAP_FRACTION = 0.28


def _functional_zones(
    region: HomeRegion,
    points: list[InteractionPoint],
) -> list[tuple[Point2D, Polygon2D]]:
    """Split a room into bands across its longer axis, one motion sensor per occupied band.

    One sensor per room reports every one of that room's activities as the same event, and the room
    where the resident spends her day then swallows the dataset: on one eight-month horizon the
    single kitchen sensor produced 67.3% of all observations while the balcony managed 0.3 a day.
    Adding sensors alone does not fix it — the `dense` preset gives each of them the whole room as
    coverage, so they report the same thing twice. What differentiates them is *restricted*
    coverage, which is only meaningful once the room contains distinct places to stand: a kitchen
    with nine interaction points has zones, a kitchen with a moka does not.

    A grid rather than bands across one axis. Bands were tried first and separated too little: a
    kitchen is furnished along its walls, so the fridge and the stove fell in the same strip and one
    sensor still carried 63% of the log. Cutting both axes puts an appliance run and the table in
    different cells. Reproducible from the geometry alone — no seed, no iteration, no tie to break.
    """
    xs = [vertex.x for vertex in region.boundary.vertices]
    ys = [vertex.y for vertex in region.boundary.vertices]
    minimum_x, maximum_x = min(xs), max(xs)
    minimum_y, maximum_y = min(ys), max(ys)

    # How many places there are to stand, then how many a room this size can physically hold.
    area = max(0.0, (maximum_x - minimum_x) * (maximum_y - minimum_y))
    affordable = max(1, int(area // _MINIMUM_ZONE_AREA_SQUARE_METRES))
    zones = max(1, min(_MAX_ZONES_PER_ROOM, affordable, ceil(len(points) / _POINTS_PER_ZONE)))
    columns = ceil(sqrt(zones))
    rows = ceil(zones / columns)
    width = (maximum_x - minimum_x) / columns
    height = (maximum_y - minimum_y) / rows
    # Cells stay disjoint for *assigning* points — every interaction point belongs to exactly one
    # sensor, which is what makes the zones distinguishable — while the coverage polygon that
    # decides detection is grown past them.
    margin_x = width * _ZONE_OVERLAP_FRACTION
    margin_y = height * _ZONE_OVERLAP_FRACTION

    placed: list[tuple[Point2D, Polygon2D]] = []
    for row in range(rows):
        for column in range(columns):
            left = minimum_x + column * width
            bottom = minimum_y + row * height
            members = [
                point
                for point in points
                # The far edge belongs to the last cell, so every point lands in exactly one.
                if left <= point.position.x <= left + width
                and bottom <= point.position.y <= bottom + height
                and (column == 0 or point.position.x > left)
                and (row == 0 or point.position.y > bottom)
            ]
            if not members:
                continue
            placed.append(
                (
                    Point2D(
                        x=round(sum(item.position.x for item in members) / len(members), 4),
                        y=round(sum(item.position.y for item in members) / len(members), 4),
                    ),
                    _rectangle(
                        max(minimum_x, left - margin_x),
                        max(minimum_y, bottom - margin_y),
                        min(maximum_x, left + width + margin_x) - max(minimum_x, left - margin_x),
                        min(maximum_y, bottom + height + margin_y)
                        - max(minimum_y, bottom - margin_y),
                    ),
                )
            )
    return placed or [(_center(region.boundary), region.boundary)]


def _poisson(fraction: float, mean: float) -> int:
    """Inverse-transform sample of a Poisson count from one uniform fraction."""
    if mean <= 0:
        return 0
    probability = math.exp(-mean)
    cumulative = probability
    count = 0
    while fraction > cumulative and count < 200:
        count += 1
        probability *= mean / count
        cumulative += probability
    return count


def _failure_windows(
    sensor_id: str,
    *,
    seed: int,
    policy: SensorDeploymentPolicy,
    start: datetime,
    end: datetime,
) -> list[SensorFailureWindow]:
    """When this node is off the air, decided once per sensor from the seed.

    Two mechanisms, because they leave different marks in the data. A transient outage is a hole:
    the sensor stops for an afternoon and comes back, and an algorithm that assumes continuous
    coverage reads it as the resident having gone out. A battery death is a horizon: the node
    reports nothing from that moment on, and every conclusion about that room afterwards rests on
    the sensors that are left.

    Both are ordinary in a real deployment and absent from every run this simulator has produced —
    244 days out of 244 with every device healthy. Drawn from stable fractions rather than a
    stream, so a sensor's fate depends on its own identity and not on how many sensors precede it.
    """
    span_years = max((end - start).total_seconds() / (365.25 * 86_400), 1e-9)
    windows: list[tuple[datetime, datetime]] = []

    death_probability = 1 - (1 - policy.battery_death_probability_per_year) ** span_years
    if _stable_fraction(str(seed), sensor_id, "battery-death") < death_probability:
        # Never in the opening tenth: a node that dies immediately is indistinguishable from one
        # that was never deployed, and says nothing a shorter horizon would not have said.
        position = 0.1 + 0.9 * _stable_fraction(str(seed), sensor_id, "battery-death-at")
        windows.append((start + (end - start) * position, end))

    # Poisson rather than the rate rounded off. Rounding gave every sensor of an eight-month run
    # exactly four outages, which is its own tell: real counts spread, and some nodes are simply
    # lucky. The durations spread for the same reason — a dropped packet and a router left off over
    # a weekend are both "an outage".
    expected = policy.transient_outages_per_year * span_years
    outages = _poisson(_stable_fraction(str(seed), sensor_id, "outage-count"), expected)
    for index in range(outages):
        position = _stable_fraction(str(seed), sensor_id, f"outage-at:{index}")
        spread = _stable_fraction(str(seed), sensor_id, f"outage-for:{index}")
        duration = timedelta(hours=policy.transient_outage_hours * (0.25 + 2.5 * spread**2))
        opens = start + max(end - start - duration, timedelta(0)) * position
        windows.append((opens, min(opens + duration, end)))

    # The contract refuses overlapping windows, and an outage inside a dead node's silence is not
    # a second event anyway: merge whatever collides.
    merged: list[tuple[datetime, datetime]] = []
    for opens, closes in sorted(windows):
        if merged and opens <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], closes))
        else:
            merged.append((opens, closes))
    return [SensorFailureWindow(starts_at=opens, ends_at=closes) for opens, closes in merged]


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

    def sensor_timing(sensor_id: str, *, cooldown_milliseconds: float = 0.0) -> SensorTiming:
        """Per-node timing: every sensor keeps its own stable RTC skew inside the policy band."""
        drift = 0.0
        if policy.clock_drift_ppm_spread > 0:
            fraction = _stable_fraction(str(bundle.seed), sensor_id, "clock-drift")
            drift = (fraction - 0.5) * 2 * policy.clock_drift_ppm_spread
        return SensorTiming(
            latency_milliseconds=policy.latency_milliseconds,
            clock_jitter_milliseconds=policy.clock_jitter_milliseconds,
            cooldown_milliseconds=cooldown_milliseconds,
            clock_drift_ppm=round(drift, 6),
        )

    points_by_region: dict[str, list[InteractionPoint]] = defaultdict(list)
    for point in home.interaction_points:
        points_by_region[point.region_id].append(point)

    for region in selected:
        if policy.preset == "functional_zones":
            zones = _functional_zones(region, points_by_region.get(region.region_id, []))
            for number, (position, coverage) in enumerate(zones, start=1):
                sensor_id = (
                    f"pir_{region.region_id}_{number}"
                    if len(zones) > 1
                    else (f"pir_{region.region_id}")
                )
                sensors.append(
                    PirSensor(
                        sensor_id=sensor_id,
                        position=position,
                        region_ids=[region.region_id],
                        coverage=coverage,
                        hold_milliseconds=policy.pir_hold_milliseconds,
                        hold_log_sigma=policy.pir_hold_log_sigma,
                        timing=sensor_timing(
                            sensor_id, cooldown_milliseconds=policy.pir_cooldown_milliseconds
                        ),
                        error_model=pir_error,
                    )
                )
            continue
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
                    hold_log_sigma=policy.pir_hold_log_sigma,
                    timing=sensor_timing(
                        f"pir_{region.region_id}{suffix}",
                        cooldown_milliseconds=policy.pir_cooldown_milliseconds,
                    ),
                    error_model=pir_error,
                )
            )
    entities = {item.entity_id: item for item in home.entities}
    # Instrumented because they have a door, not because the script happens to open them.
    #
    # These used to be derived from the action bindings: a cupboard nobody opened in the authored
    # behaviour got no sensor at all. That is wrong twice over. An installer fits the reed switch
    # before the study begins, so eight months of silence from the medicine cabinet *is a
    # measurement* — here it was indistinguishable from never having been instrumented. And the
    # sensor list itself became a summary of the resident's habits: reading `contact_wardrobe` in
    # the inventory told you the wardrobe gets used before you looked at a single event, which is
    # the same oracle leak as shipping the noise model in the observable log.
    contact_entities = [
        entity
        for entity in sorted(home.entities, key=lambda item: item.entity_id)
        if entity.entity_type in CONTACT_INSTRUMENTED_TYPES
    ]
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
                pulse_log_sigma=policy.contact_pulse_log_sigma,
                timing=sensor_timing("contact_entrance_door"),
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
                pulse_log_sigma=policy.contact_pulse_log_sigma,
                timing=sensor_timing(f"contact_{entity.entity_id}"),
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
        room_fraction = _stable_fraction(bundle.seed.__str__(), region.region_id, "temperature")
        room_offset = (room_fraction - 0.5) * 1.4 if policy.use_city_climate else 0.0
        sample_phase = (
            room_fraction * policy.temperature_sample_interval_seconds
            if policy.stagger_temperature_sampling
            else 0.0
        )
        sensors.append(
            TemperatureSensor(
                sensor_id=f"temperature_{region.region_id}",
                position=_center(region.boundary),
                region_id=region.region_id,
                baseline_celsius=policy.temperature_baseline_celsius,
                climate_profile="city_seasonal" if policy.use_city_climate else "fixed",
                room_offset_celsius=round(room_offset, 6),
                thermal_time_constant_hours=policy.temperature_thermal_time_constant_hours,
                quantization_celsius=policy.temperature_quantization_celsius,
                sample_phase_seconds=round(sample_phase, 6),
                seasonal_coupling=(
                    policy.temperature_seasonal_coupling if policy.use_city_climate else 0.0
                ),
                reporting_mode=policy.temperature_reporting_mode,
                report_threshold_celsius=policy.temperature_report_threshold_celsius,
                heartbeat_seconds=policy.temperature_heartbeat_seconds,
                timing=sensor_timing(f"temperature_{region.region_id}"),
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
    if policy.battery_death_probability_per_year > 0 or policy.transient_outages_per_year > 0:
        window = bundle.scenario.simulation_window
        sensors = [
            sensor.model_copy(
                update={
                    "failure_windows": _failure_windows(
                        sensor.sensor_id,
                        seed=bundle.seed,
                        policy=policy,
                        start=window.start,
                        end=window.end,
                    )
                }
            )
            for sensor in sensors
        ]

    model = SensorModel(
        sensor_model_id=f"{home.home_id}__{policy.preset}__sensors",
        sensor_model_version="1.2.0" if policy.policy_version == "1.2.0" else "1.1.0",
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


@dataclass(frozen=True)
class _Environment:
    """What the deterministic policies produce before anything is executed."""

    scenario: Scenario
    bundle: SimulationBundle
    sensor_model: SensorModel
    roles: dict[str, str]


def _accepted_compilation(precompiled: CompilationResult, scenario: Scenario) -> CompilationResult:
    """Take a caller's compilation only if its plan provably belongs to *this* scenario.

    A canonical plan records the digest of the document it was compiled from, so the check is an
    identity comparison rather than a judgement call: either the plan is the one this scenario
    compiles to, or it is somebody else's and reusing it would silently materialize a home for a
    document nobody supplied. There is no partial credit, and no way to pass by resembling.
    """
    plan = precompiled.plan
    if plan is None:
        raise MaterializationFailure(
            "compilation",
            "The supplied compilation carries no canonical plan.",
            precompiled.report.issues,
        )
    digest = canonical_sha256(scenario)
    if plan.source_scenario_id != scenario.scenario_id or plan.source_scenario_sha256 != digest:
        raise MaterializationFailure(
            "compilation",
            "The supplied canonical plan was compiled from a different scenario: "
            f"plan {plan.source_scenario_id}/{plan.source_scenario_sha256[:16]}, "
            f"scenario {scenario.scenario_id}/{digest[:16]}.",
        )
    return precompiled


def _build_environment(
    staging: Path,
    scenario_path: Path,
    package_path: Path,
    *,
    home_policy: HomeGenerationPolicy,
    sensor_policy: SensorDeploymentPolicy,
    approved_home: HomeModel | None,
    approved_sensors: SensorModel | None,
    emit: Callable[..., None],
    precompiled: CompilationResult | None = None,
) -> _Environment:
    """Compile, build the home, bind the bundle and deploy the sensor field into ``staging``.

    Everything up to, but not including, execution. Split out because it is worth having on its
    own: the plan and the sensor field are what a researcher reviews and approves, and making them
    only reachable by running the simulation meant paying for a year of execution to see a room in
    the wrong place. `materialize_workspace` continues from here; `materialize_environment` stops.
    """
    scenario = _load_model(scenario_path, Scenario)
    package = _load_model(package_path, PersonalProcessPackage)
    emit("input", 2, "Accepted source artifacts")
    shutil.copyfile(scenario_path, staging / "scenario.json")
    shutil.copyfile(package_path, staging / "personal-process-package.json")
    _json(staging / "home-generation-policy.json", home_policy)
    _json(staging / "sensor-deployment-policy.json", sensor_policy)

    compilation = (
        compile_scenario(scenario)
        if precompiled is None
        else _accepted_compilation(precompiled, scenario)
    )
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

    if approved_home is not None:
        _json(staging / "home-model.json", approved_home)
        emit(
            "home",
            26,
            "Accepted the researcher-approved plan",
            {"regions": len(approved_home.regions)},
        )
    else:
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

    if approved_sensors is not None:
        sensor_model = bind_sensor_model(approved_sensors, bundle_result.bundle)
        _json(staging / "sensor-model.json", sensor_model)
        emit(
            "sensors",
            50,
            "Accepted the researcher-approved sensor field",
            {"sensors": len(sensor_model.sensors)},
        )
    else:
        sensor_result = deploy_sensors(bundle_result.bundle, sensor_policy)
        _json(staging / "sensor-deployment-report.json", sensor_result.report)
        if sensor_result.sensor_model is None:
            raise MaterializationFailure(
                "sensors", "Sensor deployment failed.", sensor_result.report.issues
            )
        sensor_model = sensor_result.sensor_model
        _json(staging / "sensor-model.json", sensor_model)
        emit(
            "sensors",
            50,
            "Deployed and validated sensors",
            {"sensors": sensor_result.report.summary.sensor_count},
        )
    _json_document(
        staging / "plan-approval.json",
        {
            "schemaVersion": "1.0.0",
            "documentType": "plan_approval",
            "homeModel": "researcher_approved" if approved_home else "generated",
            "sensorModel": "researcher_approved" if approved_sensors else "generated",
            "homeSha256": canonical_sha256(bundle_result.bundle.home_model),
            "sensorModelSha256": canonical_sha256(sensor_model),
        },
    )
    # An approved model has no generation report: nothing generated it. The manifest records only
    # artifacts this run actually produced, and plan-approval.json says which of the two models the
    # researcher supplied.
    roles = {
        "scenario": "scenario.json",
        "behavior_package": "personal-process-package.json",
        "home_policy": "home-generation-policy.json",
        **({} if approved_home else {"home_report": "home-generation-report.json"}),
        "home": "home-model.json",
        "compilation_report": "compilation-report.json",
        "canonical_plan": "canonical-plan.json",
        "environment_report": "environment-report.json",
        "simulation_bundle": "simulation-bundle.json",
        "sensor_policy": "sensor-deployment-policy.json",
        **({} if approved_sensors else {"sensor_report": "sensor-deployment-report.json"}),
        "sensor_model": "sensor-model.json",
        "plan_approval": "plan-approval.json",
    }
    return _Environment(
        scenario=scenario, bundle=bundle_result.bundle, sensor_model=sensor_model, roles=roles
    )


def materialize_environment(
    scenario_path: Path,
    package_path: Path,
    output_directory: Path,
    *,
    home_policy: HomeGenerationPolicy | None = None,
    sensor_policy: SensorDeploymentPolicy | None = None,
    approved_home: HomeModel | None = None,
    approved_sensors: SensorModel | None = None,
    precompiled: CompilationResult | None = None,
    progress: Callable[[str, float, str, dict[str, int]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> EnvironmentMaterializationManifest:
    """Materialize the home and its sensor field from one scenario, and execute nothing.

    The output is the plan a researcher reviews: rooms, furniture, providers and the deployed
    sensors, with the same validation gates a full run applies. Nothing about it is provisional —
    a run started afterwards executes exactly these artifacts once they are approved.

    ``precompiled`` hands back a compilation the caller already paid for, which is what validating
    an authoring bundle produces on the way to its deterministic-precondition gate. It is accepted
    only when the plan's recorded source digest matches this scenario, so it saves the second solve
    without widening what the run will execute.
    """
    if output_directory.exists():
        raise FileExistsError(f"output directory already exists: {output_directory}")
    home_policy = home_policy or HomeGenerationPolicy()
    sensor_policy = sensor_policy or SensorDeploymentPolicy()
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
            # The environment is the whole job here, not its first half, so its own 2-50 becomes
            # the full bar: a progress indicator that stops at 50 reads as a job that stalled.
            progress(phase, min(percent * 2, 99), message, counters or {})

    try:
        environment = _build_environment(
            staging,
            scenario_path,
            package_path,
            home_policy=home_policy,
            sensor_policy=sensor_policy,
            approved_home=approved_home,
            approved_sensors=approved_sensors,
            precompiled=precompiled,
            emit=emit,
        )
        manifest = EnvironmentMaterializationManifest(
            scenario_id=environment.scenario.scenario_id,
            bundle_id=environment.bundle.bundle_id,
            home_id=environment.bundle.home_model.home_id,
            sensor_model_id=environment.sensor_model.sensor_model_id,
            artifacts=[
                WorkspaceArtifact(
                    role=role,
                    relative_path=relative_path,
                    sha256=_file_digest(staging / relative_path),
                )
                for role, relative_path in environment.roles.items()
            ],
        )
        _json(staging / "environment-manifest.json", manifest)
        staging.replace(output_directory)
        if progress is not None:
            progress(
                "completed",
                100,
                "Published the home and its sensor field",
                {"artifacts": len(manifest.artifacts)},
            )
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def materialize_workspace(
    scenario_path: Path,
    package_path: Path,
    output_directory: Path,
    *,
    home_policy: HomeGenerationPolicy | None = None,
    sensor_policy: SensorDeploymentPolicy | None = None,
    approved_home: HomeModel | None = None,
    approved_sensors: SensorModel | None = None,
    precompiled: CompilationResult | None = None,
    progress: Callable[[str, float, str, dict[str, int]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> SyntheticWorkspaceManifest:
    """Materialize, simulate and project one scenario into a complete synthetic workspace.

    ``approved_home``/``approved_sensors`` are the models a researcher has confirmed or edited for
    this home. When given they REPLACE the corresponding deterministic policy step: the recommended
    plan is what the generator proposes, the approved plan is what the run executes. They are not
    trusted blindly — the M4 bundle gate and the M6 sensor contract judge them exactly as they judge
    a generated model, and a rejected approved model fails the run instead of quietly falling back
    to the policy, which would simulate a home the researcher never agreed to.

    ``precompiled`` is different in kind: not a model to approve but a solve already done, which
    validating an authoring bundle produces on its way to the deterministic-precondition gate. It
    is accepted only when the plan's recorded source digest matches this scenario, so it removes a
    duplicate solve without changing what runs.
    """
    if output_directory.exists():
        raise FileExistsError(f"output directory already exists: {output_directory}")
    home_policy = home_policy or HomeGenerationPolicy()
    sensor_policy = sensor_policy or SensorDeploymentPolicy()
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
        environment = _build_environment(
            staging,
            scenario_path,
            package_path,
            home_policy=home_policy,
            sensor_policy=sensor_policy,
            approved_home=approved_home,
            approved_sensors=approved_sensors,
            precompiled=precompiled,
            emit=emit,
        )
        scenario = environment.scenario
        bundle = environment.bundle
        sensor_model = environment.sensor_model

        emit("simulation", 52, "Started deterministic execution")
        simulation = simulate_bundle(bundle)
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
        projection = project_sensors(simulation.trace, bundle, sensor_model)
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
            **environment.roles,
            "simulation_report": "simulation-report.json",
            "execution_trace": "execution-trace.json",
            "projection_report": "sensor-projection-report.json",
            "observable_sensor_log": "observable-sensor-log.json",
            "oracle_mapping": "oracle-mapping.json",
        }
        manifest = SyntheticWorkspaceManifest(
            scenario_id=scenario.scenario_id,
            bundle_id=bundle.bundle_id,
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
        return SensorDeploymentPolicy.realistic()
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
