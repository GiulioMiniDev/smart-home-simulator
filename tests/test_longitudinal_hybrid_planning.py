from __future__ import annotations

from datetime import date
from pathlib import Path

from smart_home_sim.hybrid_planning.longitudinal import (
    one_month_end,
    slice_planning_case,
)
from smart_home_sim.hybrid_planning.service import _read_models

ROOT = Path(__file__).parents[1]
CASE = ROOT / "examples/hybrid/tommaso_bianchi_week.planning-case.json"


def test_one_month_end_clamps_day_for_shorter_month() -> None:
    assert one_month_end(date(2026, 1, 31)) == date(2026, 2, 28)
    assert one_month_end(date(2028, 1, 31)) == date(2028, 2, 29)
    assert one_month_end(date(2026, 8, 10)) == date(2026, 9, 10)


def test_slice_planning_case_covers_month_without_gaps() -> None:
    planning_case, _ = _read_models(CASE)

    chunks = slice_planning_case(
        planning_case,
        end_exclusive=date(2026, 9, 10),
        chunk_days=7,
    )

    assert [len(item.dates()) for item in chunks] == [7, 7, 7, 7, 3]
    dates = [value for chunk in chunks for value in chunk.dates()]
    assert dates == [
        date.fromordinal(date(2026, 8, 10).toordinal() + offset)
        for offset in range(31)
    ]
    assert all(chunk.case_id == planning_case.case_id for chunk in chunks)
    assert all(chunk.initial_state.at == chunk.planning_window.start for chunk in chunks)
