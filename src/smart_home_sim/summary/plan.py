"""The dwelling as a drawing, derived from the home model and the sensor field over it.

A home model has no walls and no doors. It has regions that happen to touch and connections
declaring two points either side of a partition, which is everything the path planner needs and
nothing a reader does: drawn literally it gives one outline per room and a dotted line floating
across the label. This module derives what an architect would draw from exactly that data -- an
envelope, partitions inside it, openings with a swing, furniture footprints carrying their own
symbols, and the sensors laid over the lot.

The derivation is the one the editor canvas already performs in `frontend/src/editor.ts`, ported
here because an export cannot start a browser. A dataset that travels to another machine has to
carry its own picture of the flat, or `pir_kitchen` in the sensor log is a name with no place
attached to it.

Everything is drawn in metres, in the model's own coordinates and its own orientation, so the page
never has to agree with the editor about a scale: the viewBox is the flat.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from smart_home_sim.domain.environment import HomeModel, HomeRegion, Point2D
from smart_home_sim.domain.sensors import SensorModel

# How far off a wall to look when asking what stands on the other side of it.
PROBE_METERS = 0.06
# Padding around the dwelling, in metres, so a caption at the edge is not clipped.
MARGIN_METERS = 1.2
# Below this a room caption stops being legible and is dropped rather than drawn over the walls.
MINIMUM_CAPTION_METERS = 0.16

# The fallback provider the materializer attaches to every room: a capability holder with no
# footprint and nothing to say to a reader.
SERVICE_ENTITY_TYPE = "generated_environment_service"

FURNITURE_SYMBOL: dict[str, str] = {
    "bed": "bed",
    "wardrobe": "wardrobe",
    "sofa": "sofa",
    "television": "television",
    "radio": "radio",
    "table": "table",
    "chair": "chair",
    "stove": "stove",
    "refrigerator": "refrigerator",
    "sink": "sink",
    "washbasin": "washbasin",
    "storage_cabinet": "cabinet",
    "moka_coffee_maker": "kettle",
    "shower": "shower",
    "toilet": "toilet",
    "washing_machine": "washing_machine",
    "garden_planter": "planter",
}

# The glyphs the editor draws, authored in a -24..24 box and scaled to each obstacle's real
# footprint at use time, so a symbol always matches the extent the path planner routes around.
#
# Every fill is written as an inline style rather than a class, because `<use>` clones a symbol
# into a shadow tree that the page's own selectors cannot reach: a stylesheet rule for
# `.furniture rect` never matches the copy the browser draws, and the shapes come out solid black.
# What does cross that boundary is inheritance, so the colours are custom properties resolved from
# the plan around them and the outline is `currentColor` -- which is how the same drawing reads on
# a white page and a dark one.
_PAPER = 'style="fill:var(--plan-paper)"'
_TINT = 'style="fill:var(--plan-tint)"'
_WARM = 'style="fill:var(--plan-warm)"'
_INK = 'style="fill:currentColor;stroke:none"'
_BODY = (
    'style="fill:none;stroke:currentColor;stroke-width:2;stroke-linejoin:round;'
    'stroke-linecap:round"'
)

_FURNITURE_BODIES: dict[str, str] = {
    "bed": f"""<rect x="-19" y="-15" width="38" height="30" rx="3" {_PAPER}/>
<rect x="-16" y="-12" width="13" height="9" rx="2" {_TINT}/>
<rect x="3" y="-12" width="13" height="9" rx="2" {_TINT}/>
<path d="M-16 1h32v11h-32z" {_TINT}/>""",
    "wardrobe": f"""<rect x="-15" y="-19" width="30" height="38" rx="2" {_PAPER}/>
<path d="M0-19v38"/><circle cx="-3" cy="0" r="1.8" {_INK}/>
<circle cx="3" cy="0" r="1.8" {_INK}/>""",
    "sofa": f"""<rect x="-20" y="-8" width="40" height="18" rx="4" {_PAPER}/>
