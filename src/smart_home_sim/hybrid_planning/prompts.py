from __future__ import annotations

import json

from smart_home_sim.domain.behavior import ActivityCatalog
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    PlanningCase,
    PlanningMemory,
    WeeklyBrief,
    WeeklyDayBrief,
)

SYSTEM_PROMPT = """You are the semantic planning component of a hybrid smart-home planner.
Create plausible synthetic plans that stay faithful to the supplied profile while making days
meaningfully different. You choose intentions, ordering, rough time bands, optionality and
rationale. Never emit exact timestamps, trajectories, sensor events, environment changes or
claims about executed state. Use only the supplied intent and location identifiers. Return only
the JSON object required by the response schema."""


def _catalog_payload(catalog: ActivityCatalog) -> list[dict[str, str]]:
    return [
        {
            "intent": item.intent,
            "category": item.category,
        }
        for item in catalog.activities
    ]


def _case_payload(planning_case: PlanningCase) -> dict[str, object]:
    return {
        "resident": planning_case.resident.model_dump(mode="json", by_alias=True),
        "planningWindow": planning_case.planning_window.model_dump(mode="json", by_alias=True),
        "timeZone": planning_case.time_zone,
        "calendar": [
            planning_case.calendar_day(value).model_dump(mode="json", by_alias=True)
            for value in planning_case.dates()
        ],
        "locations": [
            item.model_dump(mode="json", by_alias=True) for item in planning_case.locations
        ],
        "resources": [
            item.model_dump(mode="json", by_alias=True) for item in planning_case.resources
        ],
        "routineRequirements": [
            item.model_dump(mode="json", by_alias=True)
            for item in planning_case.routine_requirements
        ],
        "contextNotes": planning_case.context_notes,
    }


def weekly_prompt(planning_case: PlanningCase, _catalog: ActivityCatalog) -> str:
    payload = {"case": _case_payload(planning_case)}
    return f"""Design the narrative structure for this planning window.

Make workdays and weekends structurally different. Preserve recurring necessities, but vary
leisure, domestic, social and errand choices. Give every day at least one distinctive goal.
Do not treat an available location or resource as evidence that an event must happen.
Do not invent named relationships that the case does not support.

The days array must contain exactly these dates in order:
{json.dumps([item.isoformat() for item in planning_case.dates()])}

Authoritative planning input:
{json.dumps(payload, ensure_ascii=False, indent=2)}"""


def daily_prompt(
    planning_case: PlanningCase,
    catalog: ActivityCatalog,
    weekly_brief: WeeklyBrief,
    day_brief: WeeklyDayBrief,
    memory: PlanningMemory,
) -> str:
    payload = {
        "case": _case_payload(planning_case),
        "weeklyBrief": weekly_brief.model_dump(mode="json", by_alias=True),
        "dayBrief": day_brief.model_dump(mode="json", by_alias=True),
        "planningMemory": memory.model_dump(mode="json", by_alias=True),
        "allowedActivities": _catalog_payload(catalog),
        "durationClasses": {
            "brief": "about 15 minutes",
            "short": "about 30 minutes",
            "medium": "about 60 minutes",
            "long": "about 2 hours",
            "extended": "about 8 hours",
        },
    }
    return f"""Propose one day for {day_brief.date.isoformat()}.

Return 6 to 12 activities in meaningful daily order. Include basic daily continuity where
appropriate, but do not copy the recent-day sequence. Use rough time bands and duration classes;
the deterministic simulator will assign exact times. Long activities consume later bands, so keep
the day feasible. Use the exact requested date and only supplied identifiers. The deterministic
materializer assigns the authoritative duration of sleep and work shifts; do not use `extended`
yourself. A morning work shift becomes a full shift; a later shift uses your requested class.
Every applicable routine requirement is mandatory, including its time band and occurrence bounds.

Planning input:
{json.dumps(payload, ensure_ascii=False, indent=2)}"""


def diversity_repair_prompt(
    planning_case: PlanningCase,
    catalog: ActivityCatalog,
    weekly_brief: WeeklyBrief,
    proposal: DailyProposal,
    all_proposals: list[DailyProposal],
    reasons: list[str],
) -> str:
    other_days = [item for item in all_proposals if item.date != proposal.date]
    payload = {
        "case": _case_payload(planning_case),
        "weeklyBrief": weekly_brief.model_dump(mode="json", by_alias=True),
        "proposalToRevise": proposal.model_dump(mode="json", by_alias=True),
        "otherAcceptedDays": [item.model_dump(mode="json", by_alias=True) for item in other_days],
        "diversityFailures": reasons,
        "allowedActivities": _catalog_payload(catalog),
    }
    return f"""Revise only the proposed day below because the week is too repetitive.

Keep the same resident, date, plausible necessities and weekly narrative. Change optional choices,
sequence or rough time bands enough to create meaningful semantic variety. Do not make random or
implausible changes merely to differ. Return the complete replacement day.

Revision input:
{json.dumps(payload, ensure_ascii=False, indent=2)}"""


def structural_repair_prompt(
    planning_case: PlanningCase,
    catalog: ActivityCatalog,
    weekly_brief: WeeklyBrief,
    proposal: DailyProposal,
    error: str,
) -> str:
    payload = {
        "case": _case_payload(planning_case),
        "weeklyBrief": weekly_brief.model_dump(mode="json", by_alias=True),
        "rejectedProposal": proposal.model_dump(mode="json", by_alias=True),
        "validationError": error,
        "allowedActivities": _catalog_payload(catalog),
    }
    return f"""Repair the rejected daily proposal below.

Resolve the validation error using only exact supplied intent and location identifiers. Preserve
the date, narrative and every unrelated valid choice. Return the complete replacement day, not a
patch or explanation. Do not silently reinterpret the error.

Repair input:
{json.dumps(payload, ensure_ascii=False, indent=2)}"""
