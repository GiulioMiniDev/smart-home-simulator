from __future__ import annotations

from datetime import UTC, datetime

import pytest

from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar, CalendarDay, HabitOccurrence
from smart_home_sim.hybrid_planning.habit_trace import build_planned_trace
from smart_home_sim.hybrid_planning.habits import HabitKind, Weekday

_NOW = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _occ(label: str, target: str) -> HabitOccurrence:
    return HabitOccurrence(
        habit_id=label.replace(" ", "_"),
        label=label,
        kind=HabitKind.anchor,
        target_time=target,
        window_start="06:00",
        window_end="22:00",
    )


def _calendar() -> CadenceCalendar:
    days = [
        CalendarDay(
            date="2026-08-03",
            weekday=Weekday.monday,
            occurrences=[_occ("morning coffee", "07:10"), _occ("evening pill", "20:00")],
        ),
        CalendarDay(
            date="2026-08-04", weekday=Weekday.tuesday, occurrences=[_occ("groceries", "10:30")]
        ),
    ]
    return CadenceCalendar(
        calendar_id="cal",
        persona_id="luigi_bianchi",
        profile_id="luigi_bianchi_profile",
        start_date="2026-08-03",
        end_date="2026-08-04",
        months=1,
        seed=1,
        timezone="Europe/Rome",
        days=days,
        provenance=Provenance(author_type=AuthorType.rule_generator, generated_at=_NOW),
    )


def test_build_planned_trace_maps_habits_to_intents() -> None:
    trace = build_planned_trace(_calendar(), now=_NOW)
    assert trace.trace_id == "luigi_bianchi_planned_trace"
    assert trace.persona_id == "luigi_bianchi"
    assert trace.profile_id == "luigi_bianchi_profile"
    resolved = {(entry.date, entry.label): entry.intent for entry in trace.entries}
    assert resolved[("2026-08-03", "morning coffee")] == "eat_breakfast"
    assert resolved[("2026-08-03", "evening pill")] == "take_morning_medication"
    assert resolved[("2026-08-04", "groceries")] == "buy_groceries"
    assert len(trace.entries) == 3
    assert trace.provenance.author_type is AuthorType.rule_generator


def test_build_planned_trace_slice() -> None:
    trace = build_planned_trace(_calendar(), start_index=1, days=1, now=_NOW)
    assert {entry.date for entry in trace.entries} == {"2026-08-04"}


def test_build_planned_trace_empty_raises() -> None:
    with pytest.raises(ValueError):
        build_planned_trace(_calendar(), start_index=9)