<rect x="-20" y="-14" width="40" height="8" rx="3" {_TINT}/>
<rect x="-20" y="-10" width="6" height="18" rx="3" {_TINT}/>
<rect x="14" y="-10" width="6" height="18" rx="3" {_TINT}/>""",
    "television": f"""<rect x="-21" y="-14" width="42" height="26" rx="3" {_TINT}/>
<path d="M-7 17h14M0 12v5"/>""",
    "radio": f"""<rect x="-16" y="-10" width="32" height="20" rx="3" {_PAPER}/>
<circle cx="-6" cy="0" r="5" {_TINT}/><path d="M6-5h7M6 0h7M6 5h7"/>""",
    "table": f"""<circle cx="0" cy="0" r="15" {_WARM}/>
<path d="M-9 12l-4 8M9 12l4 8M-9-12l-4-8M9-12l4-8"/>""",
    "chair": f"""<rect x="-11" y="-6" width="22" height="18" rx="3" {_WARM}/>
<rect x="-11" y="-16" width="22" height="8" rx="3" {_TINT}/>""",
    "stove": f"""<rect x="-19" y="-18" width="38" height="36" rx="4" {_PAPER}/>
<circle cx="-8" cy="-7" r="5" {_TINT}/><circle cx="8" cy="-7" r="5" {_TINT}/>
<circle cx="-8" cy="8" r="5" {_TINT}/><circle cx="8" cy="8" r="5" {_TINT}/>""",
    "refrigerator": f"""<rect x="-14" y="-21" width="28" height="42" rx="3" {_PAPER}/>
<path d="M-14-5h28M8-15v7M8 1v8"/><rect x="-10" y="-17" width="12" height="8" rx="2" {_TINT}/>""",
    "sink": f"""<rect x="-19" y="-13" width="38" height="27" rx="4" {_PAPER}/>
<ellipse cx="0" cy="2" rx="12" ry="8" {_TINT}/><path d="M-4-13v-5c0-4 8-4 8 0v7"/>""",
    "washbasin": f"""<ellipse cx="0" cy="2" rx="17" ry="12" {_PAPER}/>
<ellipse cx="0" cy="2" rx="10" ry="6.5" {_TINT}/><path d="M-3-11v-4c0-3 6-3 6 0v5"/>""",
    "cabinet": f"""<rect x="-19" y="-17" width="38" height="34" rx="3" {_WARM}/>
<path d="M0-17v34M-19 0h38"/><circle cx="-4" cy="-8" r="1.6" {_INK}/>
<circle cx="4" cy="-8" r="1.6" {_INK}/><circle cx="-4" cy="8" r="1.6" {_INK}/>
<circle cx="4" cy="8" r="1.6" {_INK}/>""",
    "kettle": f"""<path d="M-11-10h19l4 25h-27z" {_PAPER}/>
<path d="M9-5c11 0 12 17 3 20M-6-10v-5h9v5"/>""",
    "shower": f"""<path d="M-12 17V-4c0-8 5-13 12-13 6 0 10 3 12 8"/>
<path d="M7-8h10v5H7z" {_TINT}/><path d="M9 2v2m4-2v2m4-2v2M9 9v2m4-2v2m4-2v2"/>
<path d="M-17 17h34"/>""",
    "toilet": f"""<rect x="-10" y="-18" width="20" height="13" rx="3" {_TINT}/>
<ellipse cx="0" cy="4" rx="13" ry="10" {_PAPER}/><ellipse cx="0" cy="4" rx="7" ry="5" {_TINT}/>""",
    "washing_machine": f"""<rect x="-18" y="-20" width="36" height="40" rx="4" {_PAPER}/>
<circle cx="0" cy="4" r="11" {_TINT}/><path d="M-13-13h14"/>
<circle cx="11" cy="-13" r="2" {_INK}/>""",
    "planter": f"""<path d="M-13 2h26l-4 16h-18z" {_WARM}/>
