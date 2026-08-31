"""Where on a piece of furniture a body actually rests.

An interaction point is where somebody *stands* to use a thing. It has to be: it is the point the
router walks to, and the router may only ever put a body on free floor. For a fridge that is the
whole story. For a bed it is the carpet beside it, and a resident recorded as asleep for eight
hours is recorded as asleep standing next to her own bed.

A berth is the other half of the answer: the place on the piece the body occupies once it has
stopped being a body that walks. Deliberately inside the footprint, which is why it is a separate
idea and not a correction to the interaction point — the two answer different questions and only
one of them may be handed to `plan_path`.

They come in more than one to a piece on purpose. Two people share a double bed and a sofa seats
three, and a model that cannot say which side of the bed each of them is on cannot answer the
question a multi-resident home is for.
"""

from __future__ import annotations

from dataclasses import dataclass

from smart_home_sim.domain.environment import Point2D, Polygon2D

# What one body takes up, across the axis the occupants are ranged along. Lying takes a shoulder
# width and a little room to turn over; sitting takes a seat.
_LYING_WIDTH_METRES = 0.62
_SEATED_WIDTH_METRES = 0.55
# Below this a piece is not shared, whatever the arithmetic says: a two-seat bench that two bodies
# can technically be squeezed onto is still one place to sit as far as a plan is concerned.
_MINIMUM_SHARE_METRES = 1.05


@dataclass(frozen=True)
class Footprint:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @classmethod
    def of(cls, boundary: Polygon2D) -> Footprint:
        xs = [vertex.x for vertex in boundary.vertices]
        ys = [vertex.y for vertex in boundary.vertices]
        return cls(min(xs), min(ys), max(xs), max(ys))

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def depth(self) -> float:
        return self.max_y - self.min_y


def berths(boundary: Polygon2D, *, lying: bool) -> list[Point2D]:
    """Every place a body can rest on this piece, in a fixed order.

    Bodies are ranged along different axes depending on what they are doing on it. Lying, they run
    the length of the piece and lie side by side across its width, so it is the short side that is
    divided. Sitting, they take up almost no depth and sit shoulder to shoulder along the long one.
    A single berth is the middle of the piece, which is what a chair and a single bed both want.

    Deterministic in the geometry alone: no seed, nothing to tie-break, the same answer every run.
    """
    box = Footprint.of(boundary)
    horizontal = box.width >= box.depth
    # The axis the occupants are ranged along: across the piece for lying, along it for sitting.
    ranged_horizontally = horizontal if not lying else not horizontal
    span = box.width if ranged_horizontally else box.depth
    room_for = _LYING_WIDTH_METRES if lying else _SEATED_WIDTH_METRES
    places = 1 if span < _MINIMUM_SHARE_METRES else max(1, int(span // room_for))

    centre_x = (box.min_x + box.max_x) / 2
    centre_y = (box.min_y + box.max_y) / 2
    if places == 1:
        return [Point2D(x=round(centre_x, 4), y=round(centre_y, 4))]

    low = box.min_x if ranged_horizontally else box.min_y
    step = span / places
    return [
        Point2D(
            x=round(low + step * (index + 0.5) if ranged_horizontally else centre_x, 4),
            y=round(centre_y if ranged_horizontally else low + step * (index + 0.5), 4),
        )
        for index in range(places)
    ]


def berth_for(boundary: Polygon2D, *, lying: bool, occupant: int) -> Point2D:
    """The berth this occupant takes, counting from the first and wrapping round.

    Wrapping rather than refusing: a fourth body on a three-seat sofa is a crowded sofa, not a
    simulation that cannot continue. Who gets which index is the caller's business — it is the
    thing that has to stay stable for a resident across a night, not something geometry knows.
    """
    places = berths(boundary, lying=lying)
    return places[occupant % len(places)]
