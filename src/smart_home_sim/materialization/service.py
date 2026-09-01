from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import atan2, ceil, degrees, hypot
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from shapely.geometry import MultiPoint, Point, Polygon
from shapely.geometry import box as ShapelyBox
from shapely.ops import unary_union, voronoi_diagram

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
    capabilities_for_entity_type,
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
    ContactSensor,
    PirSensor,
    SensorErrorModel,
    SensorFailureWindow,
    SensorModel,
    SensorTiming,
    TemperatureSensor,
    TemperatureSource,
    contact_instrumented_types,
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


ENTRANCE_PREFERENCE = ("hallway", "corridor", "living_room", "kitchen")


def _entrance_region(local: list[Any], regions: list[HomeRegion]) -> str:
    """Put the front door in a circulation space when the plan has one."""
    available = {item.location_id for item in local}
    for candidate in ENTRANCE_PREFERENCE:
        if candidate in available:
            return candidate
    return local[0].location_id if local else regions[0].region_id


def _level_of(location: Any) -> int:
    """Which storey a scenario location declares itself to be on.

    Carried in `attributes` rather than as a field of its own: a storey is a property of this
    particular dwelling, every scenario written before houses had storeys means the ground floor,
    and the location contract does not have to change for either of those to be true.
    """
    value = location.attributes.get("level", 0)
    return int(value) if isinstance(value, int | float) and int(value) >= 0 else 0


# What `dwelling_scale` may be. Named rather than inline because the authoring prompt prints the
# range: a bound the prompt restates by hand is a bound that drifts, and an author who reads 3.5
# and writes it gets silently given 1.0.
MIN_DWELLING_SCALE = 0.4
MAX_DWELLING_SCALE = 3.0


def _plan_scale(scenario: Any) -> float:
    """How much bigger or smaller than the reference flat this dwelling is drawn.

    A studio and a family house are furnished from the same room profiles, and without this they
    would also be *sized* from them — every generated home came out the same 60 square metres
    whatever it claimed to be.
    """
    value = scenario.initial_state.environment_facts.get("dwelling_scale", 1.0)
    if isinstance(value, int | float) and MIN_DWELLING_SCALE <= float(value) <= MAX_DWELLING_SCALE:
        return float(value)
    return 1.0


STAIR_ROOM_PREFERENCE = ("landing", "hallway", "corridor", "entrance", "living_room")
# The four walls a flight can run up, as the direction somebody stepping off it is facing.
_STAIR_FACINGS: tuple[tuple[float, float], ...] = (
    (0.0, 1.0),
    (0.0, -1.0),
    (1.0, 0.0),
    (-1.0, 0.0),
)
# Flight lengths, longest first: a straight run, then progressively shorter ones, down to the
# quarter-turn a small landing can actually hold.
_STAIR_LENGTHS: tuple[float, ...] = (2.6, 2.2, 1.8, 1.4, 1.1)
_STAIR_WIDTH = 1.0


def _stair_region(
    local: list[Any],
    levels: dict[str, int],
    level: int,
    rects: dict[str, floorplan.Rect],
) -> str | None:
    """Which room on this storey the stairs come up in: a circulation space, or the largest room."""
    on_level = [item.location_id for item in local if levels[item.location_id] == level]
    for candidate in STAIR_ROOM_PREFERENCE:
        for region_id in on_level:
            if candidate in region_id:
                return region_id
    if not on_level:
        return None
    return max(on_level, key=lambda region_id: rects[region_id].width * rects[region_id].height)


def _distance_to_rect(point: tuple[float, float], rect: floorplan.Rect) -> float:
    dx = max(rect.x - point[0], 0.0, point[0] - rect.max_x)
    dy = max(rect.y - point[1], 0.0, point[1] - rect.max_y)
    return (dx * dx + dy * dy) ** 0.5