<path d="M0 2c0-9-5-14-11-15 1 8 5 13 11 15zM0 2c0-9 5-14 11-15-1 8-5 13-11 15z" {_TINT}/>""",
}

FURNITURE_SYMBOLS = "".join(
    f'<symbol id="furn-{name}" viewBox="-24 -24 48 48"><g {_BODY}>{body}</g></symbol>'
    for name, body in _FURNITURE_BODIES.items()
)

PLAN_STYLE = """
svg.plan { width: 100%; height: auto; display: block; margin: .8rem 0 .4rem;
  background: var(--plan-paper); border: 1px solid var(--line); border-radius: 6px; }
svg.plan .grid { fill: none; stroke: var(--plan-grid); stroke-width: .012; }
svg.plan .region { fill: var(--plan-room); stroke: none; }
svg.plan .wall { stroke: var(--plan-wall); stroke-linecap: square; }
svg.plan .wall-exterior { stroke-width: .16; }
svg.plan .wall-partition { stroke-width: .09; }
svg.plan .door-leaf { stroke: var(--plan-wall); stroke-width: .05; }
svg.plan .door-swing { fill: none; stroke: var(--plan-wall); stroke-width: .028;
  stroke-dasharray: .12 .1; opacity: .65; }
svg.plan .obstacle { fill: var(--plan-furniture); stroke: none; opacity: .45; }
svg.plan .furniture { color: var(--plan-ink); }
svg.plan .coverage { fill: none; stroke: var(--accent); stroke-width: .035;
  stroke-dasharray: .18 .14; opacity: .45; }
svg.plan .sensor { color: var(--accent); }
svg.plan .sensor-contact { color: var(--sensor-contact); }
svg.plan .sensor-temperature { color: var(--sensor-temperature); }
svg.plan .sensor .glyph { fill: none; stroke: currentColor; stroke-width: .045; }
svg.plan .sensor .glyph-solid { fill: currentColor; stroke: none; }
svg.plan text { font-family: "Segoe UI", system-ui, sans-serif; text-anchor: middle;
  fill: var(--plan-ink); }
svg.plan text.area { fill: var(--muted); }
svg.plan text.sensor-name { text-anchor: start; font-size: .18px; fill: var(--plan-ink); }
svg.plan text.door-caption { font-size: .2px; fill: var(--muted); }
"""


@dataclass(frozen=True)
class Wall:
    """One straight run of wall. `exterior` means nothing stands behind it: the envelope."""

    x1: float
    y1: float
    x2: float
    y2: float
    exterior: bool


@dataclass(frozen=True)
class Door:
    """An opening, plus the leaf and the swing that say which way it turns."""

    opening_id: str
    kind: str
    x1: float
    y1: float
    x2: float
    y2: float
    leaf_x: float
    leaf_y: float
    width: float


def _n(value: float) -> str:
    """Coordinates at millimetre resolution: finer is noise, and the file is smaller for it."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _points(vertices: Sequence[Point2D]) -> str:
    return " ".join(f"{_n(item.x)},{_n(item.y)}" for item in vertices)


def _length(x1: float, y1: float, x2: float, y2: float) -> float:
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def polygon_area(vertices: Sequence[Point2D]) -> float:
    total = 0.0
    for index, current in enumerate(vertices):
        previous = vertices[index - 1]
        total += (previous.x + current.x) * (previous.y - current.y)
    return abs(total) / 2


def point_in_polygon(x: float, y: float, vertices: Sequence[Point2D]) -> bool:
    inside = False
    for index, current in enumerate(vertices):
        previous = vertices[index - 1]
        if (current.y > y) != (previous.y > y) and x < (previous.x - current.x) * (
            y - current.y
        ) / (previous.y - current.y) + current.x:
            inside = not inside
    return inside


def _centre(vertices: Sequence[Point2D]) -> tuple[float, float]:
    count = max(len(vertices), 1)
    return sum(item.x for item in vertices) / count, sum(item.y for item in vertices) / count


