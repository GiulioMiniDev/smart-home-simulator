from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from smart_home_sim.domain.models import SimulationWindow
from smart_home_sim.hybrid_planning.models import PlanningCase


def one_month_end(start: date) -> date:
    year = start.year + (1 if start.month == 12 else 0)
    month = 1 if start.month == 12 else start.month + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


def slice_planning_case(
    base: PlanningCase,
    *,
    end_exclusive: date,
    chunk_days: int,
) -> list[PlanningCase]:
    if not 1 <= chunk_days <= 7:
        raise ValueError("chunk_days must be between 1 and 7")
    start = base.dates()[0]
    if end_exclusive <= start:
        raise ValueError("end_exclusive must be after planning start")
    zone = ZoneInfo(base.time_zone)
    chunks: list[PlanningCase] = []
    current = start
    while current < end_exclusive:
        chunk_end = min(current + timedelta(days=chunk_days), end_exclusive)
        start_at = datetime.combine(current, time.min, tzinfo=zone)
        end_at = datetime.combine(chunk_end, time.min, tzinfo=zone)
        calendar = [item for item in base.calendar if current <= item.date < chunk_end]
        chunks.append(
            base.model_copy(
                update={
                    "planning_window": SimulationWindow(
                        start=start_at,
                        end=end_at,
                    ),
                    "initial_state": base.initial_state.model_copy(
                        update={"at": start_at}
                    ),
                    "calendar": calendar,
                }
            )
        )
        current = chunk_end
    return chunks
