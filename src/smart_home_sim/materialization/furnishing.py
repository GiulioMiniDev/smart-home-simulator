"""Furnishing a room the way a room is furnished, instead of walking its perimeter.

The previous placer (`floorplan.place_furniture`) walked the four walls in order — bottom, right,
top, left — pushing each piece flush against the first span that happened to be free. It produced
plans that were geometrically valid and architecturally absurd: every object stood with its back to
a wall, the middle of every room was a void, the television faced a blank wall while the sofa faced
another one, and the four kitchen chairs stood in a row along the skirting board with the table two
metres away against the opposite wall. Nothing was *arranged*; things were merely stored.

What a room actually has is a small number of **arrangements**, each of which is a piece and the
things that belong with it:

- a bed against the wall furthest from the door, with a nightstand on whichever side has room;
- a sofa with a coffee table in front of it and the television on the surface the sofa looks at;
- a dining table standing in open floor with its chairs around it, not against a wall;
- a kitchen whose sink, hob and worktop form one continuous run, with the fridge closing it.

So this module places by *pose* rather than by cursor. Each piece proposes candidate poses — along
every wall at a fine step, out in the open floor on a grid, or at an exact offset from a piece
already standing — every pose is scored for the things that make a layout read as designed, and the
best pose that survives the hard checks wins.

The hard checks are the ones the rest of the system depends on and are unchanged in substance: a
piece may not leave its room, overlap another piece, block a doorway, or break the room's free space
into more than one component. `environment/navigation.py` routes through exactly the free space
computed here, so a layout this module accepts is a layout the path planner can walk.

Everything is a pure function of the room, the pieces, the doorways and the seed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random
from typing import TYPE_CHECKING, Any

from smart_home_sim.domain.environment import Point2D

if TYPE_CHECKING:  # pragma: no cover - typing only
    from smart_home_sim.materialization.floorplan import PlacedFurniture, Rect

# The home validator tests clearance with `covers`, which accepts a point exactly on the boundary;
# placing at the same radius therefore emits points it then rejects. Placement clears a hair more so
# its own predicate is strictly the stronger one.
CLEARANCE_EPSILON = 0.02
# Gap kept between two pieces that are not deliberately part of the same fitted run. Obstacles that
# merely touch are rejected by the home validator as overlapping, and two objects sharing an edge
# read as one object on the plan.
_PIECE_GAP = 0.03
# How finely a wall is sampled for candidate positions. Ten centimetres is below what reads as a
# difference on a plan and keeps the candidate count per wall in the tens, not the hundreds.
_WALL_STEP = 0.10
# How finely open floor is sampled for a piece that stands away from the walls.
_ISLAND_STEP = 0.25
# Poses that survive scoring and are then put through the expensive free-space test, best first. A
# piece that fits in none of its twenty best poses is a piece this room has no room for.
_HARD_CHECK_BUDGET = 24
# How far apart two candidate poses have to be to count as different attempts.
_POSE_SEPARATION = 0.45
# How many of the best-scoring poses are tried before that rule starts applying.
_KEEP_BEST = 8
# Attempts allowed on the final pass, where the only question left is whether the piece fits at all.
_LAST_RESORT_BUDGET = 240
# How far in front of a piece its interaction point sits, beyond the body radius the caller passes.
_APPROACH_GAP = 0.10
# How far inside the free space a last-resort standing point is pulled, so it is inside it rather
# than on its edge.
_FALLBACK_INSET = 0.03
# Fractions of a piece's stated clearance, tried in turn until it fits somewhere.
_CLEARANCE_RELAXATIONS = (1.0, 0.6, 0.3, 0.0)


@dataclass(frozen=True)
class FurnitureSpec:
    """What a kind of furniture is, dimensionally and socially.

    `extent` is the piece's own width — the span it occupies along the wall it stands against — and
    `depth` is front-to-back. A wardrobe is 1.20 wide and 0.60 deep whichever way round the room it
    faces; the pose decides how that maps onto x and y.
    """

    extent: float
    depth: float
    # Where this kind of thing stands: against a wall, tucked into a corner, or out in the floor.
    placement: str = "wall"
    # Floor a body needs in front of the piece to use it: a wardrobe needs its doors to open, a
    # dining chair needs to be pulled out. Kept clear of other furniture, which is most of what
    # stops the placer parking the coffee table hard against the front of the sofa.
    clearance: float = 0.55
    # Which arrangement the piece belongs to. Same-group pieces attract each other; that is what
    # makes a kitchen a run and a sitting area a sitting area.
    group: str = "misc"
    # Part of a continuous fitted run with its group-mates — worktops, not free-standing objects.
    run: bool = False
    # May stand with its long axis running into the room rather than along the wall. A
    # bed may — that is how a bed fits a narrow room — and a wardrobe may not, because
    # its doors would then open into a wall.
    rotatable: bool = False


# Footprints for the types that already existed are carried over unchanged: they were measured
# against the standard resource set and the room profiles are sized for them.
_SPECS: dict[str, FurnitureSpec] = {
    # Sleeping.
    "bed": FurnitureSpec(1.60, 2.00, clearance=0.60, group="sleep", rotatable=True),
    "single_bed": FurnitureSpec(0.90, 2.00, clearance=0.55, group="sleep", rotatable=True),
    "nightstand": FurnitureSpec(0.45, 0.40, clearance=0.35, group="sleep"),
    "wardrobe": FurnitureSpec(1.20, 0.60, clearance=0.75, group="store"),
    "chest_of_drawers": FurnitureSpec(0.90, 0.50, clearance=0.70, group="store"),
    # Sitting.
    "sofa": FurnitureSpec(2.00, 0.85, clearance=0.70, group="lounge"),
    "armchair": FurnitureSpec(0.80, 0.80, placement="free", clearance=0.55, group="lounge"),
    "coffee_table": FurnitureSpec(1.00, 0.55, placement="free", clearance=0.40, group="lounge"),
    "television": FurnitureSpec(1.10, 0.35, clearance=0.30, group="lounge"),
    "tv_stand": FurnitureSpec(1.20, 0.42, clearance=0.35, group="lounge"),
    "radio": FurnitureSpec(0.35, 0.25, clearance=0.25, group="lounge"),
    "bookshelf": FurnitureSpec(0.90, 0.32, clearance=0.60, group="store"),
    "storage_cabinet": FurnitureSpec(0.80, 0.40, clearance=0.60, group="store"),
    "sideboard": FurnitureSpec(1.40, 0.45, clearance=0.60, group="store"),
    "floor_lamp": FurnitureSpec(0.35, 0.35, placement="corner", clearance=0.20, group="decor"),
    "houseplant": FurnitureSpec(0.40, 0.40, placement="corner", clearance=0.20, group="decor"),
    # Eating and working.
    "table": FurnitureSpec(
        1.20, 0.80, placement="island", clearance=0.75, group="dine", rotatable=True
    ),
    "chair": FurnitureSpec(0.45, 0.45, placement="free", clearance=0.45, group="dine"),
    "stool": FurnitureSpec(0.38, 0.38, placement="free", clearance=0.40, group="dine"),
    "bench": FurnitureSpec(1.20, 0.40, clearance=0.45, group="dine"),
    "desk": FurnitureSpec(1.30, 0.65, clearance=0.80, group="work"),
    # Cooking. The fitted run is what makes a kitchen legible from above.
    "kitchen_counter": FurnitureSpec(1.20, 0.62, clearance=0.90, group="cook", run=True),
    "sink": FurnitureSpec(0.60, 0.55, clearance=0.90, group="cook", run=True),
    "stove": FurnitureSpec(0.60, 0.60, clearance=0.90, group="cook", run=True),
    "oven": FurnitureSpec(0.60, 0.60, clearance=0.90, group="cook", run=True),
    "dishwasher": FurnitureSpec(0.60, 0.60, clearance=0.90, group="cook", run=True),
    "refrigerator": FurnitureSpec(0.70, 0.70, clearance=0.90, group="cook", run=True),
    "microwave": FurnitureSpec(0.50, 0.38, clearance=0.30, group="cook"),
    "kettle": FurnitureSpec(0.22, 0.22, clearance=0.25, group="cook"),
    "coffee_machine": FurnitureSpec(0.30, 0.30, clearance=0.25, group="cook"),
    "moka_coffee_maker": FurnitureSpec(0.20, 0.20, clearance=0.25, group="cook"),
    # Washing.
    "washbasin": FurnitureSpec(0.60, 0.45, clearance=0.70, group="wash", run=True),
    "toilet": FurnitureSpec(0.45, 0.70, clearance=0.65, group="wash", run=True),
    "bidet": FurnitureSpec(0.40, 0.60, clearance=0.60, group="wash", run=True),
    "shower": FurnitureSpec(0.80, 0.80, placement="corner", clearance=0.60, group="wash"),
    "bathtub": FurnitureSpec(1.70, 0.75, placement="corner", clearance=0.65, group="wash"),
    "washing_machine": FurnitureSpec(0.60, 0.55, clearance=0.70, group="laundry"),
    "drying_rack": FurnitureSpec(0.70, 0.55, placement="free", clearance=0.40, group="laundry"),
    "medicine_cabinet": FurnitureSpec(0.45, 0.20, clearance=0.55, group="store"),
    # Halls and outdoor space.
    "shoe_rack": FurnitureSpec(0.70, 0.30, clearance=0.55, group="store"),
    "coat_rack": FurnitureSpec(0.45, 0.35, placement="corner", clearance=0.50, group="store"),
    "mirror": FurnitureSpec(0.60, 0.12, clearance=0.55, group="decor"),
    "garden_planter": FurnitureSpec(0.50, 0.40, placement="corner", clearance=0.35, group="decor"),
    "garden_chair": FurnitureSpec(0.55, 0.55, placement="free", clearance=0.45, group="decor"),
}
_DEFAULT_SPEC = FurnitureSpec(0.60, 0.50)

# A scenario names its own resource types, and it names them the way a person would. The generated
# world says `bedside_table`, an imported one says `night_table`, and neither is a key in the table
# above — so both fell through to the 0.60 x 0.50 default, stood against a wall on their own, and
# were never recognised as the thing that belongs beside the bed. Spelling is not a different piece
# of furniture.
_TYPE_ALIASES: dict[str, str] = {
    "armoire": "wardrobe",
    "bath": "bathtub",
    "bedside_table": "nightstand",
    "bookcase": "bookshelf",
    "book_shelf": "bookshelf",
    "cabinet": "storage_cabinet",
    "coat_stand": "coat_rack",
    "cooker": "stove",
    "couch": "sofa",
    "counter": "kitchen_counter",
    "cupboard": "storage_cabinet",
    "dining_chair": "chair",
    "dining_table": "table",
    "dishwashing_machine": "dishwasher",
    "dresser": "chest_of_drawers",
    "easy_chair": "armchair",
    "electric_kettle": "kettle",
    "freezer": "refrigerator",
    "fridge": "refrigerator",
    "hob": "stove",
    "kitchen_cabinet": "storage_cabinet",
    "kitchen_chair": "chair",
    "kitchen_table": "table",
    "lamp": "floor_lamp",
    "night_table": "nightstand",
    "plant": "houseplant",
    "potted_plant": "houseplant",
    "settee": "sofa",
    "side_table": "coffee_table",
    "study_desk": "desk",
    "tv": "television",
    "wash_basin": "washbasin",
    "washstand": "washbasin",
    "wc": "toilet",
    "worktop": "kitchen_counter",
    "writing_desk": "desk",
}


def canonical_type(entity_type: str) -> str:
    """The catalogue entry a scenario's own spelling refers to."""
    return _TYPE_ALIASES.get(entity_type, entity_type)


