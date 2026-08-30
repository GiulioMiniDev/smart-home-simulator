"""What a furnished room has to look like.

The old placer walked the perimeter and these are the things it could not do: put a chair at a
table, point a television at a sofa, keep a kitchen's fixtures in one run, or leave the middle of a
room as anything but a void. Each of those is a test here, alongside the invariants that were
always true and must stay true — everything inside its room, nothing overlapping, the room still
walkable end to end.
"""

from __future__ import annotations

from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.ops import unary_union

from smart_home_sim.domain.environment import Point2D
from smart_home_sim.materialization.floorplan import PlacedFurniture, Rect, place_furniture
from smart_home_sim.materialization.furnishing import footprint_for, spec_for

BODY_RADIUS = 0.27
DOORWAY = 1.0


def _polygon(rect: Rect) -> ShapelyPolygon:
    return ShapelyPolygon(
        [(rect.x, rect.y), (rect.max_x, rect.y), (rect.max_x, rect.max_y), (rect.x, rect.max_y)]
    )


def _by_id(placed: list[PlacedFurniture]) -> dict[str, PlacedFurniture]:
    return {item.entity_id: item for item in placed}


def _centre(item: PlacedFurniture) -> tuple[float, float]:
    return (
        item.footprint.x + item.footprint.width / 2,
        item.footprint.y + item.footprint.height / 2,
    )


def _gap(left: PlacedFurniture, right: PlacedFurniture) -> float:
    dx = max(
        left.footprint.x - right.footprint.max_x, right.footprint.x - left.footprint.max_x, 0.0
    )
    dy = max(
        left.footprint.y - right.footprint.max_y, right.footprint.y - left.footprint.max_y, 0.0
    )
    return (dx * dx + dy * dy) ** 0.5


