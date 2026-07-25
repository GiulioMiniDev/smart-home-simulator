"""Deterministic apartment floor plans: room tiling, doorways on shared walls, furniture footprints.

The previous layout put every room in a single horizontal row of identical 6x6 squares
(`_rectangle(index * room_width, 0, ...)`) and wired the doors sequentially, so the resident had
to walk through the bathroom to get from the kitchen to the living room. Furniture had no physical
extent at all: an entity was a bare interaction point, `HomeModel.obstacles` was never populated by
anything, and the obstacle-aware visibility planner in `environment/navigation.py` therefore always
ran against an empty box. Straight-line paths through the bed and the sofa were the norm.

This module produces instead:

- a compact 2D tiling by recursive area-weighted bisection, with per-room-kind target areas, so a
  bathroom is not the size of a living room and the plan is a block rather than a corridor;
- doorways derived from the walls rooms *actually* share, plus a connectivity repair pass, because
  the navigation graph must stay connected for path planning to succeed;
- furniture footprints placed along the walls and published as `HomeObstacle`, with each entity's
  interaction point pushed into free space in front of it.

Everything is a pure function of the room list and the policy, so the same inputs always give the
same plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from smart_home_sim.domain.environment import Point2D, Polygon2D

# Target floor area and preferred aspect (width : height) per known room kind. Unknown rooms fall
# back to _DEFAULT_PROFILE, so the generator stays generic for arbitrary scenario locations.
# Sized so the standard resource set actually fits with walking room around it: at the previous
# areas a bathroom could not hold a washing machine next to a shower without sealing itself off,
# and the placer (correctly) refused the piece.
_ROOM_PROFILES: dict[str, tuple[float, float]] = {
    "living_room": (26.0, 1.20),
    "bedroom": (19.5, 1.15),
    "second_bedroom": (14.0, 1.15),
    "kitchen": (18.0, 1.10),
    "dining_room": (14.0, 1.15),
    "study": (11.0, 1.10),
    "hallway": (8.0, 2.60),
    "corridor": (7.0, 3.00),
    "bathroom": (8.5, 1.25),
    "second_bathroom": (5.0, 1.10),
    "balcony": (6.0, 2.60),
    "terrace": (9.5, 2.20),
    "storage": (4.5, 1.00),
    "laundry_room": (5.5, 1.10),
}
_DEFAULT_PROFILE = (12.0, 1.15)
# Rooms that read as appendages of the flat and belong on its edge rather than in the middle.
_EDGE_ROOMS = frozenset({"balcony", "terrace", "storage"})
# Rooms that in a real flat open onto exactly one other space.
_SINGLE_DOOR_ROOMS = frozenset(
    {"bathroom", "second_bathroom", "balcony", "terrace", "storage", "laundry_room"}
)
# Spaces a flat circulates through, which legitimately carry more than one door.
_CIRCULATION_ROOMS = frozenset({"hallway", "corridor", "living_room", "kitchen"})
# The home validator tests clearance with `covers`, which accepts a point lying exactly on the
# boundary; accepting at the same radius therefore emits points it then rejects. Placement clears a
# hair more so its own predicate is strictly the stronger one.
_CLEARANCE_EPSILON = 0.02


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def max_x(self) -> float:
        return self.x + self.width

    @property
    def max_y(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)

    def to_polygon(self) -> Polygon2D:
        return Polygon2D(
            vertices=[
                Point2D(x=round(self.x, 4), y=round(self.y, 4)),
                Point2D(x=round(self.max_x, 4), y=round(self.y, 4)),
                Point2D(x=round(self.max_x, 4), y=round(self.max_y, 4)),
                Point2D(x=round(self.x, 4), y=round(self.max_y, 4)),
            ]
        )


@dataclass(frozen=True)
class SharedWall:
    region_a_id: str
    region_b_id: str
    # Midpoint of the overlapping wall segment, and whether the wall runs vertically.
    x: float
    y: float
    vertical: bool
    overlap_meters: float


def room_area(region_id: str) -> float:
    return _ROOM_PROFILES.get(region_id, _DEFAULT_PROFILE)[0]


def preferred_aspect(region_id: str) -> float:
    """The shape this kind of room wants. A balcony is meant to be a strip; a bedroom is not."""
    return _ROOM_PROFILES.get(region_id, _DEFAULT_PROFILE)[1]


def layout_rooms(region_ids: list[str]) -> dict[str, Rect]:
    """Tile the flat's footprint over the rooms by recursive area-weighted bisection.

    Bisection guarantees a gap-free, overlap-free tiling of rectangles whose areas track the target
    profile, and always splits the *longer* side so rooms stay reasonably square instead of
    degenerating into the slivers a naive slice-and-dice produces.
    """
    if not region_ids:
        return {}
    ordered = _order_for_layout(region_ids)
    total_area = sum(room_area(region_id) for region_id in ordered)

    # The outer footprint's own proportions decide how square the rooms can come out, and a single
    # fixed guess leaves a big room as a corridor a bed will not fit into. Sweep candidate outer
    # aspects and keep the plan whose rooms sit closest to their preferred shape.
    best: dict[str, Rect] | None = None
    best_score: float | None = None
    for step in range(9):
        outer_aspect = 0.9 + step * 0.15
        height = (total_area / outer_aspect) ** 0.5
        placed: dict[str, Rect] = {}
        _bisect(ordered, Rect(0.0, 0.0, total_area / height, height), placed)
        score = max(
            _aspect(rect) / _ROOM_PROFILES.get(region_id, _DEFAULT_PROFILE)[1]
            for region_id, rect in placed.items()
        )
        # A plan where the only way into the balcony is through the bathroom is geometrically fine
        # and architecturally absurd. Door selection cannot repair it — connectivity forces its
        # hand — so the layout has to avoid creating it.
        score += 10.0 * _stranded_private_rooms(placed)
        if best_score is None or score < best_score:
            best, best_score = placed, score
    assert best is not None
    return best


def _stranded_private_rooms(placed: dict[str, Rect]) -> int:
    """Count private rooms that touch no circulation space at all.

    Such a room can only be entered through another private one — the balcony you reach through
    the bathroom. Door selection cannot fix it, because connectivity leaves it no other edge to
    pick, so the layout is where it has to be avoided.
    """
    private = [region_id for region_id in placed if region_id in _SINGLE_DOOR_ROOMS]
    circulation = {region_id for region_id in placed if region_id in _CIRCULATION_ROOMS}
    if not private or not circulation:
        return 0
    neighbours: dict[str, set[str]] = {region_id: set() for region_id in placed}
    for wall in shared_walls(placed, minimum_overlap=0.9):
        neighbours[wall.region_a_id].add(wall.region_b_id)
        neighbours[wall.region_b_id].add(wall.region_a_id)
    return sum(1 for region_id in private if not neighbours[region_id] & circulation)


def _order_for_layout(region_ids: list[str]) -> list[str]:
    """Largest rooms first so bisection settles the core of the flat before its appendages, with
    edge rooms (balcony, storage) pushed to the end so they land against the perimeter."""
    return sorted(
        region_ids,
        key=lambda region_id: (
            region_id in _EDGE_ROOMS,
            -room_area(region_id),
            region_id,
        ),
    )


def _bisect(region_ids: list[str], rect: Rect, placed: dict[str, Rect]) -> None:
    if len(region_ids) == 1:
        placed[region_ids[0]] = rect
        return
    areas = [room_area(region_id) for region_id in region_ids]
    total = sum(areas)
    # Split the list where the cumulative area is closest to half: both halves stay compact.
    best_index, best_gap, running = 1, None, 0.0
    for index in range(len(region_ids) - 1):
        running += areas[index]
        gap = abs(running - total / 2)
        if best_gap is None or gap < best_gap:
            best_index, best_gap = index + 1, gap
    head, tail = region_ids[:best_index], region_ids[best_index:]
    head_share = sum(areas[:best_index]) / total

    # Cutting the longer side unconditionally is what turns a large room into a corridor: the slice
    # handed to a leaf fixes its shape for good. Score both directions by the worst aspect ratio
    # they produce and take the squarer one.
    vertical = Rect(rect.x, rect.y, rect.width * head_share, rect.height)
    horizontal = Rect(rect.x, rect.y, rect.width, rect.height * head_share)
    vertical_score = max(
        _aspect(vertical),
        _aspect(Rect(0, 0, rect.width * (1 - head_share), rect.height)),
    )
    horizontal_score = max(
        _aspect(horizontal),
        _aspect(Rect(0, 0, rect.width, rect.height * (1 - head_share))),
    )

    if vertical_score <= horizontal_score:
        cut = rect.width * head_share
        _bisect(head, Rect(rect.x, rect.y, cut, rect.height), placed)
        _bisect(tail, Rect(rect.x + cut, rect.y, rect.width - cut, rect.height), placed)
    else:
        cut = rect.height * head_share
        _bisect(head, Rect(rect.x, rect.y, rect.width, cut), placed)
        _bisect(tail, Rect(rect.x, rect.y + cut, rect.width, rect.height - cut), placed)


def _aspect(rect: Rect) -> float:
    if rect.width <= 0 or rect.height <= 0:
        return float("inf")
    return max(rect.width, rect.height) / min(rect.width, rect.height)


def shared_walls(rects: dict[str, Rect], *, minimum_overlap: float) -> list[SharedWall]:
    """Find every pair of rooms that share enough wall to hold a door.

    Bisection tiles the footprint exactly, so neighbours touch on a common edge; this recovers those
    contacts to place doors where an architect would, instead of chaining rooms in list order.
    """
    walls: list[SharedWall] = []
    for left_id, left in sorted(rects.items()):
        for right_id, right in sorted(rects.items()):
            if left_id >= right_id:
                continue
            # Vertical contact: left's right edge against right's left edge (or the reverse).
            for a, b in ((left, right), (right, left)):
                if abs(a.max_x - b.x) > 1e-6:
                    continue
                low, high = max(a.y, b.y), min(a.max_y, b.max_y)
                if high - low >= minimum_overlap:
                    walls.append(
                        SharedWall(left_id, right_id, a.max_x, (low + high) / 2, True, high - low)
                    )
            for a, b in ((left, right), (right, left)):
                if abs(a.max_y - b.y) > 1e-6:
                    continue
                low, high = max(a.x, b.x), min(a.max_x, b.max_x)
                if high - low >= minimum_overlap:
                    walls.append(
                        SharedWall(left_id, right_id, (low + high) / 2, a.max_y, False, high - low)
                    )
    return walls


def select_doors(
    region_ids: list[str], rects: dict[str, Rect], walls: list[SharedWall]
) -> list[SharedWall]:
    """Choose the doorways: a maximum spanning tree over the shared walls, plus circulation links.

    Opening a door on every shared wall gives private rooms three and four of them, which is both
    architecturally wrong and unusable: a bedroom with doors at each end is a corridor, and no bed
    fits across it without sealing the room (`place_furniture` then rightly refuses the piece).

    A spanning tree gives exactly the doors connectivity requires and leaves private rooms as leaves
    with a single door. Edges are ranked so wide walls and circulation spaces win, and extra doors
    are then added back only between circulation rooms, where a real flat does have more than one.
    """
    ranked = sorted(
        walls,
        key=lambda wall: (-_door_priority(wall), wall.region_a_id, wall.region_b_id),
    )
    parent = {region_id: region_id for region_id in region_ids}

    def find(region_id: str) -> str:
        while parent[region_id] != region_id:
            parent[region_id] = parent[parent[region_id]]
            region_id = parent[region_id]
        return region_id

    chosen: list[SharedWall] = []
    for wall in ranked:
        left, right = find(wall.region_a_id), find(wall.region_b_id)
        if left == right:
            continue
        parent[left] = right
        chosen.append(wall)

    used = {(wall.region_a_id, wall.region_b_id) for wall in chosen}
    for wall in ranked:
        pair = (wall.region_a_id, wall.region_b_id)
        if pair in used:
            continue
        if wall.region_a_id in _CIRCULATION_ROOMS and wall.region_b_id in _CIRCULATION_ROOMS:
            chosen.append(wall)
            used.add(pair)
    return connect_all(region_ids, rects, chosen)


def _door_priority(wall: SharedWall) -> float:
    """Prefer wide walls, and walls that touch a circulation space over private-to-private ones."""
    score = wall.overlap_meters
    for region_id in (wall.region_a_id, wall.region_b_id):
        if region_id in _CIRCULATION_ROOMS:
            score += 4.0
        if region_id in _SINGLE_DOOR_ROOMS:
            score -= 1.5
    # A door straight from the bathroom onto the balcony is worse than a longer way round.
    if wall.region_a_id in _SINGLE_DOOR_ROOMS and wall.region_b_id in _SINGLE_DOOR_ROOMS:
        score -= 6.0
    return score


def prune_implausible_doors(walls: list[SharedWall]) -> list[SharedWall]:
    """Keep at most one doorway for rooms that only ever have one in a real flat.

    Bisection happily leaves a bathroom touching three neighbours; opening a door on each of them
    gives a plan no architect would draw (a balcony reachable through the bathroom). Each such room
    keeps only its widest contact, and `connect_all` repairs anything this isolates.
    """
    limited = {
        region_id
        for wall in walls
        for region_id in (wall.region_a_id, wall.region_b_id)
        if region_id in _SINGLE_DOOR_ROOMS
    }
    dropped: set[int] = set()
    for region_id in sorted(limited):
        touching = [
            index
            for index, wall in enumerate(walls)
            if region_id in (wall.region_a_id, wall.region_b_id) and index not in dropped
        ]
        if len(touching) <= 1:
            continue

        def neighbour_of(index: int, room: str = region_id) -> str:
            wall = walls[index]
            return wall.region_b_id if wall.region_a_id == room else wall.region_a_id

        # Rank circulation neighbours above other single-door rooms first, widest contact second.
        # Without the first key a bathroom and a balcony happily pick each other and strand
        # themselves as an island the connectivity repair then has to bridge with a fake door.
        best = max(
            touching,
            key=lambda index: (
                neighbour_of(index) not in _SINGLE_DOOR_ROOMS,
                walls[index].overlap_meters,
                -index,
            ),
        )
        dropped.update(index for index in touching if index != best)
    return [wall for index, wall in enumerate(walls) if index not in dropped]


def connect_all(
    region_ids: list[str], rects: dict[str, Rect], walls: list[SharedWall]
) -> list[SharedWall]:
    """Keep a spanning set of doorways and repair any region the wall contacts left isolated.

    Path planning fails outright on a disconnected navigation graph, so connectivity is a hard
    requirement rather than a nicety: any room bisection left without a usable contact is linked to
    its nearest already-connected neighbour.
    """
    kept = list(walls)
    reachable: set[str] = set()
    adjacency: dict[str, set[str]] = {region_id: set() for region_id in region_ids}
    for wall in kept:
        adjacency[wall.region_a_id].add(wall.region_b_id)
        adjacency[wall.region_b_id].add(wall.region_a_id)

    stack = [region_ids[0]]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(sorted(adjacency[current] - reachable))

    for region_id in region_ids:
        if region_id in reachable:
            continue
        anchor = min(
            reachable,
            key=lambda other: _centre_distance(rects[region_id], rects[other]),
        )
        left, right = sorted((region_id, anchor))
        midpoint_x = (rects[left].center[0] + rects[right].center[0]) / 2
        midpoint_y = (rects[left].center[1] + rects[right].center[1]) / 2
        kept.append(SharedWall(left, right, midpoint_x, midpoint_y, True, 0.0))
        reachable.add(region_id)
    return kept


def _centre_distance(left: Rect, right: Rect) -> float:
    return (left.center[0] - right.center[0]) ** 2 + (left.center[1] - right.center[1]) ** 2


# Footprint per entity type as (extent along the wall, depth from the wall), in metres.
_FURNITURE_FOOTPRINTS: dict[str, tuple[float, float]] = {
    "bed": (1.60, 2.00),
    "wardrobe": (1.20, 0.60),
    "sofa": (2.00, 0.85),
    "television": (1.10, 0.35),
    "radio": (0.35, 0.25),
    "table": (1.20, 0.80),
    "chair": (0.45, 0.45),
    "stove": (0.60, 0.60),
    "refrigerator": (0.70, 0.70),
    "sink": (0.60, 0.55),
    "washbasin": (0.60, 0.45),
    "storage_cabinet": (0.80, 0.40),
    "moka_coffee_maker": (0.20, 0.20),
    "shower": (0.80, 0.80),
    "toilet": (0.45, 0.70),
    "washing_machine": (0.60, 0.55),
    "garden_planter": (0.50, 0.40),
}
_DEFAULT_FOOTPRINT = (0.60, 0.50)


@dataclass(frozen=True)
class PlacedFurniture:
    entity_id: str
    footprint: Rect
    # Where the resident stands to use it: in front of the piece, inside navigable space.
    approach: Point2D


def footprint_for(entity_type: str) -> tuple[float, float]:
    return _FURNITURE_FOOTPRINTS.get(entity_type, _DEFAULT_FOOTPRINT)


def place_furniture(
    room: Rect,
    entities: list[tuple[str, str]],
    door_positions: list[Point2D],
    *,
    body_radius: float,
    doorway_width: float,
) -> list[PlacedFurniture]:
    """Lay furniture flush against the room's walls, leaving doorways and a walkway clear.

    Placement walks the perimeter (bottom, right, top, left) and skips any span that would block a
    door. A piece is only accepted if, once its footprint is added, the room still has one connected
    navigable region that covers every door portal and every approach point placed so far — the
    exact predicate `environment/navigation.py` will later apply. Anything that fails is dropped, so
    the generator can never emit a home the path planner cannot route through.
    """
    from shapely.geometry import Point as ShapelyPoint
    from shapely.geometry import Polygon as ShapelyPolygon

    def rect_polygon(rect: Rect) -> ShapelyPolygon:
        return ShapelyPolygon(
            [
                (rect.x, rect.y),
                (rect.max_x, rect.y),
                (rect.max_x, rect.max_y),
                (rect.x, rect.max_y),
            ]
        )

    clearance = body_radius + _CLEARANCE_EPSILON
    shell = rect_polygon(room)
    walkable = shell.buffer(-clearance, join_style="mitre")
    if walkable.is_empty or walkable.geom_type != "Polygon":
        return []

    # Keep-clear discs in front of each door, so furniture never seals a room shut.
    door_clearance = doorway_width / 2 + clearance
    required = [ShapelyPoint(item.x, item.y) for item in door_positions]
    blocked = [point.buffer(door_clearance) for point in required]

    placed: list[PlacedFurniture] = []
    accepted: list[ShapelyPolygon] = []
    margin = clearance + 0.10

    # (origin, along-wall unit vector, inward unit vector, wall length)
    walls = (
        ((room.x, room.y), (1.0, 0.0), (0.0, 1.0), room.width),
        ((room.max_x, room.y), (0.0, 1.0), (-1.0, 0.0), room.height),
        ((room.max_x, room.max_y), (-1.0, 0.0), (0.0, -1.0), room.width),
        ((room.x, room.max_y), (0.0, -1.0), (1.0, 0.0), room.height),
    )
    # One cursor per wall: resetting to zero on every wrap re-proposes spans already taken and
    # burns the attempt budget re-colliding with furniture that is standing there.
    cursors = [0.0] * len(walls)
    wall_index = 0
    for entity_id, entity_type in entities:
        extent, depth = footprint_for(entity_type)
        # Give each piece several shots around the perimeter: a rejection means "not here", not
        # "nowhere", and dropping the item on the first clash is what emptied whole rooms.
        settled = False
        for _ in range(4 * len(walls)):
            if settled:
                break
            origin, along, inward, length = walls[wall_index]
            cursor = cursors[wall_index]
            # A piece can stand either way round against a wall, which is what lets a bed fit a
            # narrow bedroom lengthwise instead of being dropped for want of 20 cm.
            for span, thickness in _orientations(extent, depth):
                if cursor + span > length or thickness + margin >= _wall_depth(room, inward):
                    continue
                start_x = origin[0] + along[0] * cursor
                start_y = origin[1] + along[1] * cursor
                end_x = start_x + along[0] * span + inward[0] * thickness
                end_y = start_y + along[1] * span + inward[1] * thickness
                candidate = Rect(
                    min(start_x, end_x),
                    min(start_y, end_y),
                    abs(end_x - start_x) or thickness,
                    abs(end_y - start_y) or thickness,
                )
                middle = cursor + span / 2
                approach = Point2D(
                    x=round(origin[0] + along[0] * middle + inward[0] * (thickness + margin), 4),
                    y=round(origin[1] + along[1] * middle + inward[1] * (thickness + margin), 4),
                )

                polygon = rect_polygon(candidate)
                if any(polygon.intersects(zone) for zone in blocked):
                    continue
                # Two pieces on perpendicular walls meet at the corner unless this is checked, and
                # the home validator rejects a model whose obstacles overlap.
                if any(polygon.buffer(0.01).intersects(item) for item in accepted):
                    continue

                trial = accepted + [polygon]
                free = walkable.difference(
                    _union([item.buffer(clearance, join_style="mitre") for item in trial])
                )
                probes = [*required, ShapelyPoint(approach.x, approach.y)]
                probes.extend(ShapelyPoint(item.approach.x, item.approach.y) for item in placed)
                if not _is_navigable(free, probes):
                    continue

                accepted = trial
                placed.append(PlacedFurniture(entity_id, candidate, approach))
                cursors[wall_index] = cursor + span + 0.10
                settled = True
                break
            if settled:
                break
            cursors[wall_index] = cursor + min(extent, depth) / 2 + 0.10
            if cursors[wall_index] + min(extent, depth) > length:
                cursors[wall_index] = length
            wall_index = (wall_index + 1) % len(walls)
    return placed


def free_fallback_points(
    room: Rect, placed: list[PlacedFurniture], *, body_radius: float, count: int
) -> list[Point2D]:
    """Distinct in-room points clear of every footprint, for entities the placer had to refuse.

    Falling back to a naive in-room grid puts the point inside a neighbouring piece of furniture and
    the home validator rejects the whole model, so the fallback has to respect the same free space.
    """
    from shapely.geometry import Point as ShapelyPoint

    free = _room_free_space(room, placed, body_radius)
    if count <= 0 or getattr(free, "is_empty", True):
        return []
    parts = list(getattr(free, "geoms", [])) or [free]
    largest = max(parts, key=lambda part: part.area)
    minimum_x, minimum_y, maximum_x, maximum_y = largest.bounds

    found: list[Point2D] = []
    steps = 4
    while steps <= 32 and len(found) < count:
        found = []
        for row in range(1, steps + 1):
            for column in range(1, steps + 1):
                x = minimum_x + (maximum_x - minimum_x) * column / (steps + 1)
                y = minimum_y + (maximum_y - minimum_y) * row / (steps + 1)
                if largest.covers(ShapelyPoint(x, y)):
                    found.append(Point2D(x=round(x, 4), y=round(y, 4)))
                if len(found) >= count:
                    break
            if len(found) >= count:
                break
        steps *= 2
    if not found:
        point = largest.representative_point()
        found = [Point2D(x=round(float(point.x), 4), y=round(float(point.y), 4))]
    return (found * count)[:count]


def _room_free_space(room: Rect, placed: list[PlacedFurniture], body_radius: float) -> object:
    from shapely.geometry import Polygon as ShapelyPolygon

    def rect_polygon(rect: Rect) -> ShapelyPolygon:
        return ShapelyPolygon(
            [
                (rect.x, rect.y),
                (rect.max_x, rect.y),
                (rect.max_x, rect.max_y),
                (rect.x, rect.max_y),
            ]
        )

    clearance = body_radius + _CLEARANCE_EPSILON
    free = rect_polygon(room).buffer(-clearance, join_style="mitre")
    if placed:
        free = free.difference(
            _union(
                [
                    rect_polygon(item.footprint).buffer(clearance, join_style="mitre")
                    for item in placed
                ]
            )
        )
    return free


def navigable_point(room: Rect, placed: list[PlacedFurniture], *, body_radius: float) -> Point2D:
    """A point guaranteed to sit in the room's free space, for region anchors and service entities.

    Those used to be the room centre, which was safe only while rooms were empty boxes; with real
    footprints the centre can fall inside the sofa and the home validator rejects the model.
    """
    centre = Point2D(x=round(room.center[0], 4), y=round(room.center[1], 4))
    free = _room_free_space(room, placed, body_radius)
    if getattr(free, "is_empty", True):
        return centre
    parts = list(getattr(free, "geoms", [])) or [free]
    largest = max(parts, key=lambda part: part.area)
    point = largest.representative_point()
    return Point2D(x=round(float(point.x), 4), y=round(float(point.y), 4))


def _orientations(extent: float, depth: float) -> tuple[tuple[float, float], ...]:
    if abs(extent - depth) < 1e-9:
        return ((extent, depth),)
    return ((extent, depth), (depth, extent))


def _wall_depth(room: Rect, inward: tuple[float, float]) -> float:
    return room.height if inward[1] else room.width


def _union(polygons: list) -> object:
    from shapely.ops import unary_union

    return unary_union(polygons)


def _is_navigable(free: object, probes: list) -> bool:
    """Every probe must sit in one and the same connected component of the free space."""
    if getattr(free, "is_empty", True):
        return False
    parts = list(getattr(free, "geoms", [])) or [free]
    return any(all(part.covers(point) for point in probes) for part in parts)


__all__ = [
    "Rect",
    "SharedWall",
    "PlacedFurniture",
    "connect_all",
    "footprint_for",
    "free_fallback_points",
    "navigable_point",
    "place_furniture",
    "prune_implausible_doors",
    "select_doors",
    "layout_rooms",
    "preferred_aspect",
    "room_area",
    "shared_walls",
]