# A piece that belongs *with* another one, and how it belongs. The anchor types are tried in order;
# whichever is already standing when the satellite is placed wins. A satellite whose anchor is
# absent (or could not be placed) falls back to the generic poses for its own placement kind, so a
# chair in a room with no table is still a chair against a wall rather than a dropped item.
_SATELLITES: dict[str, tuple[tuple[str, ...], str]] = {
    "nightstand": (("bed", "single_bed"), "flank"),
    "coffee_table": (("sofa",), "front"),
    "television": (("sofa", "armchair", "bed", "single_bed"), "faced_by"),
    "tv_stand": (("sofa", "armchair", "bed", "single_bed"), "faced_by"),
    "armchair": (("coffee_table", "sofa"), "quarter"),
    "chair": (("table", "desk"), "around"),
    "stool": (("kitchen_counter", "table"), "around"),
    "floor_lamp": (("sofa", "armchair", "bed"), "beside"),
}

# Order in which a room is furnished. The big decisions come first, because everything else is
# positioned relative to them: you place the bed and then find somewhere for the nightstand, never
# the other way round. Within a rank ties break on the entity id, so the order is stable.
_GROUP_RANK = {
    "sleep": 0,
    "lounge": 1,
    "cook": 1,
    "wash": 1,
    "dine": 2,
    "work": 2,
    "laundry": 3,
    "misc": 4,
    "store": 4,
    "decor": 5,
}
# A satellite is placed after its anchor whatever their groups say, or there is nothing to sit
# beside. The rank is deliberately below `store` so shelves still get the leftover wall.
_SATELLITE_RANK = 3