def _furnish(room: Rect, entities: list[tuple[str, str]], doors: list[Point2D], **kwargs: object):
    return place_furniture(
        room,
        entities,
        doors,
        body_radius=BODY_RADIUS,
        doorway_width=DOORWAY,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_dining_chair_stands_at_the_table_and_not_against_the_wall() -> None:
    """The perimeter walk put the table on one wall and its four chairs along another."""
    room = Rect(0.0, 0.0, 4.6, 4.0)
    placed = _furnish(
        room,
        [
            ("table_01", "table"),
            ("chair_01", "chair"),
            ("chair_02", "chair"),
            ("chair_03", "chair"),
        ],
        [Point2D(x=0.5, y=0.4)],
        region_id="dining_room",
        seed=4,
    )
    items = _by_id(placed)
    assert "table_01" in items
    seated = [items[key] for key in ("chair_01", "chair_02", "chair_03") if key in items]
    assert len(seated) >= 2
    for chair in seated:
        assert _gap(items["table_01"], chair) < 0.5, "a chair belongs at the table, not near it"


def test_the_table_stands_in_the_floor_rather_than_against_a_wall() -> None:
    room = Rect(0.0, 0.0, 4.6, 4.0)
    placed = _by_id(_furnish(room, [("table_01", "table")], [], region_id="dining_room", seed=1))
    table = placed["table_01"].footprint
    clear = min(
        table.x - room.x, table.y - room.y, room.max_x - table.max_x, room.max_y - table.max_y
    )
    assert clear > 0.4, "an island that touches a wall is a wall table"


def test_the_television_faces_whatever_is_looking_at_it() -> None:
    room = Rect(0.0, 0.0, 5.4, 4.4)
    placed = _by_id(
        _furnish(
            room,
            [("sofa_01", "sofa"), ("television_01", "television")],
            [Point2D(x=0.5, y=0.45)],
            region_id="living_room",
            seed=2,
        )
    )
    sofa, television = placed["sofa_01"], placed["television_01"]
    # Measured along the direction the sofa looks in, not along the axes: two things on the same
    # wall two metres apart are also "far apart in x", and that is not a sitting room.
    sofa_centre, screen_centre = _centre(sofa), _centre(television)
    offset = (screen_centre[0] - sofa_centre[0], screen_centre[1] - sofa_centre[1])
    ahead = offset[0] * sofa.facing[0] + offset[1] * sofa.facing[1]
    sideways = abs(offset[0] * -sofa.facing[1] + offset[1] * sofa.facing[0])
    assert ahead > 1.5, "the screen has to be in front of the seat, across the room"
    # Loose, and deliberately so: dead ahead wins when dead ahead is free, but this room's doorway
    # is on the wall the sofa faces, and a set slid along that wall is better than one beside the
    # sofa. What must not happen is the set ending up on the same wall as the seat.
    assert sideways < 2.2, "the set has to stay on the wall the sofa looks at"
    assert (
        round(sofa.facing[0] + television.facing[0], 6),
        round(sofa.facing[1] + television.facing[1], 6),
    ) == (0.0, 0.0)


def test_a_nightstand_stands_beside_the_bed() -> None:
    room = Rect(0.0, 0.0, 4.2, 3.6)
    placed = _by_id(
        _furnish(
            room,
            [("bed_01", "bed"), ("nightstand_01", "nightstand"), ("wardrobe_01", "wardrobe")],
            [Point2D(x=0.5, y=0.45)],
            region_id="bedroom",
            seed=5,
        )
    )
    assert _gap(placed["bed_01"], placed["nightstand_01"]) < 0.45
    # Beside, which means facing the same way, not turned to look at the bed.
    assert placed["nightstand_01"].facing == placed["bed_01"].facing


def test_the_kitchen_fixtures_form_one_run() -> None:
    room = Rect(0.0, 0.0, 4.4, 3.4)
    placed = _by_id(
        _furnish(
            room,
            [
                ("sink_01", "sink"),
                ("stove_01", "stove"),
                ("counter_01", "kitchen_counter"),
                ("refrigerator_01", "refrigerator"),
            ],
            [Point2D(x=0.5, y=0.45)],
            region_id="kitchen",
            seed=3,
        )
    )
    run = [placed[key] for key in ("sink_01", "stove_01", "counter_01") if key in placed]
    assert len(run) == 3
    facings = {item.facing for item in run}
    assert len(facings) == 1, "a fitted run faces one way; three walls is not a kitchen"
    for other in run[1:]:
        assert _gap(run[0], other) < 2.2


def test_nothing_leaves_its_room_overlaps_or_seals_it() -> None:
    """The invariants the path planner depends on, over every kind of room the generator emits."""
    rooms = {
        "living_room": (
            Rect(0.0, 0.0, 5.4, 4.4),
            [
                "sofa",
                "television",
                "coffee_table",
                "armchair",
                "bookshelf",
                "floor_lamp",
                "houseplant",
            ],
        ),
        "bedroom": (
            Rect(0.0, 0.0, 4.2, 3.6),
            ["bed", "wardrobe", "nightstand", "nightstand", "chest_of_drawers"],
        ),
        "kitchen": (
            Rect(0.0, 0.0, 4.4, 3.4),
            [
                "sink",
                "stove",
                "refrigerator",
                "kitchen_counter",
                "table",
                "chair",
                "chair",
                "microwave",
            ],
        ),
        "bathroom": (
            Rect(0.0, 0.0, 2.6, 3.2),
            ["shower", "toilet", "washbasin", "washing_machine", "bidet"],
        ),
        "hallway": (Rect(0.0, 0.0, 3.4, 1.9), ["shoe_rack", "coat_rack", "mirror"]),
    }
    for region_id, (room, types) in rooms.items():
        doors = [Point2D(x=room.width / 2, y=0.42), Point2D(x=0.42, y=room.height / 2)]
        entities = [(f"{kind}_{index:02d}", kind) for index, kind in enumerate(types)]
        placed = _furnish(room, entities, doors, region_id=region_id, seed=11)
        assert placed, region_id

        shell = _polygon(room)
        for item in placed:
            assert shell.covers(_polygon(item.footprint)), f"{item.entity_id} left {region_id}"
        for index, left in enumerate(placed):
            for right in placed[index + 1 :]:
                overlap = _polygon(left.footprint).intersection(_polygon(right.footprint)).area
                assert overlap <= 1e-9, f"{left.entity_id} and {right.entity_id} overlap"

        clearance = BODY_RADIUS + 0.02
        free = shell.buffer(-clearance, join_style="mitre").difference(
            unary_union(
                [_polygon(item.footprint).buffer(clearance, join_style="mitre") for item in placed]
            )
        )
        parts = list(getattr(free, "geoms", [])) or [free]
        probes = [ShapelyPoint(door.x, door.y) for door in doors]
        probes.extend(ShapelyPoint(item.approach.x, item.approach.y) for item in placed)
        assert any(all(part.covers(probe) for probe in probes) for part in parts), (
            f"{region_id} is not one walkable room any more"
        )


def test_two_seeds_furnish_the_same_room_differently_and_each_one_the_same_way_twice() -> None:
    room = Rect(0.0, 0.0, 5.4, 4.4)
    entities = [
        ("sofa_01", "sofa"),
        ("television_01", "television"),
        ("coffee_table_01", "coffee_table"),
        ("bookshelf_01", "bookshelf"),
    ]
    doors = [Point2D(x=2.7, y=0.42)]

    def layout(seed: int) -> list[tuple[str, float, float]]:
        return [
            (item.entity_id, round(item.footprint.x, 3), round(item.footprint.y, 3))
            for item in _furnish(room, entities, doors, region_id="living_room", seed=seed)
        ]

    assert layout(1) == layout(1)
    assert len({tuple(layout(seed)) for seed in range(1, 9)}) > 1


def test_floor_a_staircase_already_occupies_is_not_offered_to_the_furniture() -> None:
    room = Rect(0.0, 0.0, 3.6, 3.0)
    stairs = Rect(1.3, 0.0, 1.0, 2.4)
    placed = _furnish(
        room,
        [("bookshelf_01", "bookshelf"), ("sideboard_01", "sideboard")],
        [Point2D(x=0.42, y=1.5)],
        region_id="hallway",
        seed=6,
        reserved=[stairs],
    )
    for item in placed:
        assert _polygon(item.footprint).intersection(_polygon(stairs)).area <= 1e-9


def test_a_scenario_spelling_resolves_to_the_piece_it_names() -> None:
    """`bedside_table` is a nightstand; it used to be an anonymous 0.60 x 0.50 box."""
    assert footprint_for("bedside_table") == footprint_for("nightstand")
    assert spec_for("dining_table").placement == "island"
    assert spec_for("something_nobody_has_heard_of").placement == "wall"


def test_a_room_with_nothing_in_it_and_a_room_too_small_to_stand_in() -> None:
    """Both are real: a balcony the scenario gave no objects, and a cupboard-sized store."""
    assert _furnish(Rect(0.0, 0.0, 3.0, 2.0), [], []) == []
    cramped = _furnish(
        Rect(0.0, 0.0, 0.4, 0.4), [("cabinet_01", "storage_cabinet")], [], region_id="storage"
    )
    assert cramped == []


def test_a_piece_with_nowhere_to_stand_beside_it_still_gets_a_reachable_point() -> None:
    """A tight room is a tight room; what it must not produce is furniture nobody can reach.

    The point falls back to the nearest floor in the component the doorway opens onto, pulled just
    inside it — on its edge the home validator counts the point as blocked and refuses the model.
    """
    room = Rect(0.0, 0.0, 2.2, 2.0)
    placed = _furnish(
        room,
        [("wardrobe_01", "wardrobe"), ("cabinet_01", "storage_cabinet"), ("shelf_01", "bookshelf")],
        [Point2D(x=1.1, y=0.42)],
        region_id="storage",
        seed=2,
    )
    assert placed
    shell = _polygon(room)
    clearance = BODY_RADIUS + 0.02
    free = shell.buffer(-clearance, join_style="mitre").difference(
        unary_union(
            [_polygon(item.footprint).buffer(clearance, join_style="mitre") for item in placed]
        )
    )
    parts = list(getattr(free, "geoms", [])) or [free]
    for item in placed:
        point = ShapelyPoint(item.approach.x, item.approach.y)
        assert any(part.covers(point) for part in parts), item.entity_id


def test_a_piece_the_room_has_no_space_for_is_left_out_rather_than_forced_in() -> None:
    """The caller's contract: anything absent from the result gets a free-standing point instead."""
    room = Rect(0.0, 0.0, 2.0, 1.9)
    placed = _furnish(
        room,
        [("bed_01", "bed"), ("wardrobe_01", "wardrobe"), ("second_bed_01", "bed")],
        [Point2D(x=1.0, y=0.42)],
        region_id="bedroom",
        seed=1,
    )
    assert len(placed) < 3
    assert all(_polygon(room).covers(_polygon(item.footprint)) for item in placed)