def _box(vertices: Sequence[Point2D]) -> tuple[float, float, float, float]:
    return (
        min(item.x for item in vertices),
        min(item.y for item in vertices),
        max(item.x for item in vertices),
        max(item.y for item in vertices),
    )


def dwelling_region_ids(home: HomeModel) -> set[str]:
    """The flat itself, without the places the simulator keeps kilometres away.

    The supermarket and the bar are regions the planner needs, not architecture: at twelve metres
    off they decide the viewport and leave the dwelling unreadable in a corner. Rooms are inside by
    definition and a walkable connection carries membership outward, so a balcony reached through a
    hallway is as much part of the flat as the hallway is.
    """
    inside = {item.region_id for item in home.regions if item.kind == "room"}
    walkable = [item for item in home.connections if item.kind != "transit"]
    for _ in range(len(walkable)):
        grew = False
        for connection in walkable:
            if connection.region_a_id in inside and connection.region_b_id not in inside:
                inside.add(connection.region_b_id)
                grew = True
            elif connection.region_b_id in inside and connection.region_a_id not in inside:
                inside.add(connection.region_a_id)
                grew = True
        if not grew:
            break
    return inside


def _region_behind(
    shown: Sequence[HomeRegion], region: HomeRegion, a: Point2D, b: Point2D
) -> str | None:
    """Which shown region, if any, lies on the far side of this edge.

    Both sides are probed and the one still inside the room itself is discarded, so the answer does
    not depend on which way round the polygon happens to be wound.
    """
    length = _length(a.x, a.y, b.x, b.y)
    if length < 1e-9:
        return None
    nx = -(b.y - a.y) / length * PROBE_METERS
    ny = (b.x - a.x) / length * PROBE_METERS
    mid_x, mid_y = (a.x + b.x) / 2, (a.y + b.y) / 2
    inward = point_in_polygon(mid_x + nx, mid_y + ny, region.boundary.vertices)
    x = mid_x - nx if inward else mid_x + nx
    y = mid_y - ny if inward else mid_y + ny
    for other in shown:
        if other.region_id == region.region_id:
            continue
        if point_in_polygon(x, y, other.boundary.vertices):
            return other.region_id
    return None


def plan_walls(home: HomeModel, visible: set[str]) -> list[Wall]:
    """Every wall of the plan, told apart by what stands behind it.

    An edge with a room behind it is a partition, one with nothing behind it is the outside of the
    building, and drawing the two alike is what makes a plan read as a pile of boxes rather than a
    flat.
    """
    shown = [item for item in home.regions if item.region_id in visible]
    pieces: list[Wall] = []
    for region in shown:
        vertices = region.boundary.vertices
        for index, a in enumerate(vertices):
            b = vertices[(index + 1) % len(vertices)]
            # A repeated vertex is a zero-length edge, which is not a wall anyone can draw.
            if _length(a.x, a.y, b.x, b.y) < 1e-9:
                continue
            behind = _region_behind(shown, region, a, b)
            # A partition is walked twice, once from each room it separates; keep one pass.
            if behind is not None and behind < region.region_id:
                continue
            pieces.append(Wall(a.x, a.y, b.x, b.y, exterior=behind is None))
    return pieces


def plan_doors(home: HomeModel, visible: set[str]) -> list[Door]:
    """The doors and passages, as an opening in the wall plus a leaf and its swing.

    A connection declares one point in each room, straddling the wall it crosses: their midpoint is
    where the opening sits and the line between them is its normal, so the opening runs across that,
    as wide as the connection declares.
    """
    doors: list[Door] = []
    for connection in home.connections:
        if connection.kind == "transit":
            continue
        if connection.region_a_id not in visible or connection.region_b_id not in visible:
            continue
        a, b = connection.portal_a, connection.portal_b
        span = _length(a.x, a.y, b.x, b.y)
        if span < 1e-9:
            continue
        nx, ny = (b.x - a.x) / span, (b.y - a.y) / span
        half = connection.width_meters / 2
        cx, cy = (a.x + b.x) / 2, (a.y + b.y) / 2
        x1, y1 = cx + ny * half, cy - nx * half
        doors.append(
            Door(
                opening_id=connection.connection_id,
                kind=connection.kind,
                x1=x1,
                y1=y1,
                x2=cx - ny * half,
                y2=cy + nx * half,
                leaf_x=x1 + nx * connection.width_meters,
                leaf_y=y1 + ny * connection.width_meters,
                width=connection.width_meters,
            )
        )
    return doors


