from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralHabit,
    BehavioralProfile,
    HabitCadence,
    HabitKind,
)
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
    validate_behavioral_profile,
)
from smart_home_sim.hybrid_planning.lmstudio import LMStudioExchange
from smart_home_sim.hybrid_planning.models import HybridPlanningConfig, TimeBand
from smart_home_sim.hybrid_planning.profile_service import generate_behavioral_profile
from smart_home_sim.hybrid_planning.service import _read_models

ROOT = Path(__file__).parents[1]
CASE = ROOT / "examples/hybrid/tommaso_bianchi_week.planning-case.json"


def habit() -> BehavioralHabit:
    return BehavioralHabit(
        habit_id="daily_medication",
        intent="take_morning_medication",
        kind=HabitKind.anchor,
        rationale="Tommaso manages type 1 diabetes every morning.",
        cadence=HabitCadence(
            minimum_occurrences=1,
            typical_occurrences=1,
            maximum_occurrences=1,
            period_days=1,
        ),
        applicable_day_types=[],
        preferred_time_bands=[TimeBand.early_morning],
        temporal_jitter_minutes=20,
        execution_probability=0.98,
        exception_probability=0.02,
        cooldown_days=0,
        location_ids=["bedroom_01"],
        predecessor_intents=[],
        successor_intents=[],
        incompatible_habit_ids=[],
        seasonality="stable",
        mining_difficulty="easy",
    )


def profile_habit(
    habit_id: str,
    intent: str,
    kind: HabitKind,
    location: str,
    band: TimeBand,
    *,
    day_types: list[str] | None = None,
    minimum: int = 1,
    typical: int = 1,
    maximum: int = 1,
    period_days: int = 1,
    cooldown_days: int = 0,
    predecessors: list[str] | None = None,
    successors: list[str] | None = None,
) -> BehavioralHabit:
    return BehavioralHabit(
        habit_id=habit_id,
        intent=intent,
        kind=kind,
        rationale=f"A stable and measurable pattern for {intent}.",
        cadence=HabitCadence(
            minimum_occurrences=minimum,
            typical_occurrences=typical,
            maximum_occurrences=maximum,
            period_days=period_days,
        ),
        applicable_day_types=day_types or [],
        preferred_time_bands=[band],
        temporal_jitter_minutes=30,
        execution_probability=0.9,
        exception_probability=0.1,
        cooldown_days=cooldown_days,
        location_ids=[location],
        predecessor_intents=predecessors or [],
        successor_intents=successors or [],
        incompatible_habit_ids=[],
        seasonality="stable unless a versioned drift applies",
        mining_difficulty="easy" if kind is HabitKind.anchor else "medium",
    )


def valid_profile() -> BehavioralProfile:
    return BehavioralProfile(
        profile_id="tommaso_bianchi_behavior",
        profile_version="1.0.0",
        source_case_id="tommaso_bianchi_2026_08_10",
        resident_id="tommaso_bianchi",
        effective_from=date(2026, 8, 10),
        immutable_facts={
            "age": 30,
            "occupation": "gardener",
            "city": "Barcelona",
            "condition": "type_1_diabetes",
        },
        synthetic_traits={
            "wakeStyle": "early",
            "mealStyle": "regular",
            "socialStyle": "family-oriented",
            "exerciseStyle": "active",
            "domesticStyle": "orderly",
            "noveltyStyle": "moderate",
        },
        habits=[
            profile_habit(
                "daily_medication",
                "take_morning_medication",
                HabitKind.anchor,
                "bedroom_01",
                TimeBand.early_morning,
            ),
            profile_habit(
                "weekday_work",
                "work_shift",
                HabitKind.anchor,
                "garden_workplace",
                TimeBand.morning,
                day_types=["workday"],
            ),
            profile_habit(
                "night_sleep",
                "sleep",
                HabitKind.anchor,
                "bedroom_01",
                TimeBand.night,
            ),
            profile_habit(
                "weekly_groceries",
                "buy_groceries",
                HabitKind.contextual,
                "supermarket_barcelona",
                TimeBand.afternoon,
                period_days=7,
                cooldown_days=4,
            ),
            profile_habit(
                "mother_visit",
                "visit_mother_and_have_dinner",
                HabitKind.contextual,
                "mother_house_barcelona",
                TimeBand.evening,
                day_types=["weekend"],
                minimum=2,
                typical=3,
                maximum=4,
                period_days=30,
                cooldown_days=5,
                predecessors=["travel_to_mothers_home"],
                successors=["travel_home"],
            ),
            profile_habit(
                "regular_reading",
                "read",
                HabitKind.optional,
                "living_room_01",
                TimeBand.evening,
                minimum=1,
                typical=3,
                maximum=5,
                period_days=7,
            ),
            profile_habit(
                "evening_walk",
                "evening_walk",
                HabitKind.optional,
                "neighborhood_park",
                TimeBand.evening,
                minimum=1,
                typical=2,
                maximum=3,
                period_days=7,
                cooldown_days=1,
            ),
            profile_habit(
                "medication_refill",
                "collect_medication_refill",
                HabitKind.rare,
                "pharmacy_barcelona",
                TimeBand.afternoon,
                minimum=0,
                typical=1,
                maximum=1,
                period_days=60,
                cooldown_days=30,
            ),
        ],
    )


