from __future__ import annotations

from dataclasses import dataclass
from math import hypot

import networkx as nx
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from smart_home_sim.domain.environment import (
    HomeConnection,
    HomeModel,
    Point2D,
    TraversalMode,
)


@dataclass(frozen=True)
class NavigationWaypoint:
    region_id: str
    x: float
    y: float
    traversal_mode: str


@dataclass(frozen=True)
class NavigationPath:
    waypoints: tuple[NavigationWaypoint, ...]
    distance_meters: float
    duration_seconds: float


def _polygon(vertices: list[Point2D]) -> Polygon:
    return Polygon([(point.x, point.y) for point in vertices])


def _free_space(home: HomeModel, region_id: str, radius: float) -> Polygon:
    region = next(item for item in home.regions if item.region_id == region_id)
    boundary = _polygon(region.boundary.vertices)
    obstacles = [
        _polygon(item.boundary.vertices).buffer(radius, join_style="mitre")
        for item in home.obstacles
        if item.region_id == region_id
    ]
    space = boundary.buffer(-radius, join_style="mitre")
    if obstacles:
        space = space.difference(unary_union(obstacles))
    if space.geom_type != "Polygon":
        polygons = list(space.geoms) if hasattr(space, "geoms") else []
        if not polygons:
            raise ValueError(f"region '{region_id}' has no navigable free space")
        space = max(polygons, key=lambda item: item.area)
    return space


def _visibility_path(
    home: HomeModel,
    region_id: str,
    start: tuple[float, float],
    end: tuple[float, float],
    radius: float,
) -> tuple[list[tuple[float, float]], float]:
    free = _free_space(home, region_id, radius)
    if not free.covers(Point(start)) or not free.covers(Point(end)):
        raise ValueError(f"route endpoint is outside navigable space in region '{region_id}'")
    vertices = {start, end}
    vertices.update((float(x), float(y)) for x, y in list(free.exterior.coords)[:-1])
    for ring in free.interiors:
        vertices.update((float(x), float(y)) for x, y in list(ring.coords)[:-1])
    ordered = sorted(vertices)
    graph = nx.Graph()
    graph.add_nodes_from(ordered)
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            segment = LineString([left, right])
            if free.covers(segment):
                graph.add_edge(left, right, weight=hypot(right[0] - left[0], right[1] - left[1]))
    try:
        path = nx.shortest_path(graph, start, end, weight="weight", method="dijkstra")
    except nx.NetworkXNoPath as error:
        raise ValueError(f"no collision-free path in region '{region_id}'") from error
    return path, sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:], strict=False))


def _connection_graph(home: HomeModel, mobility_profile: str) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(region.region_id for region in home.regions if region.traversable))
    for connection in sorted(home.connections, key=lambda item: item.connection_id):
        if connection.allowed_mobility_profiles and (
            mobility_profile not in connection.allowed_mobility_profiles
        ):
            continue
        weight = connection.distance_meters or hypot(
            connection.portal_b.x - connection.portal_a.x,
            connection.portal_b.y - connection.portal_a.y,
        )
        graph.add_edge(
            connection.region_a_id,
            connection.region_b_id,
            weight=weight,
            connection=connection,
        )
        if connection.bidirectional:
            graph.add_edge(
                connection.region_b_id,
                connection.region_a_id,
                weight=weight,
                connection=connection,
            )
    return graph


def _oriented_portals(
    connection: HomeConnection, source_region_id: str
) -> tuple[tuple[float, float], tuple[float, float]]:
    if connection.region_a_id == source_region_id:
        return (
            (connection.portal_a.x, connection.portal_a.y),
            (connection.portal_b.x, connection.portal_b.y),
        )
    return (
        (connection.portal_b.x, connection.portal_b.y),
        (connection.portal_a.x, connection.portal_a.y),
    )


def plan_path(
    home: HomeModel,
    *,
    start_region_id: str,
    start: Point2D,
    end_region_id: str,
    end: Point2D,
    walking_speed_meters_per_second: float,
    body_radius_meters: float,
    mobility_profile: str,
) -> NavigationPath:
    """Return a deterministic, collision-free route and timestampable travel duration."""
    if walking_speed_meters_per_second <= 0 or body_radius_meters <= 0:
        raise ValueError("kinematic values must be positive")
    graph = _connection_graph(home, mobility_profile)
    try:
        regions = nx.shortest_path(
            graph,
            start_region_id,
            end_region_id,
            weight="weight",
            method="dijkstra",
        )
    except (nx.NodeNotFound, nx.NetworkXNoPath) as error:
        raise ValueError(
            f"no route from region '{start_region_id}' to '{end_region_id}'"
        ) from error

    current = (start.x, start.y)
    waypoints = [NavigationWaypoint(start_region_id, start.x, start.y, "walking")]
    walking_distance = 0.0
    transport_distance = 0.0
    for source_region, target_region in zip(regions, regions[1:], strict=False):
        connection: HomeConnection = graph[source_region][target_region]["connection"]
        source_portal, target_portal = _oriented_portals(connection, source_region)
        segment, distance = _visibility_path(
            home, source_region, current, source_portal, body_radius_meters
        )
        walking_distance += distance
        waypoints.extend(NavigationWaypoint(source_region, x, y, "walking") for x, y in segment[1:])
        mode = connection.traversal_mode.value
        waypoints.append(NavigationWaypoint(target_region, *target_portal, mode))
        if connection.traversal_mode is TraversalMode.transport:
            transport_distance += connection.distance_meters or 0.0
        else:
            walking_distance += hypot(
                target_portal[0] - source_portal[0], target_portal[1] - source_portal[1]
            )
        current = target_portal
    segment, distance = _visibility_path(
        home, end_region_id, current, (end.x, end.y), body_radius_meters
    )
    walking_distance += distance
    waypoints.extend(NavigationWaypoint(end_region_id, x, y, "walking") for x, y in segment[1:])
    # Transport links declare metric distance but not a speed; 8 m/s is the frozen M4 urban default.
    duration = walking_distance / walking_speed_meters_per_second + transport_distance / 8.0
    return NavigationPath(tuple(waypoints), walking_distance + transport_distance, duration)