def spec_for(entity_type: str) -> FurnitureSpec:
    return _SPECS.get(canonical_type(entity_type), _DEFAULT_SPEC)


def footprint_for(entity_type: str) -> tuple[float, float]:
    spec = spec_for(entity_type)
    return (spec.extent, spec.depth)


Vector = tuple[float, float]
# The four directions a piece can face, in a fixed order so candidate generation is reproducible.
_FACINGS: tuple[Vector, ...] = ((0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0))


@dataclass(frozen=True)
class Pose:
    """A concrete placement: where the piece is, and which way it looks into the room."""

    rect: Rect
    facing: Vector
    score: float = 0.0

    @property
    def centre(self) -> tuple[float, float]:
        return (self.rect.x + self.rect.width / 2, self.rect.y + self.rect.height / 2)

    def approach_options(self, gap: float) -> tuple[tuple[float, float], ...]:
        """Where a body could stand to use this piece, best first.

        In front of it, on its own centre line, is the answer for almost everything. It is not the
        answer for a dining chair, whose front is against the table: taking the front point on faith
        put the resident's standing position inside the table, the free-space test rejected it, and
        every seat round every table was refused — which is why chairs ended up back against the
        walls. A body reaches a chair from behind it, and this says so.
        """
        centre_x, centre_y = self.centre
        forward = self.facing
        side = (-forward[1], forward[0])
        ahead = (abs(forward[0]) * self.rect.width + abs(forward[1]) * self.rect.height) / 2 + gap
        across = (abs(side[0]) * self.rect.width + abs(side[1]) * self.rect.height) / 2 + gap
        return tuple(
            (centre_x + x, centre_y + y)
            for x, y in (
                (forward[0] * ahead, forward[1] * ahead),
                (side[0] * across, side[1] * across),
                (-side[0] * across, -side[1] * across),
                (-forward[0] * ahead, -forward[1] * ahead),
            )
        )


@dataclass
class _Standing:
    """A piece already placed, kept so later pieces can be arranged around it."""

    entity_id: str
    entity_type: str
    spec: FurnitureSpec
    pose: Pose
    # Filled in once the room is finished: see `_assign_approaches`.
    approach: tuple[float, float] = (0.0, 0.0)


def _rect(x: float, y: float, width: float, height: float) -> Rect:
    """A footprint at full precision.

    Rounding here to make the published numbers pretty is what made a piece standing flush against
    the left wall sit four ten-thousandths outside the room the bisection actually computed. The
    contract rounds once, at the boundary, in `Rect.to_polygon`; geometry stays exact until then.
    """
    from smart_home_sim.materialization.floorplan import Rect as RectType

    return RectType(x, y, width, height)


def _pose_at(back_centre: tuple[float, float], facing: Vector, extent: float, depth: float) -> Rect:
    """The footprint of a piece whose back sits at `back_centre` and which looks along `facing`.

    The piece spans `extent` across the facing direction and `depth` along it, so a 1.20 x 0.60
    wardrobe against the south wall is 1.20 wide and 0.60 tall, and the same wardrobe against the
    east wall is 0.60 wide and 1.20 tall, without either dimension being swapped by hand.
    """
    centre_x = back_centre[0] + facing[0] * depth / 2
    centre_y = back_centre[1] + facing[1] * depth / 2
    width = abs(facing[1]) * extent + abs(facing[0]) * depth
    height = abs(facing[0]) * extent + abs(facing[1]) * depth
    return _rect(centre_x - width / 2, centre_y - height / 2, width, height)