class FakeClient:
    def __init__(self, outputs: list[BehavioralProfile]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def complete_json(self, **kwargs: Any) -> tuple[BehavioralProfile, LMStudioExchange]:
        self.prompts.append(kwargs["user_prompt"])
        value = self.outputs.pop(0)
        content = value.model_dump_json(by_alias=True)
        return value, LMStudioExchange(
            request={"messages": [{"content": kwargs["user_prompt"]}]},
            api_response={"choices": [{"message": {"content": content}}]},
            raw_content=content,
        )


def test_cadence_rejects_inverted_bounds() -> None:
    with pytest.raises(ValidationError, match="typicalOccurrences"):
        HabitCadence(
            minimum_occurrences=2,
            typical_occurrences=1,
            maximum_occurrences=3,
            period_days=7,
        )


def test_profile_rejects_duplicate_habit_ids_and_intents() -> None:
    repeated = habit()
    with pytest.raises(ValidationError, match="habitId and intent"):
        BehavioralProfile(
            profile_id="tommaso_behavior",
            profile_version="1.0.0",
            source_case_id="tommaso_bianchi_2026_08_10",
            resident_id="tommaso_bianchi",
            effective_from=date(2026, 8, 10),
            immutable_facts={"occupation": "gardener"},
            synthetic_traits={
                "socialStyle": "family-oriented",
                "wakeStyle": "early",
                "mealStyle": "regular",
                "exerciseStyle": "active",
                "domesticStyle": "orderly",
                "noveltyStyle": "moderate",
            },
            habits=[repeated, repeated.model_copy(update={"habit_id": "other"})] * 4,
        )


def test_profile_validator_reports_identity_catalog_and_portfolio_errors() -> None:
    planning_case, catalog = _read_models(CASE)
    invalid_habits = [
        habit().model_copy(
            update={"habit_id": f"bad_{index}", "intent": f"invented_{index}"}
        )
        for index in range(8)
    ]
    invalid = valid_profile().model_copy(
        update={"resident_id": "someone_else", "habits": invalid_habits}
    )
    report = validate_behavioral_profile(planning_case, catalog, invalid)
    assert {issue.code for issue in report.issues} >= {
        "PROFILE_RESIDENT_MISMATCH",
        "PROFILE_UNKNOWN_INTENT",
        "PROFILE_MISSING_ROUTINE_ANCHOR",
        "PROFILE_PORTFOLIO_UNBALANCED",
    }


def test_profile_generation_repairs_then_freezes(tmp_path: Path) -> None:
    invalid = valid_profile().model_copy(update={"resident_id": "someone_else"})
    valid = valid_profile()
    client = FakeClient([invalid, valid])
    result = generate_behavioral_profile(
        CASE,
        tmp_path / "profile",
        HybridPlanningConfig(model="fake"),
        client=client,
    )
    assert result.profile == valid
    assert len(client.prompts) == 2
    assert (result.output_dir / "behavioral-profile.json").is_file()
    assert (result.output_dir / "intended-habits.json").is_file()
    assert (result.output_dir / "profile.sha256").read_text().strip() == result.profile_digest
    assert result.profile_digest == behavioral_profile_digest(valid)
