from datetime import date

import pytest
from test_behavioral_profile import valid_profile
from test_hybrid_planning import CASE, _read_models, activity

from smart_home_sim.hybrid_planning.guardrails import (
    daily_life_violations,
    fit_day_to_time_budget,
    normalize_daily_guardrails,
    normalize_habit_preferences,
    semantic_violations,
    spatial_coherence_violations,
)
from smart_home_sim.hybrid_planning.longitudinal_models import QualityViolation
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    DurationClass,
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


def test_time_budget_trim_drops_low_priority_optionals_and_keeps_essentials() -> None:
    planning_case, catalog = _read_models(CASE)

    def act(intent: str, location: str, band: str, *, dur: str = "medium",
            mandatory: bool = False, priority: int = 30) -> ProposedActivity:
        return ProposedActivity(
            intent=intent, location_id=location, time_band=TimeBand(band),
            duration_class=DurationClass(dur), mandatory=mandatory, priority=priority,
            rationale="x",
        )

    over_dense = DailyProposal(
        date=date(2026, 8, 10),
        narrative_intent="An overfull workday",
        activities=[
            act("take_morning_medication", "bedroom_01", "early_morning", mandatory=True, priority=100),
            act("morning_toilet_and_shower", "bathroom_01", "early_morning"),
            act("eat_breakfast_and_read_news", "kitchen_01", "morning"),
            act("check_calendar_and_household_supplies", "living_room_01", "morning"),
            act("commute_to_work", "garden_workplace", "morning", mandatory=True, priority=90),
            act("work_shift", "garden_workplace", "morning", dur="extended", mandatory=True, priority=100),
            act("eat_lunch", "garden_workplace", "midday"),
            act("commute_home", "garden_workplace", "afternoon", mandatory=True, priority=90),
            act("tidy_living_room_and_hallway", "living_room_01", "afternoon"),
            act("short_evening_walk", "neighborhood_park", "evening"),
            act("eat_dinner", "kitchen_01", "evening"),
            act("watch_documentary", "living_room_01", "evening"),
            act("read_and_rest", "living_room_01", "evening"),
            act("evening_hygiene", "bathroom_01", "evening"),
            act("sleep", "bedroom_01", "night", dur="extended", mandatory=True, priority=100),
        ],
    )

    fitted, removed = fit_day_to_time_budget(
        planning_case, over_dense, frozenset({"work_shift"}), date(2026, 8, 12)
    )

    assert removed, "an over-dense day should have activities trimmed"
    kept = {item.intent for item in fitted.activities}
    # Mandatory and protected intents are never dropped.
    for essential in ("work_shift", "take_morning_medication", "sleep", "commute_to_work", "commute_home"):
        assert essential in kept
    # The daily-life guardrail (nourishment + hygiene + density) still holds after trimming.
    assert daily_life_violations("workday", fitted) == []


def test_spatial_coherence_flags_home_activity_while_away() -> None:
    planning_case, _catalog = _read_models(CASE)
    teleporting = DailyProposal(
        date=date(2026, 8, 10),
        narrative_intent="Workday with breakfast wrongly scheduled during the shift",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("commute_to_work", "garden_workplace", "morning"),
            activity("work_shift", "garden_workplace", "morning"),
            activity("prepare_and_eat_breakfast", "kitchen_01", "afternoon"),
            activity("commute_home", "garden_workplace", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )

    violations = spatial_coherence_violations(planning_case, teleporting)
    assert [item.code for item in violations] == ["HOME_ACTIVITY_WHILE_AWAY"]
    assert violations[0].intent == "prepare_and_eat_breakfast"


def test_spatial_coherence_accepts_breakfast_before_commute() -> None:
    planning_case, _catalog = _read_models(CASE)
    coherent = DailyProposal(
        date=date(2026, 8, 10),
        narrative_intent="Workday with breakfast at home before leaving",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("prepare_and_eat_breakfast", "kitchen_01", "morning"),
            activity("commute_to_work", "garden_workplace", "morning"),
            activity("work_shift", "garden_workplace", "morning"),
            activity("commute_home", "garden_workplace", "evening"),
            activity("prepare_light_dinner", "kitchen_01", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )

    assert spatial_coherence_violations(planning_case, coherent) == []


def test_daily_guardrail_normalization_relabels_orphan_post_walk_shower() -> None:
    planning_case, catalog = _read_models(CASE)
    orphan = DailyProposal(
        date=date(2026, 8, 16),
        narrative_intent="Quiet Sunday without a walk",
        activities=[
            activity("take_morning_medication", "bedroom_01", "early_morning"),
            activity("prepare_weekend_breakfast", "kitchen_01", "morning"),
            activity("watch_television", "living_room_01", "afternoon"),
            activity("post_walk_shower", "bathroom_01", "evening"),
            activity("sleep", "bedroom_01", "night"),
        ],
    )

    normalized, changes = normalize_daily_guardrails(
        planning_case,
        catalog,
        "weekend",
        orphan,
    )

    assert "post_walk_shower" not in {
        item.intent for item in normalized.activities
    }
    assert semantic_violations(valid_profile(), normalized) == []
    assert changes == [
        {
            "date": "2026-08-16",
            "action": "replace",
            "intent": "evening_hygiene",
            "reason": "orphan_post_walk_shower",
            "replaces": "post_walk_shower",
        }
    ]


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