_TOLERANCE = 1e-9


def _snap(room: Rect, rect: Rect) -> Rect:
    """Pull a pose that is a rounding error away from a wall onto the wall.

    `_pose_at` reaches a flush position by adding half a depth and subtracting half a height, and
    the two do not always cancel: a wardrobe against the far wall came out four parts in 10^16
    outside the room it was placed in. The published polygon rounds that away, but the free-space
    arithmetic in between does not, and a piece that is outside its room by a rounding error is
    still outside its room.
    """
    x = room.x if abs(rect.x - room.x) < 1e-6 else rect.x
    y = room.y if abs(rect.y - room.y) < 1e-6 else rect.y
    max_x = room.max_x if abs(rect.max_x - room.max_x) < 1e-6 else rect.max_x
    max_y = room.max_y if abs(rect.max_y - room.max_y) < 1e-6 else rect.max_y
    return _rect(x, y, max_x - x, max_y - y)


def _overlaps(left: Rect, right: Rect, *, gap: float = 0.0) -> bool:
    return (
        left.x - gap < right.max_x - _TOLERANCE
        and right.x - gap < left.max_x - _TOLERANCE
        and left.y - gap < right.max_y - _TOLERANCE
        and right.y - gap < left.max_y - _TOLERANCE
    )


def _contains(outer: Rect, inner: Rect) -> bool:
    return (
        inner.x >= outer.x - _TOLERANCE
        and inner.y >= outer.y - _TOLERANCE
        and inner.max_x <= outer.max_x + _TOLERANCE
        and inner.max_y <= outer.max_y + _TOLERANCE
    )


def _clearance_rect(pose: Pose, depth: float) -> Rect:
    """The floor a body needs in front of the piece, as a rectangle of the piece's own width."""
    if pose.facing[1] > 0:
        return _rect(pose.rect.x, pose.rect.max_y, pose.rect.width, depth)
    if pose.facing[1] < 0:
        return _rect(pose.rect.x, pose.rect.y - depth, pose.rect.width, depth)
    if pose.facing[0] > 0:
        return _rect(pose.rect.max_x, pose.rect.y, depth, pose.rect.height)
    return _rect(pose.rect.x - depth, pose.rect.y, depth, pose.rect.height)


def _distance_to_rect(point: tuple[float, float], rect: Rect) -> float:
    dx = max(rect.x - point[0], 0.0, point[0] - rect.max_x)
    dy = max(rect.y - point[1], 0.0, point[1] - rect.max_y)
    return (dx * dx + dy * dy) ** 0.5


def furnish_room(
    room: Rect,
    entities: list[tuple[str, str]],
    door_positions: list[Point2D],
    *,
    body_radius: float,
    doorway_width: float,
    region_id: str = "",
    seed: int = 0,
    reserved: list[Rect] | None = None,
) -> list[PlacedFurniture]:
    """Arrange a room's furniture and return the pieces that fit, in placement order.

    Pieces that cannot be placed anywhere are simply absent from the result; the caller gives them a
    free-standing interaction point instead. That is the same contract the perimeter walk had, and
    materialization depends on it.
    """
    from smart_home_sim.materialization.floorplan import PlacedFurniture as Placed

    if not entities:
        return []
    return [
        Placed(
            entity_id=item.entity_id,
            footprint=item.pose.rect,
            approach=_point(item.approach),
            facing=item.pose.facing,
        )
        for item in _Furnisher(
            room,
            door_positions,
            body_radius=body_radius,
            doorway_width=doorway_width,
            region_id=region_id,
            seed=seed,
            reserved=reserved or [],
        ).run(entities)
    ]


def _point(position: tuple[float, float]) -> Point2D:
    return Point2D(x=round(position[0], 4), y=round(position[1], 4))


