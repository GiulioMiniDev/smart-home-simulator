"""How far one occurrence of a routine strays from the moment the resident usually keeps.

Two places need this quantity and both used to draw it from a bounded distribution:
`expander._wobble` took a uniform inside the habit's declared `jitter_minutes`, and `drives.advance`
took a narrow Gaussian around the chronotype. Both produced a resident far more punctual than a
real one.

The night is the cleanest occurrence to compare, because there is exactly one per day and no
question of which one to count. Against CASAS Aruba, taking each logical day's longest `Sleeping`
segment — the night itself, rather than one of the two or three fragments the annotation splits it
into when the resident gets up:

| | circular dispersion | within an hour of the typical time |
|---|---:|---:|
| Aruba | 85 min | 60% |
| generated | 36 min | 96% |

The gap is not only amplitude, which is why widening `jitter_minutes` does not close it. A bounded
draw is bounded: reaching 85 minutes with a uniform needs a band so wide the habit has no typical
moment left, and the resident goes to bed at random. What the real log shows instead is a narrow
body with a thin tail — almost always the same hour, occasionally an hour with nothing to do with
it.

So the stray is a two-component mixture: a common component of the width the caller declares, and a
rare component several times wider. The second component's two numbers are a fact about people
rather than about any one habit, which is why they are constants here instead of fields in the
outline, where the model writing it would have to invent a plausible pair per recurring activity.
"""

from __future__ import annotations

import random

# How often an occurrence lands in the tail rather than the body. Roughly one day a week, which is
# what "she is usually punctual, but not always" amounts to when counted.
EXCEPTION_PROBABILITY = 0.15
# How much wider the tail is than the body. Calibrated so that the pair reproduces Aruba's bedtime
# together: the mixture's standard deviation is `sqrt(1 - p + p * k**2)` times the body's, and it
# keeps about 65% of occurrences within an hour of the typical moment against Aruba's 60%.
EXCEPTION_WIDTH_MULTIPLE = 3.5


def stray_minutes(rng: random.Random, typical_minutes: float) -> float:
    """Minutes either side of the typical moment, from the narrow body or the rare wide tail.

    ``typical_minutes`` is the standard deviation of the body, not a bound: the draw is Gaussian and
    the caller clamps it to whatever the day can actually hold.
    """
    if typical_minutes <= 0:
        return 0.0
    width = typical_minutes
    if rng.random() < EXCEPTION_PROBABILITY:
        width *= EXCEPTION_WIDTH_MULTIPLE
    return rng.gauss(0, width)


def fold_into(value: float, floor: float, ceiling: float) -> float:
    """Reflect ``value`` into ``[floor, ceiling]`` instead of piling it up on the nearer edge.

    A hard `min`/`max` turns every draw past an edge into the same number. On the night that is not
    a rounding detail: Giulia's outline declares a 23:30 chronotype, and against the 23:50 ceiling
    the engine used to enforce, clamping put **109 of 365 nights on exactly 23:50** and left the
    whole year inside 22:35-23:57. Reflecting spends the same mass on distinguishable evenings.

    Both edges reflect, and repeatedly, because one reflection off the ceiling can overshoot the
    floor when the tail is several times wider than the interval.
    """
    if ceiling <= floor:
        return floor
    span = ceiling - floor
    offset = (value - floor) % (2 * span)
    return floor + (offset if offset <= span else 2 * span - offset)


__all__ = ["EXCEPTION_PROBABILITY", "EXCEPTION_WIDTH_MULTIPLE", "fold_into", "stray_minutes"]
