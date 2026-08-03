"""The planned habit-mining ground truth: which habit is due when, over the horizon.

Derived deterministically from the frozen cadence calendar (no LLM, no simulation): each
due activity
occurrence becomes a trace entry with its date, target time, kind, and the canonical intent that
expresses it. This is the *planned* trace, known before simulation; the *realized* trace (what
actually occurred) is recovered later from the simulation's oracle mapping. Kept as a separate
artifact so mining precision/recall can be scored without leaking labels into the sensor data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import AuthorType, Provenance
from smart_home_sim.hybrid_planning.cadence import CadenceCalendar
from smart_home_sim.hybrid_planning.day_generation import label_to_intent
from smart_home_sim.hybrid_planning.recurring_activities import RecurringActivityKind

GENERATOR_NAME = "smart-home-sim.hybrid_planning.activity_trace"
GENERATOR_VERSION = "1.0.0"


class ActivityTraceEntry(ContractModel):
    date: str
    recurring_activity_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: RecurringActivityKind
    target_time: str
    intent: str = Field(min_length=1)


class PlannedActivityTrace(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["planned_activity_trace"] = "planned_activity_trace"
    trace_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    entries: list[ActivityTraceEntry] = Field(default_factory=list)
    provenance: Provenance


def build_planned_trace(
    calendar: CadenceCalendar,
    *,
    start_index: int = 0,
    days: int | None = None,
    now: datetime | None = None,
) -> PlannedActivityTrace:
    """Expand the calendar's due recurring activities over the horizon slice into a planned ground-
    truth trace."""
    limit = len(calendar.days) if days is None else start_index + days
    day_slice = calendar.days[start_index:limit]
    if not day_slice:
        raise ValueError("requested calendar slice is empty")

    entries = [
        ActivityTraceEntry(
            date=day.date,
            recurring_activity_id=occurrence.recurring_activity_id,
            label=occurrence.label,
            kind=occurrence.kind,
            target_time=occurrence.target_time,
            intent=label_to_intent(occurrence.label, occurrence.kind.value),
        )
        for day in day_slice
        for occurrence in day.occurrences
    ]
    return PlannedActivityTrace(
        trace_id=f"{calendar.persona_id}_planned_trace",
        persona_id=calendar.persona_id,
        profile_id=calendar.profile_id,
        entries=entries,
        provenance=Provenance(
            author_type=AuthorType.rule_generator,
            generator_name=GENERATOR_NAME,
            generator_version=GENERATOR_VERSION,
            generated_at=now or datetime.now(UTC),
        ),
    )