class _Furnisher:
    """One room's worth of arrangement state: what is standing, and what floor is left."""

    def __init__(
        self,
        room: Rect,
        doors: list[Point2D],
        *,
        body_radius: float,
        doorway_width: float,
        region_id: str,
        seed: int,
        reserved: list[Rect] | None = None,
    ) -> None:
        from shapely.geometry import Point as ShapelyPoint

        self.room = room
        self.clearance = body_radius + CLEARANCE_EPSILON
        self.approach_gap = self.clearance + _APPROACH_GAP
        self.doors = doors
        self.random = Random(f"{region_id}:{seed}")
        self.standing: list[_Standing] = []
        # Which way each arrangement likes to face in *this* flat. Jitter alone only breaks ties,
        # so without a standing preference every seed produced the same plan with the ornaments
        # shuffled. Choosing a side per group is what moves the bed to the other wall and takes the
        # whole bedroom with it.
        self.bias: dict[str, Vector] = {
            group: _FACINGS[self.random.randrange(len(_FACINGS))] for group in sorted(_GROUP_RANK)
        }

        shell = _shapely_rect(room)
        self.walkable = shell.buffer(-self.clearance, join_style="mitre")
        # Keep-clear discs in front of every doorway, so no arrangement can seal a room shut.
        radius = doorway_width / 2 + self.clearance
        self.door_zones = [
            _rect(item.x - radius, item.y - radius, 2 * radius, 2 * radius) for item in doors
        ]
        self.required = [ShapelyPoint(item.x, item.y) for item in doors]
        self.free: Any = self.walkable
        # Floor that is already taken by something the room did not choose — a staircase, a
        # chimney breast, a structural column. It is not furniture and never moves, so it enters
        # the free space as a hole and every later piece has to work round it.
        self.reserved: list[Rect] = list(reserved or [])
        for blocker in self.reserved:
            self.free = self.free.difference(
                _shapely_rect(blocker).buffer(self.clearance, join_style="mitre")
            )

    # -- the public step -------------------------------------------------------------------

    def run(self, entities: list[tuple[str, str]]) -> list[_Standing]:
        if self.walkable.is_empty or self.walkable.geom_type != "Polygon":
            return []
        for entity_id, entity_type in self._ordered(entities):
            base = spec_for(entity_type)
            # Comfortable clearance is a preference, not a law. A small flat has a bathroom where
            # the washing machine stands closer to the basin than a showroom would allow, and the
            # alternative to that is not a roomier bathroom, it is a washing machine the plan drops
            # on the floor with no footprint at all. Each relaxation is tried in full before the
            # next, so a piece only crowds its neighbours when nothing else worked.
            for scale in _CLEARANCE_RELAXATIONS:
                spec = (
                    base
                    if scale == 1.0
                    else replace(base, clearance=round(base.clearance * scale, 3))
                )
                # The last, clearance-free pass is exhaustive. Everything before it is a search
                # for a *good* pose and can afford to give up; this one is the difference between a
                # cramped bathroom and a washing machine that is not in the plan at all.
                budget = _LAST_RESORT_BUDGET if scale == 0.0 else _HARD_CHECK_BUDGET
                poses = self._candidates(entity_id, entity_type, spec)[:budget]
                # A pose a body can walk up to and use is worth more than a pose that merely fits,
                # so the whole list is tried that way first. Falling straight through to "it fits"
                # is what would put a chair somewhere you can only reach by climbing over it.
                settled = any(
                    self._accept(entity_id, entity_type, spec, pose, reachable=True)
                    for pose in poses
                ) or any(
                    self._accept(entity_id, entity_type, spec, pose, reachable=False)
                    for pose in poses
                )
                if settled:
                    break
        self._assign_approaches()
        return self.standing

    def _assign_approaches(self) -> None:
        """Give every placed piece a standing point, once the room is finished.

        Doing this during placement made each piece reserve floor the next one then could not use:
        the dining table claimed the spot in front of it, and its own chairs were refused for
        standing there. The room has to be complete before it is decided where a body stands in it.
        """
        from shapely.geometry import Point as ShapelyPoint
        from shapely.ops import nearest_points

        room = self._walkable_component()
        taken: list[tuple[float, float]] = []
        for item in self.standing:
            options = [
                option
                for option in item.pose.approach_options(self.approach_gap)
                if room is not None and room.covers(ShapelyPoint(*option))
            ]
            fresh = [
                option
                for option in options
                if all(
                    abs(option[0] - other[0]) > 0.12 or abs(option[1] - other[1]) > 0.12
                    for other in taken
                )
            ]
            if fresh:
                item.approach = fresh[0]
            elif options:
                item.approach = options[0]
            elif room is not None:
                # Nothing round the piece is free floor, which happens in a genuinely tight room.
                # The nearest reachable point is still somewhere the resident can be, and it lies in
                # the component the doorways are in, so the path planner can get her there.
                #
                # The component is eroded first, and that is not a nicety: `nearest_points` returns
                # a point *on* the boundary, and the home validator tests an interaction point by
                # asking whether an obstacle grown by the approach radius covers it — which a point
                # sitting exactly on that boundary is. The generator would have emitted a point it
                # then rejected itself.
                inner = room.buffer(-_FALLBACK_INSET, join_style="mitre")
                target = inner if not getattr(inner, "is_empty", True) else room
                point = nearest_points(target, ShapelyPoint(*item.pose.centre))[0]
                item.approach = (float(point.x), float(point.y))
            else:
                item.approach = item.pose.centre
            taken.append(item.approach)

    def _walkable_component(self) -> Any:
        """The part of the free space every doorway opens onto: where a body actually is."""
        if getattr(self.free, "is_empty", True):
            return None
        parts = list(getattr(self.free, "geoms", [])) or [self.free]
        covering = [part for part in parts if all(part.covers(item) for item in self.required)]
        return (covering or [max(parts, key=lambda part: part.area)])[0]

    def _ordered(self, entities: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Anchors before the things that hang off them, and big decisions before small ones."""

        def rank(entry: tuple[str, str]) -> tuple[int, float, str]:
            entity_id, entity_type = entry
            spec = spec_for(entity_type)
            base = (
                _SATELLITE_RANK
                if canonical_type(entity_type) in _SATELLITES
                else _GROUP_RANK.get(spec.group, _GROUP_RANK["misc"])
            )
            # Within a rank the bulkiest piece is placed first: it is the one with the fewest
            # places to go, and letting a nightstand take the only wall a wardrobe fits is how the
            # old placer emptied bedrooms.
            return (base, -spec.extent * spec.depth, entity_id)

        return sorted(entities, key=rank)

    # -- candidate poses -------------------------------------------------------------------

    def _candidates(self, entity_id: str, entity_type: str, spec: FurnitureSpec) -> list[Pose]:
        poses: list[Pose] = []
        anchors, relation = _SATELLITES.get(canonical_type(entity_type), ((), ""))
        for anchor_type in anchors:
            anchor = self._standing_of(anchor_type)
            if anchor is None:
                continue
            poses.extend(self._relational(anchor, spec, relation))
            break
        if spec.placement in {"island", "free"}:
            poses.extend(self._island_poses(spec))
        poses.extend(self._wall_poses(spec))
        return _spread(sorted(poses, key=lambda item: (-item.score, item.rect.x, item.rect.y)))

    def _standing_of(self, entity_type: str) -> _Standing | None:
        for item in self.standing:
            if canonical_type(item.entity_type) == entity_type:
                return item
        return None

    def _wall_poses(self, spec: FurnitureSpec) -> list[Pose]:
        """Every flush position along every wall, at both permitted orientations."""
        poses: list[Pose] = []
        walls = (
            # (facing into the room, the wall's fixed coordinate, whether the wall runs vertically)
            ((0.0, 1.0), self.room.y, False),
            ((0.0, -1.0), self.room.max_y, False),
            ((1.0, 0.0), self.room.x, True),
            ((-1.0, 0.0), self.room.max_x, True),
        )
        for facing, fixed, vertical in walls:
            length = self.room.height if vertical else self.room.width
            low = self.room.y if vertical else self.room.x
            for extent, depth in _orientations(spec):
                if extent > length + 1e-9:
                    continue
                steps = int((length - extent) / _WALL_STEP) + 1
                for index in range(steps + 1):
                    offset = min(index * _WALL_STEP, length - extent)
                    centre = low + offset + extent / 2
                    back = (fixed, centre) if vertical else (centre, fixed)
                    rect = _snap(self.room, _pose_at(back, facing, extent, depth))
                    pose = Pose(rect, facing)
                    score = self._score(pose, spec, along_wall=True, rotated=depth != spec.depth)
                    if score is None:
                        continue
                    poses.append(Pose(rect, facing, score))
        return poses

    def _island_poses(self, spec: FurnitureSpec) -> list[Pose]:
        """Positions out in the floor, which is where a dining table belongs."""
        poses: list[Pose] = []
        inner = _rect(
            self.room.x + self.clearance,
            self.room.y + self.clearance,
            max(self.room.width - 2 * self.clearance, 0.0),
            max(self.room.height - 2 * self.clearance, 0.0),
        )
        if inner.width <= 0 or inner.height <= 0:
            return poses
        columns = max(int(inner.width / _ISLAND_STEP), 1)
        rows = max(int(inner.height / _ISLAND_STEP), 1)
        for facing in _FACINGS:
            for extent, depth in _orientations(spec):
                for row in range(rows + 1):
                    for column in range(columns + 1):
                        centre_x = inner.x + inner.width * column / max(columns, 1)
                        centre_y = inner.y + inner.height * row / max(rows, 1)
                        back = (
                            centre_x - facing[0] * depth / 2,
                            centre_y - facing[1] * depth / 2,
                        )
                        rect = _snap(self.room, _pose_at(back, facing, extent, depth))
                        pose = Pose(rect, facing)
                        score = self._score(
                            pose, spec, along_wall=False, rotated=depth != spec.depth
                        )
                        if score is None:
                            continue
                        poses.append(Pose(rect, facing, score))
        return poses

    def _relational(self, anchor: _Standing, spec: FurnitureSpec, relation: str) -> list[Pose]:
        """Poses that only make sense with respect to a piece already standing.

        The bonus here is large on purpose: a coffee table in front of the sofa is worth more than
        any wall position, and without a decisive margin the generic poses win on wall affinity and
        the arrangement never forms.
        """
        poses: list[Pose] = []
        forward = anchor.pose.facing
        side = (-forward[1], forward[0])
        anchor_centre = anchor.pose.centre
        anchor_reach = (
            abs(forward[0]) * anchor.pose.rect.width + abs(forward[1]) * anchor.pose.rect.height
        ) / 2
        anchor_half = (
            abs(side[0]) * anchor.pose.rect.width + abs(side[1]) * anchor.pose.rect.height
        ) / 2

        def add(
            back: tuple[float, float],
            facing: Vector,
            extent: float,
            depth: float,
            bonus: float,
        ) -> None:
            rect = _snap(self.room, _pose_at(back, facing, extent, depth))
            pose = Pose(rect, facing)
            score = self._score(
                pose,
                spec,
                along_wall=_touches_wall(self.room, rect),
                rotated=depth != spec.depth,
                anchor_id=anchor.entity_id,
            )
            if score is None:
                return
            poses.append(Pose(rect, facing, score + bonus))

        if relation == "flank":
            # Beside the anchor, flush with its back, facing the same way: a bedside table.
            for direction in (1, -1):
                for gap in (0.06, 0.20, 0.40):
                    offset = anchor_half + gap + spec.extent / 2
                    back = (
                        anchor_centre[0] - forward[0] * anchor_reach + side[0] * direction * offset,
                        anchor_centre[1] - forward[1] * anchor_reach + side[1] * direction * offset,
                    )
                    add(back, forward, spec.extent, spec.depth, 9.0 - gap)
        elif relation == "front":
            # In front of the anchor, turned to face it back: a coffee table before a sofa.
            facing = (-forward[0], -forward[1])
            for gap in (0.40, 0.50, 0.62, 0.75):
                for slide in (0.0, 0.25, -0.25):
                    reach = anchor_reach + gap + spec.depth
                    back = (
                        anchor_centre[0] + forward[0] * reach + side[0] * slide,
                        anchor_centre[1] + forward[1] * reach + side[1] * slide,
                    )
                    add(back, facing, spec.extent, spec.depth, 9.0 - gap)
        elif relation == "faced_by":
            # On the surface the anchor is looking at, turned back towards it. This is the whole
            # reason a television is worth placing at all: it is the piece whose position is
            # entirely a consequence of another one.
            #
            # The whole of that wall is offered, not just the centre line, because the centre line
            # is often exactly where the door is: with five positions to choose from, a sofa facing
            # the doorway wall got no television opposite it at all and one beside it instead. The
            # bonus falls off with how far along the wall the set has to go, so dead ahead still
            # wins whenever dead ahead is free.
            facing = (-forward[0], -forward[1])
            wall_back = self._wall_point(anchor_centre, forward)
            span = abs(side[0]) * self.room.width + abs(side[1]) * self.room.height
            steps = int(span / 0.2)
            for index in range(steps + 1):
                slide = index * 0.2 - span / 2
                back = (wall_back[0] + side[0] * slide, wall_back[1] + side[1] * slide)
                add(back, facing, spec.extent, spec.depth, max(10.0 - 1.4 * abs(slide), 4.5))
        elif relation == "around":
            # Chairs go round a table: one per side, then the corners, all turned inwards.
            table = anchor.pose.rect
            centre = anchor.pose.centre
            for facing in _FACINGS:
                across = (-facing[1], facing[0])
                reach = (abs(facing[0]) * table.width + abs(facing[1]) * table.height) / 2
                span = (abs(across[0]) * table.width + abs(across[1]) * table.height) / 2
                seats = 2 if span >= spec.extent * 1.9 else 1
                for index in range(seats):
                    slide = 0.0 if seats == 1 else (index - 0.5) * spec.extent * 1.35
                    # `facing` here is the outward normal of the table side being seated. The seat
                    # stands beyond it, at arm's length, and looks back inwards — which is the
                    # opposite of the normal, and is why the seat's back, not its front, is the
                    # point being offset.
                    reach_out = reach + 0.04 + spec.depth
                    back = (
                        centre[0] + facing[0] * reach_out + across[0] * slide,
                        centre[1] + facing[1] * reach_out + across[1] * slide,
                    )
                    add(back, (-facing[0], -facing[1]), spec.extent, spec.depth, 8.5 - 0.1 * index)
        elif relation == "quarter":
            # At right angles to the anchor, closing the arrangement into an L.
            for direction in (1, -1):
                offset = anchor_half + 0.35 + spec.depth
                facing = (-side[0] * direction, -side[1] * direction)
                back = (
                    anchor_centre[0] + side[0] * direction * offset + forward[0] * 0.25,
                    anchor_centre[1] + side[1] * direction * offset + forward[1] * 0.25,
                )
                add(back, facing, spec.extent, spec.depth, 7.0)
        elif relation == "beside":
            for direction in (1, -1):
                offset = anchor_half + 0.18 + spec.extent / 2
                back = (
                    anchor_centre[0] - forward[0] * anchor_reach + side[0] * direction * offset,
                    anchor_centre[1] - forward[1] * anchor_reach + side[1] * direction * offset,
                )
                add(back, forward, spec.extent, spec.depth, 6.0)
        return poses

    def _wall_point(self, origin: tuple[float, float], direction: Vector) -> tuple[float, float]:
        """Where a ray from `origin` along `direction` meets the room's wall."""
        if direction[0] > 0:
            return (self.room.max_x, origin[1])
        if direction[0] < 0:
            return (self.room.x, origin[1])
        if direction[1] > 0:
            return (origin[0], self.room.max_y)
        return (origin[0], self.room.y)

    # -- scoring and acceptance ------------------------------------------------------------

    def _score(
        self,
        pose: Pose,
        spec: FurnitureSpec,
        *,
        along_wall: bool,
        rotated: bool,
        anchor_id: str = "",
    ) -> float | None:
        """What this pose is worth, or `None` if it is disqualified on cheap grounds.

        Everything here is rectangle arithmetic. The expensive free-space test runs only on the
        handful of poses that come out on top, which is what keeps a fully furnished flat inside the
        materialization budget.
        """
        rect = pose.rect
        if not _contains(self.room, rect):
            return None
        for zone in self.door_zones:
            if _overlaps(rect, zone):
                return None
        for blocker in self.reserved:
            if _overlaps(rect, blocker, gap=_PIECE_GAP):
                return None
        for item in self.standing:
            if _overlaps(rect, item.pose.rect, gap=_PIECE_GAP):
                return None
        # The floor in front has to exist and has to be floor. A wardrobe that opens into the sofa
        # is a wardrobe nobody can open, and it is exactly what a perimeter walk produces.
        needed = _clearance_rect(pose, spec.clearance)
        if not _contains(self.room, needed):
            return None
        for item in self.standing:
            # A satellite is *meant* to occupy its anchor's working space: that is what a chair at a
            # table is. Enforcing the clearance against the anchor as well would reject every seat
            # round every table and leave the chairs back against the skirting board.
            if item.entity_id == anchor_id:
                continue
            if _overlaps(needed, item.pose.rect):
                return None
        # ...and the piece must not stand in somebody else's working space either.
        for item in self.standing:
            if item.entity_id == anchor_id:
                continue
            if _overlaps(rect, _clearance_rect(item.pose, item.spec.clearance)):
                return None

        score = 0.0
        centre = pose.centre
        nearest_door = min(
            (_distance_to_rect(centre, zone) for zone in self.door_zones), default=3.0
        )
        # Circulation: keep the traffic lane between doorways clear. Distance saturates, because
        # past a couple of metres a doorway stops being the thing that decides the layout.
        score += 1.6 * min(nearest_door, 2.0)

        if along_wall:
            score += 2.4 if spec.placement in {"wall", "corner"} else 0.6
            if spec.placement == "corner":
                score += 2.0 * (1.0 - min(self._corner_distance(rect) / 1.2, 1.0))
        else:
            score += 2.2 if spec.placement == "island" else 0.9
            if spec.placement == "island":
                # An island wants to be central; a table shoved into a corner is a wall table that
                # has merely stopped touching the wall.
                room_centre = (
                    self.room.x + self.room.width / 2,
                    self.room.y + self.room.height / 2,
                )
                offset = (
                    (centre[0] - room_centre[0]) ** 2 + (centre[1] - room_centre[1]) ** 2
                ) ** 0.5
                reach = max(self.room.width, self.room.height) / 2
                score += 3.0 * (1.0 - min(offset / reach, 1.0))
        if rotated:
            # Turning a piece is a concession, not a preference.
            score -= 1.2

        # Group cohesion: a fitted run wants to continue the run it is part of, and the pieces of an
        # arrangement want to be near one another rather than scattered round the walls.
        for item in self.standing:
            if item.spec.group != spec.group:
                continue
            gap = _distance_to_rect(centre, item.pose.rect)
            if spec.run and item.spec.run:
                aligned = item.pose.facing == pose.facing
                score += (3.5 if aligned else 0.8) * (1.0 - min(gap / 2.0, 1.0))
            else:
                score += 1.1 * (1.0 - min(gap / 3.0, 1.0))

        # A bed or a sofa belongs on the wall you see when you walk in, not beside the door.
        if spec.group in {"sleep", "lounge"} and spec.placement == "wall":
            score += 0.9 * min(nearest_door, 3.0)

        if self.bias.get(spec.group) == pose.facing:
            score += 1.3

        # Seeded jitter, enough to break a near-tie and not enough to overturn a real preference.
        score += self.random.uniform(0.0, 0.9)
        return score

    def _corner_distance(self, rect: Rect) -> float:
        corners = (
            (self.room.x, self.room.y),
            (self.room.max_x, self.room.y),
            (self.room.x, self.room.max_y),
            (self.room.max_x, self.room.max_y),
        )
        return min(_distance_to_rect(corner, rect) for corner in corners)

    def _accept(
        self,
        entity_id: str,
        entity_type: str,
        spec: FurnitureSpec,
        pose: Pose,
        *,
        reachable: bool,
    ) -> bool:
        """The hard test: does the room still work as a room with this piece in it?

        Free space is carried forward rather than rebuilt, so each candidate costs one difference
        against a polygon that is already computed instead of a fresh union of everything placed.

        `reachable` asks the stronger question — is there floor beside the piece to stand on — and
        is what the first sweep over the candidates uses. The second sweep drops it, because a
        wardrobe you have to sidle up to is still better than a wardrobe that is not in the room.
        """
        from shapely.geometry import Point as ShapelyPoint

        trial = self.free.difference(
            _shapely_rect(pose.rect).buffer(self.clearance, join_style="mitre")
        )
        if getattr(trial, "is_empty", True):
            return False
        parts = list(getattr(trial, "geoms", [])) or [trial]
        # The room's own space is whichever component every doorway opens onto; a candidate leaving
        # no such component is a candidate that seals the room shut.
        room = next(
            (part for part in parts if all(part.covers(item) for item in self.required)), None
        )
        if room is None:
            return False
        if reachable and not any(
            room.covers(ShapelyPoint(*option))
            for option in pose.approach_options(self.approach_gap)
        ):
            return False
        self.free = trial
        self.standing.append(_Standing(entity_id, entity_type, spec, pose))
        return True


def _orientations(spec: FurnitureSpec) -> tuple[tuple[float, float], ...]:
    if abs(spec.extent - spec.depth) < 1e-9:
        return ((spec.extent, spec.depth),)
    if not spec.rotatable:
        return ((spec.extent, spec.depth),)
    return ((spec.extent, spec.depth), (spec.depth, spec.extent))


def _spread(ordered: list[Pose]) -> list[Pose]:
    """Thin a sorted candidate list down to poses that are actually different from each other.

    Sampling a wall every ten centimetres means the twenty best-scoring poses are twenty shuffles of
    the same spot, so a piece whose favourite corner is blocked burned its whole budget re-testing
    that corner and was dropped from a room with three empty walls. Keeping a minimum separation
    turns the budget into twenty real attempts. The thinned-out poses are kept on the end, because a
    crowded room may genuinely only have room within one corner.
    """
    chosen: list[Pose] = []
    rest: list[Pose] = []
    for pose in ordered:
        centre = pose.centre
        # The best few are kept whatever they look like. A relational pose offers the same
        # arrangement at three or four gaps — the bedside table six centimetres from the bed, then
        # twenty, then forty — and they are within a separation of each other by construction.
        # Thinning them left one attempt at the arrangement instead of four, and a bedside table
        # that could not be reached from the six-centimetre one ended up against the far wall.
        near = len(chosen) >= _KEEP_BEST and any(
            item.facing == pose.facing
            and abs(item.centre[0] - centre[0]) < _POSE_SEPARATION
            and abs(item.centre[1] - centre[1]) < _POSE_SEPARATION
            for item in chosen
        )
        (rest if near else chosen).append(pose)
        if len(chosen) >= _HARD_CHECK_BUDGET:
            break
    return chosen + rest


def _touches_wall(room: Rect, rect: Rect) -> bool:
    return (
        abs(rect.x - room.x) < 0.05
        or abs(rect.y - room.y) < 0.05
        or abs(rect.max_x - room.max_x) < 0.05
        or abs(rect.max_y - room.max_y) < 0.05
    )


def _shapely_rect(rect: Rect) -> Any:
    from shapely.geometry import Polygon as ShapelyPolygon

    return ShapelyPolygon(
        [
            (rect.x, rect.y),
            (rect.max_x, rect.y),
            (rect.max_x, rect.max_y),
            (rect.x, rect.max_y),
        ]
    )


__all__ = [
    "CLEARANCE_EPSILON",
    "FurnitureSpec",
    "Pose",
    "canonical_type",
    "footprint_for",
    "furnish_room",
    "spec_for",
]
