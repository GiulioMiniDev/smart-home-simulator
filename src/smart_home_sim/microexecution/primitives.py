from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Primitive:
    label: str
    room: str
    duration_minutes: float
    movement_interval_seconds: float | None
