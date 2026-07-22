from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from smart_home_sim.domain.models import (
    Activity,
    AuthorType,
    DateTimeWindow,
    DayContext,
    DayPlan,
    DurationRange,
    Provenance,
    Scenario,
)
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    DurationClass,
    HybridPlanningConfig,
    PlanningCase,
    TimeBand,
)

BAND_START = {
    TimeBand.early_morning: time(6, 0),
    TimeBand.morning: time(8, 0),
    TimeBand.midday: time(12, 0),
    TimeBand.afternoon: time(14, 0),
    TimeBand.evening: time(18, 0),
    TimeBand.night: time(21, 30),
}
BAND_ORDER = {value: index for index, value in enumerate(TimeBand)}
DURATIONS = {
    DurationClass.brief: (10, 15, 20),
    DurationClass.short: (20, 30, 45),
    DurationClass.medium: (45, 60, 90),
    DurationClass.long: (90, 120, 180),
    DurationClass.extended: (360, 480, 540),
}


def materialize_scenario(
    planning_case: PlanningCase,
    proposals: list[DailyProposal],
    config: HybridPlanningConfig,
    generated_at: datetime,
) -> Scenario:
    expected_dates = planning_case.dates()
    if [item.date for item in proposals] != expected_dates:
        raise ValueError("daily proposals must cover the planning window in date order")
    days: list[DayPlan] = []
    for day_proposal in proposals:
        activities = materialize_day_activities(
            planning_case,
            day_proposal,
            final_date=expected_dates[-1],
        )
        calendar_day = planning_case.calendar_day(day_proposal.date)
        days.append(
            DayPlan(
                date=day_proposal.date,
                context=DayContext(
                    day_type=calendar_day.day_type,
                    narrative_intent=day_proposal.narrative_intent,
                    facts={"calendarNotes": calendar_day.notes},
                ),
                activities=activities,
            )
        )
    return Scenario(
        schema_version="1.0.0",
        scenario_id=f"hybrid_{planning_case.case_id}",
        title=(
            "Hybrid plan for "
            f"{planning_case.resident.display_name or planning_case.resident.resident_id}"
        ),
        language=planning_case.language,
        time_zone=planning_case.time_zone,
        simulation_window=planning_case.planning_window,
        seed=planning_case.seed,
        provenance=Provenance(
            author_type=AuthorType.external_llm,
            generator_name="smart-home-simulator-hybrid-planner",
            generator_version="0.1.0",
            model_name=config.model,
            prompt_template_version="hybrid-planning-0.1.0",
            generated_at=generated_at,
            human_reviewed=False,
            parameters={
                "temperature": config.temperature,
                "topP": config.top_p,
                "planningSeed": planning_case.seed,
            },
        ),
        model_references=planning_case.model_references,
        residents=[planning_case.resident],
        locations=planning_case.locations,
        resources=planning_case.resources,
        initial_state=planning_case.initial_state,
        days=days,
        declared_constraints=[
            "LLM proposals select semantic activities and rough time bands only.",
            "Exact timestamps are materialized and compiled deterministically.",
        ],
        extensions={
            "hybridPlanning": {
                "caseId": planning_case.case_id,
                "executionPerformed": False,
            }
        },
    )


def materialize_day_activities(
    planning_case: PlanningCase,
    day_proposal: DailyProposal,
    *,
    final_date: object,
) -> list[Activity]:
    locations = {item.location_id for item in planning_case.locations}
    zone = ZoneInfo(planning_case.time_zone)
    activities: list[Activity] = []
    cursor = datetime.combine(day_proposal.date, time(0), zone)
    ordered = sorted(
        enumerate(day_proposal.activities),
        key=lambda item: (BAND_ORDER[item[1].time_band], item[0]),
    )
    for sequence, (_, proposed) in enumerate(ordered, start=1):
        if proposed.location_id not in locations:
            raise ValueError(f"unknown proposed location: {proposed.location_id}")
        anchor = datetime.combine(day_proposal.date, BAND_START[proposed.time_band], zone)
        preferred = max(anchor, cursor)
        next_midnight = datetime.combine(day_proposal.date + timedelta(days=1), time(0), zone)
        if preferred >= next_midnight:
            raise ValueError(f"activities overflow day {day_proposal.date}")
        full_work_shift = proposed.intent == "work_shift" and proposed.time_band in {
            TimeBand.early_morning,
            TimeBand.morning,
        }
        duration_class = (
            DurationClass.extended
            if proposed.intent == "sleep" or full_work_shift
            else proposed.duration_class
        )
        minimum, typical, maximum = DURATIONS[duration_class]
        earliest = max(
            datetime.combine(day_proposal.date, time(0), zone),
            preferred - timedelta(minutes=15),
        )
        latest = min(next_midnight - timedelta(minutes=1), preferred + timedelta(minutes=30))
        activities.append(
            Activity(
                activity_id=f"hybrid_{day_proposal.date:%Y%m%d}_{sequence:02d}",
                actor_id=planning_case.resident.resident_id,
                intent=proposed.intent,
                location_ids=[proposed.location_id],
                start_window=DateTimeWindow(
                    earliest=earliest,
                    preferred=preferred,
                    latest=latest,
                ),
                duration=DurationRange(
                    minimum_minutes=minimum,
                    preferred_minutes=typical,
                    maximum_minutes=maximum,
                ),
                mandatory=proposed.mandatory,
                priority=proposed.priority,
                allow_boundary_truncation=(
                    day_proposal.date == final_date
                    and preferred + timedelta(minutes=maximum)
                    > planning_case.planning_window.end
                ),
                labels=["hybrid-planning", proposed.time_band.value],
                extensions={"rationale": proposed.rationale},
            )
        )
        cursor = preferred + timedelta(minutes=typical + 10)
    return activities