def _on_edge_of(wall: Wall, vertices: Sequence[Point2D]) -> bool:
    """Whether a wall piece lies along one of this polygon's own edges."""
    mid_x, mid_y = (wall.x1 + wall.x2) / 2, (wall.y1 + wall.y2) / 2
    for index, a in enumerate(vertices):
        b = vertices[(index + 1) % len(vertices)]
        length = _length(a.x, a.y, b.x, b.y)
        if length < 1e-9:
            continue
        dx, dy = (b.x - a.x) / length, (b.y - a.y) / length
        along = (mid_x - a.x) * dx + (mid_y - a.y) * dy
        across = abs((mid_x - a.x) * -dy + (mid_y - a.y) * dx)
        if across < 1e-6 and -1e-6 < along < length + 1e-6:
            return True
    return False


def front_door(home: HomeModel, visible: set[str]) -> Door | None:
    """Where the resident actually leaves the flat.

    The model never draws one. Going out is a `transit` connection to a place kept kilometres away,
    and the door itself is an *entity* -- the thing `leave_home` binds to and the entrance contact
    sensor watches -- so the one opening a reader looks for first is the only one missing. It is
    found by what it can do rather than by what it is called, and drawn on the exterior wall of its
    room nearest the point the resident stands at to use it.
    """
    entrance = next(
        (
            item
            for item in home.entities
            if any(
                operation in {"leave_home", "enter_home"}
                for capability in item.capabilities
                for operation in capability.supported_operations
            )
        ),
        None,
    )
    if entrance is None or entrance.region_id not in visible:
        return None
    point = next(
        (
            item
            for item in home.interaction_points
            if item.interaction_point_id == entrance.interaction_point_id
        ),
        None,
    )
    region = next((item for item in home.regions if item.region_id == entrance.region_id), None)
    if point is None or region is None:
        return None

    best: tuple[float, float, float, float, float] | None = None
    for wall in plan_walls(home, visible):
        if not wall.exterior or not _on_edge_of(wall, region.boundary.vertices):
            continue
        length = _length(wall.x1, wall.y1, wall.x2, wall.y2)
        if length < 1.0:
            continue
        dx, dy = (wall.x2 - wall.x1) / length, (wall.y2 - wall.y1) / length
        along = max(
            0.5,
            min(
                length - 0.5,
                (point.position.x - wall.x1) * dx + (point.position.y - wall.y1) * dy,
            ),
        )
        x, y = wall.x1 + dx * along, wall.y1 + dy * along
        distance = _length(point.position.x, point.position.y, x, y)
        if best is not None and distance >= best[4]:
            continue
        # Outward: away from the room the door belongs to.
        inward = point_in_polygon(x - dy * 0.05, y + dx * 0.05, region.boundary.vertices)
        best = (x, y, dy if inward else -dy, -dx if inward else dx, distance)
    if best is None:
        return None

    x, y, nx, ny, _ = best
    width = 0.9
    tx, ty = -ny, nx
    x1, y1 = x - tx * width / 2, y - ty * width / 2
    return Door(
        opening_id=f"front_door_{entrance.entity_id}",
        kind="entrance",
        x1=x1,
        y1=y1,
        x2=x + tx * width / 2,
        y2=y + ty * width / 2,
        leaf_x=x1 + nx * width,
        leaf_y=y1 + ny * width,
        width=width,
    )


