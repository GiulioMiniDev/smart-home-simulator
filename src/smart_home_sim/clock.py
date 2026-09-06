"""Putting the right offset on an instant, for everything downstream of the compiler.

The compiler resolves its own time axis against the scenario's zone and has since M2
(`TimeAxis.to_datetime`). The engine and the sensor projector did not, and both build timestamps
by adding a timedelta to a base they were handed once — which is where the offset got stuck.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def localised(moment: datetime, zone: ZoneInfo) -> datetime:
    """The same instant, wearing the offset its zone was actually on at that instant.

    `simulation_window.start` parses to a *fixed* offset — `timezone(timedelta(seconds=7200))` for
    a scenario that starts in Italian summer time — and adding a timedelta to a fixed offset keeps
    that offset forever. So a five-month run begun in September wrote `+02:00` on all 440,427 of
    its observations, straight through the change of 25 October: the instants were right and the
    wall clock every consumer reads off them was an hour late for 102 of 153 days. The plan was
    always correct next to it (`2026-10-26T05:51:00+01:00` planned, `06:51:00+02:00` executed), so
    the two disagreed inside one row of the same export.

    Resolved back to a fixed offset rather than left wearing the `ZoneInfo` itself, which is the
    one thing that separates this from `TimeAxis.to_datetime`. Arithmetic on a `ZoneInfo`-aware
    datetime is *wall-clock* arithmetic — `dt + timedelta(hours=1)` across a fall-back advances the
    instant by two — and the sensor projector adds latency, jitter and hold to every timestamp it
    reads out of the trace. A fixed offset has no discontinuity to fall into, so those additions
    stay instant arithmetic; the two render to the same string anyway, and a fixed offset is also
    exactly what the trace becomes after a JSON round-trip, so an in-process pipeline and a run
    resumed from file come to the same answer.
    """
    local = moment.astimezone(zone)
    return local.replace(tzinfo=timezone(local.utcoffset() or timedelta()))