def _stair_pose(
    room: floorplan.Rect, doors: list[Point2D], policy: HomeGenerationPolicy
) -> tuple[floorplan.Rect, Point2D, float]:
    """Where the flight of stairs stands in this room, and the point at its foot.

    A staircase is the one piece of furniture the plan cannot do without: everything upstairs is
    unreachable without it, so it is placed before anything else and the arrangement works round it.
    That also makes it the piece with the least freedom, and stamping a fixed 1.0 x 2.6 flight in
    the middle of a wall does not survive contact with a real landing. Two full-length flights along
    facing walls leave twenty centimetres of floor between them; one along the wall a doorway is on
    buries the portal, and the router then reports a hallway with no way out.

    So the flight is searched for rather than assumed: every wall, a range of lengths from a full
    flight down to a short one, and every position along the wall. Length is given up before
    landing space and before the doorways, in that order.
    """
    clearance = _placement_clearance(policy) + 0.02
    step = clearance + 0.10
    keep_clear = policy.doorway_width_meters / 2 + clearance

    def clear_of_doors(rect: floorplan.Rect) -> float:
        return min((_distance_to_rect((door.x, door.y), rect) for door in doors), default=99.0)

    options: list[tuple[float, float, floorplan.Rect, Point2D, float]] = []
    # Every pose that stands on real floor, including the ones too close to a doorway. A small
    # landing with three doors off it has no pose that clears them all, and the fallback below used
    # to stop looking and stamp a flight across the middle of the room — on one generated house
    # exactly over the bathroom door, which put twenty-two routes out of reach and failed the run.
    # Keeping the near misses means the worst case is a tight staircase rather than a sealed room.
    crowded: list[tuple[float, float, floorplan.Rect, Point2D, float]] = []
    for facing in _STAIR_FACINGS:
        vertical = facing[0] == 0.0
        along = room.width if vertical else room.height
        low = room.x if vertical else room.y
        across = room.height if vertical else room.width
        for depth in _STAIR_LENGTHS:
            if depth > across - step - clearance - 0.05:
                continue
            width = min(_STAIR_WIDTH, along - 2 * clearance)
            if width < 0.7:
                continue
            positions = max(int((along - width) / 0.20), 0)
            for index in range(positions + 1):
                offset = min(index * 0.20, along - width)
                centre_along = low + offset + width / 2
                if vertical:
                    y = room.y if facing[1] > 0 else room.max_y - depth
                    rect = floorplan.Rect(centre_along - width / 2, y, width, depth)
                else:
                    x = room.x if facing[0] > 0 else room.max_x - depth
                    rect = floorplan.Rect(x, centre_along - width / 2, depth, width)
                reach = (abs(facing[0]) * rect.width + abs(facing[1]) * rect.height) / 2
                centre = (rect.x + rect.width / 2, rect.y + rect.height / 2)
                foot = Point2D(
                    x=round(centre[0] + facing[0] * (reach + step), 4),
                    y=round(centre[1] + facing[1] * (reach + step), 4),
                )
                # The foot has to be floor a body fits on, which is the room eroded by the same
                # clearance the navigator routes with. Anything else plans a route nobody can walk.
                if not (
                    room.x + clearance <= foot.x <= room.max_x - clearance
                    and room.y + clearance <= foot.y <= room.max_y - clearance
                ):
                    continue
                margin = min(clear_of_doors(rect), _distance_to_doors(foot, doors))
                pose = (depth, margin, rect, foot, _bearing(facing))
                if margin < keep_clear:
                    crowded.append(pose)
                    continue
                # A long flight beats a short one, and among equals the one furthest from the
                # doorways wins: stairs belong at the quiet end of a hall.
                options.append(pose)
    if options:
        _, _, rect, foot, bearing = max(options, key=lambda item: (item[0], item[1]))
        return rect, foot, bearing
    if crowded:
        # No pose clears the doorways. Length is what gets given up now, not the doors: a short
        # flight the resident has to squeeze past still leaves every room reachable, and a long one
        # laid over a doorway does not. Margin first, and the longest among equals.
        _, _, rect, foot, bearing = max(crowded, key=lambda item: (item[1], item[0]))
        return rect, foot, bearing

    # Not even a short flight stands on this floor. An unreachable storey is worse than a tight
    # staircase, so take the least bad pose instead of giving up.
    fallback = min(2.0, max(room.width, room.height) / 2)
    rect = floorplan.Rect(room.center[0] - 0.45, room.y, 0.9, max(fallback, 0.8))
    return (
        rect,
        Point2D(
            x=round(room.center[0], 4),
            y=round(min(rect.max_y + step, room.max_y - clearance), 4),
        ),
        90.0,
    )