def cut_doorways(walls: Iterable[Wall], doors: Sequence[Door]) -> list[Wall]:
    """The walls, minus the openings cut into them.

    Painting a door as a background-coloured line over the wall works until the wall sits over a
    fill or another door, so the hole is taken out of the geometry instead.
    """
    pieces: list[Wall] = []
    for wall in walls:
        length = _length(wall.x1, wall.y1, wall.x2, wall.y2)
        if length < 1e-9:
            continue
        dx, dy = (wall.x2 - wall.x1) / length, (wall.y2 - wall.y1) / length
        cuts: list[tuple[float, float]] = []
        for door in doors:
            ends = ((door.x1, door.y1), (door.x2, door.y2))
            # Only openings lying on this very wall cut it, not ones that cross its line elsewhere.
            if any(abs((x - wall.x1) * -dy + (y - wall.y1) * dx) > 0.06 for x, y in ends):
                continue
            offsets = [(x - wall.x1) * dx + (y - wall.y1) * dy for x, y in ends]
            start, end = max(0.0, min(offsets)), min(length, max(offsets))
            if end > start:
                cuts.append((start, end))
        cursor = 0.0
        for start, end in sorted(cuts):
            if start > cursor:
                pieces.append(
                    Wall(
                        wall.x1 + dx * cursor,
                        wall.y1 + dy * cursor,
                        wall.x1 + dx * start,
                        wall.y1 + dy * start,
                        wall.exterior,
                    )
                )
            cursor = max(cursor, end)
        if cursor < length - 1e-9:
            pieces.append(
                Wall(wall.x1 + dx * cursor, wall.y1 + dy * cursor, wall.x2, wall.y2, wall.exterior)
            )
    return pieces


def _region_caption(region: HomeRegion, raised: bool) -> str:
    """The room's name and its area, sized to the room rather than to the page.

    A caption wider than the room it names points at the wrong place, so the size answers to the
    room; below the point where a name would still be legible the caption is dropped rather than
    drawn across the walls.
    """
    min_x, min_y, max_x, max_y = _box(region.boundary.vertices)
    width, height = max_x - min_x, max_y - min_y
    name = region.region_id.replace("_", " ")
    # 0.55em per glyph is a good enough width estimate for the plan's own typeface.
    size = min(0.34, max(0.14, height * 0.16), width * 0.86 / max(len(name) * 0.55, 1e-6))
    if size < MINIMUM_CAPTION_METERS:
        return ""
    x, y = _centre(region.boundary.vertices)
    # The deployment policy puts a room's temperature sensor at its centre, exactly where the
    # caption sits, so with the sensor layer on the caption moves up rather than through it.
    if raised:
        y -= min(height * 0.22, size * 2.2)
    parts = [
        f'<text x="{_n(x)}" y="{_n(y)}" style="font-size:{_n(size)}px">{html.escape(name)}</text>'
    ]
    if height > size * 3:
        area = polygon_area(region.boundary.vertices)
        parts.append(
            f'<text class="area" x="{_n(x)}" y="{_n(y + size * 1.15)}" '
            f'style="font-size:{_n(size * 0.72)}px">{area:.1f} m²</text>'
        )
    return "".join(parts)


def _sensor_glyph(sensor_type: str) -> str:
    """What each family of sensor looks like on the plan.

    Three identical circles tell a reader nothing: a field of thirty nodes reads as thirty of the
    same thing. Each family gets the shape its own diagrams use -- motion waves, a reed pair, a
    thermometer -- so a glance over the flat says what is watching what.
    """
    if sensor_type == "contact":
        return (
            '<rect class="glyph-solid" x="-.21" y="-.07" width=".17" height=".14" rx=".03"/>'
            '<rect class="glyph-solid" x=".04" y="-.07" width=".17" height=".14" rx=".03"/>'
        )
    if sensor_type == "temperature":
        return (
            '<path class="glyph" d="M-.055 -.22 h.11 v.2 h-.11 z"/>'
            '<circle class="glyph" cx="0" cy=".08" r=".13"/>'
        )
    return (
        '<circle class="glyph-solid" r=".1"/>'
        '<path class="glyph" d="M-.15 -.16 A .22 .22 0 0 0 -.15 .16"/>'
        '<path class="glyph" d="M.15 -.16 A .22 .22 0 0 1 .15 .16"/>'
        '<path class="glyph" d="M-.26 -.28 A .38 .38 0 0 0 -.26 .28"/>'
        '<path class="glyph" d="M.26 -.28 A .38 .38 0 0 1 .26 .28"/>'
    )


