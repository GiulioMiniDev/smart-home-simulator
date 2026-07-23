from datetime import date

import pytest
from test_behavioral_profile import valid_profile
from test_hybrid_planning import CASE, _read_models, activity

from smart_home_sim.hybrid_planning.guardrails import (
    daily_life_violations,
    normalize_daily_guardrails,
    normalize_habit_preferences,
    semantic_violations,
)
from smart_home_sim.hybrid_planning.longitudinal_models import QualityViolation
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    ProposedActivity,
    TimeBand,
)


def test_quality_violation_serializes_with_aliases() -> None:
    violation = QualityViolation(
        code="MISSING_NOURISHMENT",
        date=date(2026, 8, 10),
        intent="nourishment",
        message="day requires a nourishment activity",
    )

    assert violation.model_dump(by_alias=True)["date"] == date(2026, 8, 10)


def test_daily_life_requires_nourishment_hygiene_and_density() -> None:
    sparse = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="An implausibly sparse Sunday",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("watch_television", "living_room_01", "evening"),
            activity("read_and_rest", "living_room_01", "afternoon"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )

    assert {item.code for item in daily_life_violations("weekend", sparse)} == {
        "MISSING_NOURISHMENT",
        "MISSING_HYGIENE",
        "DAILY_DENSITY_TOO_LOW",
    }


def test_daily_life_accepts_complete_variable_day() -> None:
    complete = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="Complete Sunday with room for variation",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("prepare_weekend_breakfast", "kitchen_01", "morning"),
            activity("evening_hygiene", "bathroom_01", "evening"),
            activity("read_and_rest", "living_room_01", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )

    assert daily_life_violations("weekend", complete) == []


def test_daily_guardrail_normalization_supplies_safe_structural_scaffolding() -> None:
    planning_case, catalog = _read_models(CASE)
    incomplete = DailyProposal(
        date=date(2026, 8, 10),
        narrative_intent="Workday whose structural details need repair",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("work_shift", "garden_workplace", "morning"),
            activity("watch_television", "living_room_01", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )

    normalized, changes = normalize_daily_guardrails(
        planning_case,
        catalog,
        "workday",
        incomplete,
    )

    intents = [item.intent for item in normalized.activities]
    assert intents.index("commute_to_work") < intents.index("work_shift")
    assert intents.index("work_shift") < intents.index("commute_home")
    assert daily_life_violations("workday", normalized) == []
    assert semantic_violations(valid_profile(), normalized) == []
    assert {item["reason"] for item in changes} == {
        "missing_hygiene",
        "missing_nourishment",
        "work_shift_chain",
    }


@pytest.mark.parametrize(
    ("activities", "code"),
    [
        (
            [
                activity("post_walk_shower", "bathroom_01", "evening"),
                activity("sleep", "bedroom_01", "night"),
            ],
            "SHOWER_WITHOUT_WALK",
        ),
        (
            [
                activity(
                    "visit_mother_and_have_dinner",
                    "mother_house_barcelona",
                    "evening",
                ),
                activity("sleep", "bedroom_01", "night"),
            ],
            "MOTHER_VISIT_CHAIN_INCOMPLETE",
        ),
        (
            [
                activity("work_shift", "garden_workplace", "morning"),
                activity("sleep", "bedroom_01", "night"),
            ],
            "WORK_SHIFT_CHAIN_INCOMPLETE",
        ),
    ],
)
def test_semantic_rules_reject_incomplete_chains(
    activities: list[ProposedActivity],
    code: str,
) -> None:
    proposal_activities = [
        activity("take_morning_medication", "bedroom_01", "early_morning"),
        *activities[:-1],
        activity("watch_television", "living_room_01", "afternoon"),
        *activities[-1:],
    ]
    proposal = DailyProposal(
        date=date(2026, 8, 10),
        narrative_intent="Incomplete semantic chain",
        activities=proposal_activities,
    )

    assert code in {
        item.code for item in semantic_violations(valid_profile(), proposal)
    }


def test_profile_habit_preferences_are_normalized() -> None:
    profile = valid_profile()
    wrong = DailyProposal(
        date=date(2026, 8, 10),
        narrative_intent="Wrong habit preferences",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("buy_groceries", "living_room_01", "morning"),
            activity("watch_television", "living_room_01", "afternoon"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )

    normalized, changes = normalize_habit_preferences(profile, wrong)

    item = next(
        item for item in normalized.activities if item.intent == "buy_groceries"
    )
    assert item.time_band is TimeBand.afternoon
    assert item.location_id == "supermarket_barcelona"
    assert {change["field"] for change in changes} == {"timeBand", "locationId"}