def _distance_to_doors(point: Point2D, doors: list[Point2D]) -> float:
    return min(
        (((point.x - door.x) ** 2 + (point.y - door.y) ** 2) ** 0.5 for door in doors),
        default=99.0,
    )


def _bearing(facing: tuple[float, float]) -> float:
    """A unit direction as a bearing: 0 along +x, 90 along +y, counted anticlockwise."""
    return round(degrees(atan2(facing[1], facing[0])) % 360.0, 1)


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
    reserved: dict[str, list[floorplan.Rect]] | None = None,
) -> Point2D:
    rect = room_rects.get(region.region_id)
    if rect is None:
        return _center(region.boundary)
    return floorplan.navigable_point(
        rect,
        furniture_by_region.get(region.region_id, []),
        body_radius=_placement_clearance(policy),
        reserved=(reserved or {}).get(region.region_id),
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
# The roles that name the front door, and nothing else. They belong to `entrance_door` alone: the
# per-region service anchors used to carry them too, and since `move_to_capability{home_entrance}`
# asks for an `interaction_point` — a capability the door did not offer — "walk to the front door"
# bound to whichever anchor sorted first. On a day with an outing that was the one outdoors, so
# leaving the flat became a 504-metre hop *out*, a `leave_home` that walked back *in* to the door,
# and a second hop out: 515 exits a year, 1,030 ghost crossings of the living room, and the door
# contact firing on only one of the three legs.
ENTRANCE_ROLES = ("entrance", "home_entrance", "home_exit")


def _entity_capabilities(
    resource_type: str, capabilities: list[EntityCapability]
) -> list[EntityCapability]:
    """The subset of the scenario's capabilities this piece of furniture genuinely offers."""
    allowed = capabilities_for_entity_type(resource_type)
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
    # Which storey each room is on. The scenario says so through the location's own attributes, so
    # a one-storey flat is unchanged and needs no migration: everything defaults to the ground.
    levels = {item.location_id: _level_of(item) for item in local}
    if policy.policy_id == "apartment-plan" and local:
        room_rects = floorplan.layout_rooms(
            [item.location_id for item in local],
            levels=levels,
            level_spacing=policy.level_spacing_meters,
            scale=_plan_scale(scenario),
        )
        for location in local:
            regions.append(
                HomeRegion(
                    region_id=location.location_id,
                    kind=RegionKind.room,
                    boundary=room_rects[location.location_id].to_polygon(),
                    level=levels[location.location_id],
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
    obstacles_from_structure: list[HomeObstacle] = []
    reserved: dict[str, list[floorplan.Rect]] = defaultdict(list)
    if room_rects:
        # Doors follow the walls the tiling actually produced, chosen so private rooms stay leaves.
        # Storeys are tiled independently and must be doored independently: run over all of them at
        # once and the connectivity repair happily invents a doorway between the ground-floor
        # kitchen and an upstairs bedroom, because on the page they are only four metres apart.
        walls = []
        for level in sorted(set(levels.values())):
            storey_ids = [item.location_id for item in local if levels[item.location_id] == level]
            storey_rects = {region_id: room_rects[region_id] for region_id in storey_ids}
            walls.extend(
                floorplan.select_doors(
                    storey_ids,
                    storey_rects,
                    floorplan.shared_walls(
                        storey_rects, minimum_overlap=policy.doorway_width_meters + 0.2
                    ),
                )
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
    # Staircases. A storey that is not the ground one has to be reachable, and the only thing that
    # reaches it is a flight of stairs: a real object standing on real floor at both ends, which is
    # why it is an obstacle here and not merely an edge in the graph.
    for lower, upper in zip(
        sorted(set(levels.values())), sorted(set(levels.values()))[1:], strict=False
    ):
        bottom = _stair_region(local, levels, lower, room_rects)
        top = _stair_region(local, levels, upper, room_rects)
        if bottom is None or top is None:
            continue
        # Named after the flight rather than the room it lands in: a middle storey of a three-floor
        # house has two flights in the same landing, and one id between them is a home model that
        # refuses to be built at all.
        feet: dict[str, Point2D] = {}
        for region_id in (bottom, top):
            footprint, portal, bearing = _stair_pose(
                room_rects[region_id], room_portals[region_id], policy
            )
            reserved[region_id].append(footprint)
            # The foot of the stairs joins the doorways as floor no arrangement may take: a
            # staircase you have to move the sofa to reach is a staircase nobody can use.
            room_portals[region_id].append(portal)
            obstacles_from_structure.append(
                HomeObstacle(
                    obstacle_id=f"obstacle_stairs_{bottom}_{top}_{region_id}",
                    region_id=region_id,
                    boundary=footprint.to_polygon(),
                    orientation_degrees=bearing,
                )
            )
            feet[region_id] = portal
        connections.append(
            HomeConnection(
                connection_id=f"stairs_{bottom}_{top}",
                kind=ConnectionKind.stairway,
                region_a_id=bottom,
                region_b_id=top,
                portal_a=feet[bottom],
                portal_b=feet[top],
                width_meters=policy.doorway_width_meters,
                distance_meters=policy.stair_run_meters,
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
    obstacles: list[HomeObstacle] = list(obstacles_from_structure)
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
            # The arrangement is a function of the room and the scenario's own seed: the same
            # scenario always furnishes the same way, and two scenarios do not have to.
            region_id=region_id,
            seed=scenario.seed,
            reserved=reserved.get(region_id),
        ):
            furniture[item.entity_id] = item
            furniture_by_region[region_id].append(item)
            obstacles.append(
                HomeObstacle(
                    obstacle_id=f"obstacle_{item.entity_id}",
                    orientation_degrees=item.orientation_degrees,
                    region_id=region_id,
                    boundary=item.footprint.to_polygon(),
                )
            )

    # Every route in and out of the flat leaves from the room that holds the front door. Anchoring
    # it anywhere else (it used to be simply the first room in the scenario) means the resident
    # walks out through the bedroom while the entrance sits in the hall, untouched by any path.
    anchor_id = _entrance_region(local, regions) if local else remote[0].region_id
    anchor_portal = (
        _free_anchor(regions_by_id[anchor_id], room_rects, furniture_by_region, policy, reserved)
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
            position=_free_anchor(region, room_rects, furniture_by_region, policy, reserved),
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
            reserved=reserved.get(region_id),
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
            reserved=reserved.get(entrance_region),
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
    # The door answers to its own roles for going out, coming in, opening — and for being walked
    # to. That last one is `interaction_point`, and leaving it off is what sent the resident
    # outdoors to reach her own front door; see the note on `ENTRANCE_ROLES`.
    entrance_capabilities = [
        item.model_copy(update={"roles": list(ENTRANCE_ROLES)})
        for item in capabilities
        if item.capability in ENTRANCE_CAPABILITIES or item.capability == "interaction_point"
    ]
    entrance_capabilities.append(
        EntityCapability(
            capability="openable",
            roles=list(ENTRANCE_ROLES),
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
                position=_free_anchor(region, room_rects, furniture_by_region, policy, reserved),
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
                        update={
                            "roles": sorted(
                                set(item.roles) - assigned_semantic_roles - set(ENTRANCE_ROLES)
                            )
                        }
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


_MAX_ZONES_PER_ROOM = 4
# How wide one zone may be: a worktop, a sink and a stove standing together are one, and the table
# across the room is another. Tightened where more happens, because the same two metres carry more
# information in a kitchen than on a balcony.
#
# The widths come from CASAS Aruba's own map. It never instruments an appliance — no fridge, no
# hob, no washing machine appears among its twenty-six detectors — but it does put one either side
# of the bed, one at each end of the sofa and one at each end of the bookcase. The unit is the
# place a body occupies, and two of those can be a metre and a half apart on one piece of
# furniture, which is why the busy figure sits below that.
_ZONE_DIAMETER_QUIET = 1.9
_ZONE_DIAMETER_ACTIVE = 1.6
_ZONE_DIAMETER_BUSY = 1.3
# Activities over the whole horizon, not per day: a balcony visited for the laundry sits in the
# tens, a bedroom in the dozens, and the kitchen and the bathroom in the hundreds.
_ACTIVE_ROOM_ACTIVITIES = 30
_BUSY_ROOM_ACTIVITIES = 150
# How far past its own share of the floor a detector still sees. Neighbouring cones overlap in a
# real home, and a partition where exactly one sensor ever fires is most of why a synthetic kitchen
# produces a quarter of the events per hour of presence that a real one does.
_ZONE_OVERLAP_METRES = 0.6
# How far either side of a doorway its own detector sees. Wide enough that a crossing is caught
# from both rooms, narrow enough that it does not become a third sensor for each of them.
_THRESHOLD_REACH_METRES = 0.9
# Nobody installs two motion detectors a metre apart. Counting only interaction points did exactly
# that: a small bathroom packed with fixtures — toilet, shower, basin, machine, cabinet — hit the
# cap of four, where CASAS Aruba covers its bathroom with one, and the room then reported 2.9 times
# Aruba's rate per hour of occupancy. Floor the area a single zone is allowed to shrink to.
_MINIMUM_ZONE_AREA_SQUARE_METRES = 6.0


def _zone_diameter(activity_count: int) -> float:
    """How far apart two places to stand may be and still share a detector.

    A busy room is worth telling apart more finely than a quiet one: the same two metres between a
    hob and a sink matter in a kitchen that hosts ten activities a day and do not in a balcony that
    hosts one. Three steps rather than a formula, because the evidence behind the bounds is coarse
    and a smooth curve would imply a precision nobody measured.
    """
    if activity_count >= _BUSY_ROOM_ACTIVITIES:
        return _ZONE_DIAMETER_BUSY
    if activity_count >= _ACTIVE_ROOM_ACTIVITIES:
        return _ZONE_DIAMETER_ACTIVE
    return _ZONE_DIAMETER_QUIET


def _cluster_places(
    places: list[tuple[float, float]], diameter: float, cap: int
) -> list[list[int]]:
    """Group the places to stand, complete-link, then fold the nearest pairs down to the cap.

    Complete-link rather than single-link: a zone is bounded by its own width, so an appliance run
    of six units along three metres of wall becomes two zones instead of chaining into one. Single
    link was tried and did exactly that, merging a hob, a moka, a cupboard, a chair, a fridge and a
    sink into one zone and reporting the whole kitchen as a single place.
    """
    groups = [[index] for index in range(len(places))]

    def spread(left: list[int], right: list[int]) -> float:
        return max(
            hypot(places[a][0] - places[b][0], places[a][1] - places[b][1])
            for a in left
            for b in right
        )

    while True:
        nearest: tuple[float, int, int] | None = None
        for left in range(len(groups)):
            for right in range(left + 1, len(groups)):
                gap = spread(groups[left], groups[right])
                if nearest is None or gap < nearest[0]:
                    nearest = (gap, left, right)
        if nearest is None:
            break
        gap, left, right = nearest
        # Past the cap the room cannot afford another detector, so the closest pair merges however
        # far apart it is; below it, only pairs that fit inside one zone do.
        if gap > diameter and len(groups) <= cap:
            break
        groups[left] = groups[left] + groups.pop(right)
    return groups


def _functional_zones(
    region: HomeRegion,
    points: list[InteractionPoint],
    activity_count: int = 0,
) -> list[tuple[Point2D, Polygon2D]]:
    """One motion sensor per group of places to stand, covering that group and its surroundings.

    One sensor per room reports every one of that room's activities as the same event, and the room
    where the resident spends her day then swallows the dataset: on one eight-month horizon the
    single kitchen sensor produced 67.3% of all observations while the balcony managed 0.3 a day.
    Adding sensors alone does not fix it — the `dense` preset gives each of them the whole room as
    coverage, so they report the same thing twice. What differentiates them is *restricted*
    coverage, which is only meaningful once the room contains distinct places to stand.

    Those places are found by clustering rather than by cutting the room into equal cells. The grid
    that did this before divided the bounding box into halves or quarters and dropped the empty
    ones, which asks the geometry a question the furniture answers: a living room 5.3 m wide and
    6.4 m deep, with the television at one end and the sofa at the other, was split into *columns* —
    both pieces fell in the same one, the other stood empty, and a 33.8 m² room ended up with a
    single detector covering 21.6 m² of it. Clustering asks instead which places are close enough
    to be one place, so the boundaries land where the furniture puts them.

    The caps do not move. `_MINIMUM_ZONE_AREA_SQUARE_METRES` is why a bathroom packed with fixtures
    still gets one detector where CASAS Aruba has one, and lifting it is what once made that room
    report 2.9 times Aruba's rate. This changes where the allowed detectors go, not how many a room
    may have.
    """
    xs = [vertex.x for vertex in region.boundary.vertices]
    ys = [vertex.y for vertex in region.boundary.vertices]
    minimum_x, maximum_x = min(xs), max(xs)
    minimum_y, maximum_y = min(ys), max(ys)

    # Two objects sharing a position are one place to stand: the room anchor and its service point
    # always do, and counting them twice would split a zone off nothing.
    places = sorted({(round(item.position.x, 4), round(item.position.y, 4)) for item in points})
    area = max(0.0, (maximum_x - minimum_x) * (maximum_y - minimum_y))
    affordable = max(1, int(area // _MINIMUM_ZONE_AREA_SQUARE_METRES))
    cap = max(1, min(_MAX_ZONES_PER_ROOM, affordable))
    if not places:
        return [(_center(region.boundary), region.boundary)]

    centres = [
        (
            round(sum(places[index][0] for index in group) / len(group), 4),
            round(sum(places[index][1] for index in group) / len(group), 4),
        )
        for group in _cluster_places(places, _zone_diameter(activity_count), cap)
    ]
    centres.sort(key=lambda item: (item[1], item[0]))
    if len(centres) == 1:
        return [(Point2D(x=centres[0][0], y=centres[0][1]), region.boundary)]

    # The detectors share the room out between them rather than each taking a box around its own
    # furniture. Boxes were tried first and left 60% of a living room unwatched, which is worse than
    # the single sensor it replaced: a body crossing an unwatched floor emits nothing at all. Each
    # zone therefore takes the floor nearest to it and then grows past that boundary, so the room is
    # covered once and its neighbours overlap — measured, Aruba fires more than one sensor within
    # two seconds 29.5% of the time against 3.4% here.
    room = Polygon([(vertex.x, vertex.y) for vertex in region.boundary.vertices])
    cells = voronoi_diagram(MultiPoint(centres), envelope=room)
    placed: list[tuple[Point2D, Polygon2D]] = []
    for centre in centres:
        owner = next(
            (cell for cell in cells.geoms if cell.covers(Point(centre))),
            None,
        )
        shape = room if owner is None else owner.intersection(room)
        grown = shape.buffer(_ZONE_OVERLAP_METRES, join_style=2).intersection(room)
        winner = (
            max(grown.geoms, key=lambda item: item.area) if grown.geom_type != "Polygon" else grown
        )
        placed.append(
            (
                Point2D(x=centre[0], y=centre[1]),
                Polygon2D(
                    vertices=[
                        Point2D(x=round(x, 4), y=round(y, 4))
                        for x, y in list(winner.exterior.coords)[:-1]
                    ]
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


def _threshold_sensors(
    home: HomeModel,
    rooms: set[str],
    *,
    hold_milliseconds: float,
    hold_log_sigma: float,
    timing: Any,
    error_model: SensorErrorModel,
) -> list[PirSensor]:
    """One detector per doorway, watching the crossing rather than either room.

    Nine of Aruba's twenty-six motion sensors — 35% of the field — sit on passages and doors:
    `front_door`, `back_door`, `garage_door` and six more watching the way between one room and the
    next. A field with none of them, as this one had, records where the resident settles and leaves
    the moving between almost unwitnessed, which is the half a habit-segmentation algorithm keys
    on: a band of the day is recognised as much by the transitions that open and close it as by
    what fills it.

    The sensor belongs to *both* rooms, which the contract allows and which is what a doorway
    detector actually is. Its coverage straddles the threshold and overlaps the zones on either
    side, so a crossing fires it and its neighbour together — the way two real cones do.
    """
    shapes = {
        region.region_id: Polygon([(vertex.x, vertex.y) for vertex in region.boundary.vertices])
        for region in home.regions
    }
    placed: list[PirSensor] = []
    for connection in sorted(home.connections, key=lambda item: item.connection_id):
        # Doorways only. A staircase joins two storeys drawn side by side in one plane, so the gap
        # between its ends is a drawing convention and not a place a body passes through.
        if connection.kind is not ConnectionKind.doorway:
            continue
        left, right = connection.region_a_id, connection.region_b_id
        if left not in rooms or right not in rooms:
            continue
        if left not in shapes or right not in shapes:
            continue
        centre = (
            (connection.portal_a.x + connection.portal_b.x) / 2,
            (connection.portal_a.y + connection.portal_b.y) / 2,
        )
        both = unary_union([shapes[left], shapes[right]])
        reach = _THRESHOLD_REACH_METRES
        area = ShapelyBox(
            centre[0] - reach, centre[1] - reach, centre[0] + reach, centre[1] + reach
        ).intersection(both)
        if area.is_empty or area.area <= 0:
            continue
        shape = max(area.geoms, key=lambda item: item.area) if area.geom_type != "Polygon" else area
        # The position has to lie inside the coverage, and a doorway's own midpoint sits on the
        # wall between two rooms, which belongs to neither interior.
        seat = shape.representative_point()
        sensor_id = f"pir_{connection.connection_id}"
        placed.append(
            PirSensor(
                sensor_id=sensor_id,
                position=Point2D(x=round(seat.x, 4), y=round(seat.y, 4)),
                region_ids=sorted((left, right)),
                coverage=Polygon2D(
                    vertices=[
                        Point2D(x=round(x, 4), y=round(y, 4))
                        for x, y in list(shape.exterior.coords)[:-1]
                    ]
                ),
                hold_milliseconds=hold_milliseconds,
                hold_log_sigma=hold_log_sigma,
                timing=timing(sensor_id),
                error_model=error_model,
            )
        )
    return placed


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

    # How much happens in each room over the whole horizon. The furniture says where the places to
    # stand are; this says how much it is worth telling them apart, and the two together are what a
    # researcher would weigh when deciding where to put a detector.
    activities_by_region: Counter[str] = Counter()
    for day in bundle.scenario.days:
        for activity in day.activities:
            for location in activity.location_ids[:1]:
                for region_id in _expanded_regions(bundle.scenario, location):
                    activities_by_region[region_id] += 1

    for region in selected:
        if policy.preset == "functional_zones":
            zones = _functional_zones(
                region,
                points_by_region.get(region.region_id, []),
                activities_by_region.get(region.region_id, 0),
            )
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
    if policy.preset == "functional_zones":
        sensors.extend(
            _threshold_sensors(
                home,
                {item.region_id for item in selected},
                hold_milliseconds=policy.pir_hold_milliseconds,
                hold_log_sigma=policy.pir_hold_log_sigma,
                timing=lambda sensor_id: sensor_timing(
                    sensor_id, cooldown_milliseconds=policy.pir_cooldown_milliseconds
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
        if entity.entity_type in contact_instrumented_types()
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

    # The plan staged above is this function's own compilation output, so the binder's M2 gate can
    # be answered from what we already hold instead of solving the horizon a second time to
    # re-derive it — on a five-month horizon, roughly twenty minutes of CP-SAT that reproduces the
    # bytes in `canonical-plan.json`. The gate is not skipped: the staged file still has to equal
    # this digest. A plan handed in by a caller is a different matter — nothing here compiled it —
    # so that path keeps re-compiling as its independent check.
    bundle_result = build_bundle_files(
        staging / "scenario.json",
        staging / "canonical-plan.json",
        staging / "personal-process-package.json",
        staging / "home-model.json",
        compiled_plan_digest=(canonical_sha256(compilation.plan) if precompiled is None else None),
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