def short_sensor_name(sensor_id: str) -> str:
    """`pir_bathroom_4` reads as `bathroom 4` once you know which layer you are looking at."""
    for prefix in ("pir_", "contact_", "temperature_"):
        if sensor_id.startswith(prefix):
            return sensor_id[len(prefix) :].replace("_", " ")
    return sensor_id.replace("_", " ")


def sensor_region_ids(sensor: object, entity_region: dict[str, str]) -> list[str]:
    """Which rooms a sensor belongs to, whichever way its own contract says so."""
    region_ids = getattr(sensor, "region_ids", None)
    if region_ids:
        return list(region_ids)
    region_id = getattr(sensor, "region_id", None)
    if isinstance(region_id, str):
        return [region_id]
    entity_id = getattr(sensor, "entity_id", None)
    if isinstance(entity_id, str) and entity_id in entity_region:
        return [entity_region[entity_id]]
    return []


def _sensor_positions(sensors: Sequence[object]) -> list[tuple[object, tuple[float, float]]]:
    """Where each sensor's glyph goes, nudged apart where two of them share a spot.

    The deployment policy puts a room's temperature sensor at its centre and its PIR very near it,
    so drawn at their declared coordinates the two glyphs land on top of each other and neither can
    be read. The nudge is applied in sensor identifier order and always downward, so the same field
    always produces the same drawing; the declared position stays in the table below the plan,
    which is where a coordinate belongs.
    """
    placed: list[tuple[float, float]] = []
    positions: list[tuple[object, tuple[float, float]]] = []
    for sensor in sorted(sensors, key=lambda item: item.sensor_id):  # type: ignore[attr-defined]
        x, y = sensor.position.x, sensor.position.y  # type: ignore[attr-defined]
        for _ in range(len(placed)):
            if all(_length(x, y, other_x, other_y) > 0.42 for other_x, other_y in placed):
                break
            y += 0.44
        placed.append((x, y))
        positions.append((sensor, (x, y)))
    return positions


