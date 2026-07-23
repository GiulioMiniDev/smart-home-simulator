from __future__ import annotations

from datetime import date, timedelta

from test_behavioral_profile import CASE, valid_profile

from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
)
from smart_home_sim.hybrid_planning.habit_gates import (
    constrain_daily_habit_limits,
    derive_habit_budget,
    evaluate_habit_plan,
    initial_habit_ledger,
    planned_habit_trace,
    update_habit_ledger,
)
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    DurationClass,
    ProposedActivity,
    TimeBand,
    WeeklyBrief,
    WeeklyDayBrief,
)
from smart_home_sim.hybrid_planning.service import _read_models


def activity(intent: str, location: str, band: TimeBand) -> ProposedActivity:
    return ProposedActivity(
        intent=intent,
        location_id=location,
        time_band=band,
        duration_class=DurationClass.brief,
        mandatory=True,
        priority=80,
        rationale=f"A planned occurrence of {intent}.",
    )


def proposals(*, broken: bool = False) -> list[DailyProposal]:
    start = date(2026, 8, 10)
    result: list[DailyProposal] = []
    for index in range(7):
        value = start + timedelta(days=index)
        activities = [
            activity("wake_up", "bedroom_01", TimeBand.early_morning),
            activity(
                "take_morning_medication",
                "bedroom_01",
                TimeBand.early_morning,
            ),
        ]
        if value.weekday() < 5:
            activities.append(activity("work_shift", "garden_workplace", TimeBand.morning))
        activities.extend(
            [
                activity("read", "living_room_01", TimeBand.evening),
                activity("sleep", "bedroom_01", TimeBand.night),
            ]
        )
        if broken and index in {5, 6}:
            activities.insert(
                -1,
                activity(
                    "visit_mother_and_have_dinner",
                    "mother_house_barcelona",
                    TimeBand.evening,
                ),
            )
        if broken and index == 0:
            activities = [
                item for item in activities if item.intent != "take_morning_medication"
            ]
        result.append(
            DailyProposal(
                date=value,
                narrative_intent=f"Habit test day {index + 1}",
                activities=activities,
            )
        )
    return result


def weekly_brief() -> WeeklyBrief:
    start = date(2026, 8, 10)
    return WeeklyBrief(
        week_theme="Stable habits with controlled variation",
        variety_strategy=["preserve anchors", "vary optional leisure"],
        days=[
            WeeklyDayBrief(
                date=start + timedelta(days=index),
                day_type="workday" if index < 5 else "weekend",
                narrative_intent=f"Day {index + 1}",
                distinctive_goals=["Complete the planned distinctive activity"],
                goal_intents=["buy_groceries"] if index == 5 else ["read"],
            )
            for index in range(7)
        ],
    )


def test_daily_constraint_removes_non_anchor_cooldown_repetition() -> None:
    profile, _, ledger, budget = context()
    days = proposals()
    mother = activity(
        "visit_mother_and_have_dinner",
        "mother_house_barcelona",
        TimeBand.evening,
    )
    saturday = days[5].model_copy(update={"activities": [*days[5].activities, mother]})
    sunday = days[6].model_copy(update={"activities": [*days[6].activities, mother]})

    constrained, changes = constrain_daily_habit_limits(
        profile,
        ledger,
        budget,
        [saturday],
        sunday,
    )

    intents = [item.intent for item in constrained.activities]
    assert "visit_mother_and_have_dinner" not in intents
    assert "take_morning_medication" in intents
    assert any(item["reason"] == "maximum_occurrences" for item in changes)

    compact = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="A sparse day after invalid repetitions are removed",
        activities=[
            activity("take_morning_medication", "bedroom_01", TimeBand.early_morning),
            mother,
            mother,
            activity("sleep", "bedroom_01", TimeBand.night),
        ],
    )
    compact, _ = constrain_daily_habit_limits(
        profile,
        ledger,
        budget,
        [saturday],
        compact,
    )
    assert [item.intent for item in compact.activities] == [
        "take_morning_medication",
        "sleep",
    ]


def context():
    profile = valid_profile()
    digest = behavioral_profile_digest(profile)
    ledger = initial_habit_ledger(digest, profile)
    planning_case, _ = _read_models(CASE)
    dates = planning_case.dates()
    budget = derive_habit_budget(
        profile,
        ledger,
        dates,
        {value: planning_case.calendar_day(value).day_type for value in dates},
    )
    return profile, digest, ledger, budget


def test_budget_turns_cadence_into_chunk_counts() -> None:
    _, _, _, budget = context()
    items = {item.intent: item for item in budget.items}
    assert items["take_morning_medication"].required_occurrences == 7
    assert items["work_shift"].required_occurrences == 5
    assert items["visit_mother_and_have_dinner"].maximum_occurrences == 1


def test_rare_habit_maximum_is_consumed_across_weekly_chunks() -> None:
    profile = valid_profile()
    rare = profile.habits[-1].model_copy(
        update={
            "cadence": profile.habits[-1].cadence.model_copy(
                update={"maximum_occurrences": 1, "period_days": 365}
            )
        }
    )
    profile = profile.model_copy(update={"habits": [*profile.habits[:-1], rare]})
    digest = behavioral_profile_digest(profile)
    ledger = initial_habit_ledger(digest, profile)
    first_week = proposals()
    first_week[0] = first_week[0].model_copy(
        update={
            "activities": [
                *first_week[0].activities,
                activity("collect_medication_refill", "pharmacy_barcelona", TimeBand.afternoon),
            ]
        }
    )
    ledger = update_habit_ledger(profile, digest, ledger, first_week)
    next_dates = [date(2026, 8, 17) + timedelta(days=index) for index in range(7)]
    budget = derive_habit_budget(
        profile,
        ledger,
        next_dates,
        {
            value: "workday" if value.weekday() < 5 else "weekend"
            for value in next_dates
        },
    )

    rare_budget = next(item for item in budget.items if item.habit_id == rare.habit_id)
    assert rare_budget.maximum_occurrences == 0


def test_gate_reports_missing_anchor_chain_cooldown_and_goal() -> None:
    profile, _, ledger, budget = context()
    report = evaluate_habit_plan(
        profile,
        ledger,
        budget,
        weekly_brief(),
        proposals(broken=True),
    )
    assert {item.code for item in report.violations} >= {
        "HABIT_REQUIRED_MISSING",
        "HABIT_DAILY_ANCHOR_MISSING",
        "HABIT_CHAIN_PREDECESSOR_MISSING",
        "HABIT_CHAIN_SUCCESSOR_MISSING",
        "HABIT_COOLDOWN_VIOLATION",
        "WEEKLY_GOAL_UNREALIZED",
    }


def test_trace_and_ledger_record_planned_occurrences() -> None:
    profile, digest, ledger, budget = context()
    valid_proposals = proposals()
    trace = planned_habit_trace(profile, digest, budget, valid_proposals)
    updated = update_habit_ledger(profile, digest, ledger, valid_proposals)
    assert sum(item.intent == "take_morning_medication" for item in trace.occurrences) == 7
    medication = next(item for item in updated.entries if item.habit_id == "daily_medication")
    assert medication.total_occurrences == 7
    assert medication.last_seen == date(2026, 8, 16)
