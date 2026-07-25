from __future__ import annotations

from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon

from smart_home_sim.domain.environment import Point2D
from smart_home_sim.materialization.floorplan import (
    Rect,
    connect_all,
    layout_rooms,
    navigable_point,
    place_furniture,
    select_doors,
    shared_walls,
)

STANDARD = ["bedroom", "kitchen", "bathroom", "living_room", "balcony"]
FURNISHED = {
    "bedroom": [("bed_01", "bed"), ("wardrobe_01", "wardrobe")],
    "kitchen": [
        ("stove_01", "stove"),
        ("refrigerator_01", "refrigerator"),
        ("sink_01", "sink"),
        ("kitchen_table_01", "table"),
    ],
    "bathroom": [("shower_01", "shower"), ("toilet_01", "toilet")],
    "living_room": [("sofa_01", "sofa"), ("television_01", "television")],
    "balcony": [("planter_01", "garden_planter")],
}


def _polygon(rect: Rect) -> ShapelyPolygon:
    return ShapelyPolygon(
        [(rect.x, rect.y), (rect.max_x, rect.y), (rect.max_x, rect.max_y), (rect.x, rect.max_y)]
    )


def _portals(walls: list, rects: dict[str, Rect], region_id: str) -> list[Point2D]:
    points = []
    for wall in walls:
        if region_id not in (wall.region_a_id, wall.region_b_id):
            continue
        center_x, center_y = rects[region_id].center
        if wall.vertical:
            shift = -0.4 if center_x < wall.x else 0.4
            points.append(Point2D(x=wall.x + shift, y=wall.y))
        else:
            shift = -0.4 if center_y < wall.y else 0.4
            points.append(Point2D(x=wall.x, y=wall.y + shift))
    return points


def test_layout_tiles_the_footprint_without_gaps_or_overlaps() -> None:
    """The old layout was one row of identical squares; this has to be a real 2D tiling."""
    rects = layout_rooms(STANDARD)
    assert set(rects) == set(STANDARD)

    polygons = [_polygon(rect) for rect in rects.values()]
    for index, left in enumerate(polygons):
        for right in polygons[index + 1 :]:
            assert left.intersection(right).area < 1e-6
    total = sum(polygon.area for polygon in polygons)
    hull_x = max(rect.max_x for rect in rects.values())
    hull_y = max(rect.max_y for rect in rects.values())
    assert total == hull_x * hull_y or abs(total - hull_x * hull_y) < 1e-6

    # Not a single row: rooms must occupy more than one band on both axes.
    assert len({round(rect.y, 3) for rect in rects.values()}) > 1
    assert len({round(rect.x, 3) for rect in rects.values()}) > 1


def test_rooms_get_their_own_size_instead_of_one_shared_square() -> None:
    rects = layout_rooms(STANDARD)
    areas = {name: rect.width * rect.height for name, rect in rects.items()}
    assert areas["living_room"] > areas["bedroom"] > areas["kitchen"] > areas["bathroom"]
    for name, rect in rects.items():
        aspect = max(rect.width, rect.height) / min(rect.width, rect.height)
        assert aspect < 2.0, f"{name} came out as a corridor: {aspect:.2f}"


def test_doors_follow_shared_walls_and_keep_the_plan_connected() -> None:
    rects = layout_rooms(STANDARD)
    walls = select_doors(STANDARD, rects, shared_walls(rects, minimum_overlap=1.2))

    adjacency: dict[str, set[str]] = {region_id: set() for region_id in STANDARD}
    for wall in walls:
        adjacency[wall.region_a_id].add(wall.region_b_id)
        adjacency[wall.region_b_id].add(wall.region_a_id)
    seen, stack = set(), [STANDARD[0]]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency[current] - seen)
    assert seen == set(STANDARD), "path planning fails outright on a disconnected plan"

    # Private rooms stay leaves: a bathroom with two doors is a corridor no bed or shower fits.
    assert len(adjacency["bathroom"]) == 1
    assert len(adjacency["balcony"]) == 1
    # And the balcony must not be reachable only through the bathroom.
    assert adjacency["balcony"] != {"bathroom"}


def test_furniture_is_placed_against_walls_and_leaves_the_room_navigable() -> None:
    rects = layout_rooms(STANDARD)
    walls = select_doors(STANDARD, rects, shared_walls(rects, minimum_overlap=1.2))
    clearance = 0.27

    total_placed = 0
    for region_id, entities in FURNISHED.items():
        rect = rects[region_id]
        doors = _portals(walls, rects, region_id)
        placed = place_furniture(rect, entities, doors, body_radius=clearance, doorway_width=1.0)
        total_placed += len(placed)

        footprints = [_polygon(item.footprint) for item in placed]
        for index, left in enumerate(footprints):
            assert _polygon(rect).covers(left), "furniture must stay inside its room"
            for right in footprints[index + 1 :]:
                assert left.intersection(right).area < 1e-6, "obstacles must not overlap"

        free = _polygon(rect).buffer(-clearance, join_style="mitre")
        for footprint in footprints:
            free = free.difference(footprint.buffer(clearance, join_style="mitre"))
        parts = list(getattr(free, "geoms", [])) or [free]
        probes = [ShapelyPoint(door.x, door.y) for door in doors]
        probes.extend(ShapelyPoint(item.approach.x, item.approach.y) for item in placed)
        assert any(all(part.covers(point) for point in probes) for part in parts), (
            f"{region_id} was sealed off by its own furniture"
        )

    assert total_placed >= 9


def test_navigable_point_avoids_the_furniture_it_used_to_land_in() -> None:
    room = Rect(0.0, 0.0, 4.0, 4.0)
    doors = [Point2D(x=0.4, y=2.0)]
    placed = place_furniture(
        room,
        [("sofa_01", "sofa"), ("table_01", "table")],
        doors,
        body_radius=0.27,
        doorway_width=1.0,
    )
    assert placed
    point = navigable_point(room, placed, body_radius=0.27)
    for item in placed:
        assert not _polygon(item.footprint).buffer(0.27).covers(ShapelyPoint(point.x, point.y))


def test_layout_is_deterministic_and_order_independent() -> None:
    assert layout_rooms(STANDARD) == layout_rooms(STANDARD)
    assert layout_rooms(STANDARD) == layout_rooms(list(reversed(STANDARD)))


def test_connect_all_bridges_a_room_the_walls_left_isolated() -> None:
    rects = {
        "kitchen": Rect(0.0, 0.0, 3.0, 3.0),
        "living_room": Rect(3.0, 0.0, 3.0, 3.0),
        "storage": Rect(20.0, 20.0, 2.0, 2.0),
    }
    walls = shared_walls(rects, minimum_overlap=1.0)
    assert all("storage" not in (item.region_a_id, item.region_b_id) for item in walls)
    repaired = connect_all(list(rects), rects, walls)
    assert any("storage" in (item.region_a_id, item.region_b_id) for item in repaired)