def render_plan_svg(home: HomeModel, sensors: SensorModel | None = None) -> str:
    """The whole flat as one inline SVG: rooms, walls, doors, furniture, sensors.

    Coverage is drawn as an outline rather than a wash. Six overlapping translucent fills say
    nothing about any one of them, and unlike the editor a printed page has no selection to narrow
    them down with -- an outline overlaps another outline and stays readable.
    """
    visible = dwelling_region_ids(home)
    regions = [item for item in home.regions if item.region_id in visible]
    if not regions:
        return '<p class="empty">This home model declares no dwelling to draw.</p>'
    entity_region = {item.entity_id: item.region_id for item in home.entities}
    entity_by_obstacle = {f"obstacle_{item.entity_id}": item for item in home.entities}
    shown_sensors = [
        item
        for item in (sensors.sensors if sensors else [])
        if any(region_id in visible for region_id in sensor_region_ids(item, entity_region))
    ]

    vertices = [point for region in regions for point in region.boundary.vertices]
    min_x, min_y, max_x, max_y = _box(vertices)
    min_x, min_y = min_x - MARGIN_METERS, min_y - MARGIN_METERS
    max_x, max_y = max_x + MARGIN_METERS, max_y + MARGIN_METERS
    doors = plan_doors(home, visible)
    entrance = front_door(home, visible)
    if entrance is not None:
        doors = [*doors, entrance]
    walls = cut_doorways(plan_walls(home, visible), doors)

    parts = [
        f'<svg class="plan" viewBox="{_n(min_x)} {_n(min_y)} {_n(max_x - min_x)} '
        f'{_n(max_y - min_y)}" role="img" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="Plan of {html.escape(home.home_id)}: {len(regions)} regions and '
        f'{len(shown_sensors)} sensors">',
        '<defs><pattern id="plan-grid" width="1" height="1" patternUnits="userSpaceOnUse">'
        '<path class="grid" d="M 1 0 L 0 0 0 1"/></pattern>',
        FURNITURE_SYMBOLS,
        "</defs>",
        f'<rect x="{_n(min_x)}" y="{_n(min_y)}" width="{_n(max_x - min_x)}" '
        f'height="{_n(max_y - min_y)}" fill="url(#plan-grid)"/>',
    ]
    parts.extend(
        f'<polygon class="region" points="{_points(region.boundary.vertices)}"/>'
        for region in regions
    )
    for obstacle in home.obstacles:
        if obstacle.region_id not in visible:
            continue
        parts.append(f'<polygon class="obstacle" points="{_points(obstacle.boundary.vertices)}"/>')
        entity = entity_by_obstacle.get(obstacle.obstacle_id)
        symbol = FURNITURE_SYMBOL.get(entity.entity_type if entity else "")
        if symbol is None:
            continue
        box_min_x, box_min_y, box_max_x, box_max_y = _box(obstacle.boundary.vertices)
        parts.append(
            f'<use class="furniture" href="#furn-{symbol}" x="{_n(box_min_x)}" '
            f'y="{_n(box_min_y)}" width="{_n(box_max_x - box_min_x)}" '
            f'height="{_n(box_max_y - box_min_y)}" preserveAspectRatio="xMidYMid meet"/>'
        )
    for wall in walls:
        kind = "wall-exterior" if wall.exterior else "wall-partition"
        parts.append(
            f'<line class="wall {kind}" x1="{_n(wall.x1)}" y1="{_n(wall.y1)}" '
            f'x2="{_n(wall.x2)}" y2="{_n(wall.y2)}"/>'
        )
    for door in doors:
        if door.kind == "passage":
            continue
        parts.append(
            f'<path class="door-swing" d="M {_n(door.leaf_x)} {_n(door.leaf_y)} '
            f'A {_n(door.width)} {_n(door.width)} 0 0 1 {_n(door.x2)} {_n(door.y2)}"/>'
            f'<line class="door-leaf" x1="{_n(door.x1)}" y1="{_n(door.y1)}" '
            f'x2="{_n(door.leaf_x)}" y2="{_n(door.leaf_y)}"/>'
        )
        if door.kind == "entrance":
            parts.append(
                f'<text class="door-caption" '
                f'x="{_n((door.x1 + door.x2) / 2 + (door.leaf_x - door.x1) * 0.6)}" '
                f'y="{_n((door.y1 + door.y2) / 2 + (door.leaf_y - door.y1) * 0.6)}">'
                "Front door</text>"
            )
    parts.extend(_region_caption(region, raised=bool(shown_sensors)) for region in regions)
    for sensor in shown_sensors:
        coverage = getattr(sensor, "coverage", None)
        if coverage is not None:
            parts.append(f'<polygon class="coverage" points="{_points(coverage.vertices)}"/>')
    for sensor, (x, y) in _sensor_positions(shown_sensors):
        parts.append(
            f'<g class="sensor sensor-{html.escape(sensor.sensor_type)}" '
            f'transform="translate({_n(x)} {_n(y)})">'
            f"{_sensor_glyph(sensor.sensor_type)}"
            f'<text class="sensor-name" x=".3" y=".1">'
            f"{html.escape(short_sensor_name(sensor.sensor_id))}</text></g>"
        )
    parts.append("</svg>")
    return "".join(parts)
