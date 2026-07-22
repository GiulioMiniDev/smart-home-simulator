from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralHabit,
    BehavioralProfile,
    HabitCadence,
    HabitDrift,
    HabitKind,
)
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
    validate_behavioral_profile,
)
from smart_home_sim.hybrid_planning.lmstudio import LMStudioError, LMStudioExchange
from smart_home_sim.hybrid_planning.models import HybridPlanningConfig, TimeBand
from smart_home_sim.hybrid_planning.profile_service import generate_behavioral_profile
from smart_home_sim.hybrid_planning.service import HybridPlanningError, _read_models

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


class StructurallyInvalidThenValidClient(FakeClient):
    def __init__(self, output: BehavioralProfile) -> None:
        super().__init__([output])
        self.failed_once = False

    def complete_json(self, **kwargs: Any) -> tuple[BehavioralProfile, LMStudioExchange]:
        if not self.failed_once:
            self.failed_once = True
            self.prompts.append(kwargs["user_prompt"])
            raise LMStudioError(
                "LM Studio returned an invalid structured response: "
                "executionProbability + exceptionProbability must not exceed 1"
            )
        return super().complete_json(**kwargs)


class AlwaysStructurallyInvalidClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_json(self, **kwargs: Any) -> tuple[BehavioralProfile, LMStudioExchange]:
        self.prompts.append(kwargs["user_prompt"])
        raise LMStudioError("invalid structured response: impossible probability pair")


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


def test_habit_rejects_empty_drift_and_impossible_probabilities() -> None:
    with pytest.raises(ValidationError, match="requires a cadence or time-band override"):
        HabitDrift(effective_from=date(2026, 9, 1), rationale="A planned lifestyle change.")
    valid_drift = HabitDrift(
        effective_from=date(2026, 9, 1),
        rationale="A later wake time during the autumn season.",
        preferred_time_bands_override=[TimeBand.morning],
    )
    assert valid_drift.preferred_time_bands_override == [TimeBand.morning]
    payload = habit().model_dump()
    payload.update({"execution_probability": 0.9, "exception_probability": 0.2})
    with pytest.raises(ValidationError, match="must not exceed 1"):
        BehavioralHabit.model_validate(payload)


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


def test_profile_validator_reports_fact_chain_location_and_overload_errors() -> None:
    planning_case, catalog = _read_models(CASE)
    profile = valid_profile()
    overloaded = HabitCadence(
        minimum_occurrences=1,
        typical_occurrences=1,
        maximum_occurrences=5,
        period_days=1,
    )
    habits = [
        item.model_copy(update={"cadence": overloaded}) if index < 3 else item
        for index, item in enumerate(profile.habits)
    ]
    habits[3] = habits[3].model_copy(
        update={
            "predecessor_intents": ["invented_predecessor"],
            "location_ids": ["invented_location"],
            "incompatible_habit_ids": [habits[3].habit_id],
        }
    )
    invalid = profile.model_copy(
        update={
            "source_case_id": "different_case",
            "immutable_facts": {"occupation": "astronaut"},
            "effective_from": profile.effective_from + timedelta(days=1),
            "habits": habits,
        }
    )

    report = validate_behavioral_profile(planning_case, catalog, invalid)

    assert {item.code for item in report.issues} >= {
        "PROFILE_CASE_MISMATCH",
        "PROFILE_FACTS_MISMATCH",
        "PROFILE_EFFECTIVE_DATE_MISMATCH",
        "PROFILE_UNKNOWN_CHAIN_INTENT",
        "PROFILE_UNKNOWN_LOCATION",
        "PROFILE_SELF_INCOMPATIBLE",
        "PROFILE_DAILY_OVERLOAD",
    }


def test_profile_validator_rejects_routine_cadence_mismatch() -> None:
    planning_case, catalog = _read_models(CASE)
    profile = valid_profile()
    medication = profile.habits[0].model_copy(
        update={
            "cadence": HabitCadence(
                minimum_occurrences=1,
                typical_occurrences=1,
                maximum_occurrences=1,
                period_days=7,
            )
        }
    )
    profile = profile.model_copy(update={"habits": [medication, *profile.habits[1:]]})

    report = validate_behavioral_profile(planning_case, catalog, profile)

    assert "PROFILE_ROUTINE_CADENCE_MISMATCH" in {item.code for item in report.issues}


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


def test_profile_generation_repairs_structural_llm_error(tmp_path: Path) -> None:
    client = StructurallyInvalidThenValidClient(valid_profile())

    result = generate_behavioral_profile(
        CASE,
        tmp_path / "profile",
        HybridPlanningConfig(model="fake"),
        client=client,
    )

    assert result.validation.valid
    assert len(client.prompts) == 2
    assert "must not exceed 1" in client.prompts[1]
    assert "complete replacement" in client.prompts[1]


def test_profile_generation_fails_after_structural_repair_exhaustion(
    tmp_path: Path,
) -> None:
    client = AlwaysStructurallyInvalidClient()
    output = tmp_path / "profile"

    with pytest.raises(HybridPlanningError, match="impossible probability pair"):
        generate_behavioral_profile(
            CASE,
            output,
            HybridPlanningConfig(model="fake"),
            client=client,
        )

    assert len(client.prompts) == 3
    assert json.loads((output / "run.json").read_text())["status"] == "failed"
    assert (output / "attempts/attempt-3/structure-error.txt").is_file()


def test_profile_generation_fails_after_repair_exhaustion(tmp_path: Path) -> None:
    invalid = valid_profile().model_copy(update={"resident_id": "someone_else"})
    client = FakeClient([invalid, invalid, invalid])
    output = tmp_path / "invalid-profile"

    with pytest.raises(HybridPlanningError, match="failed validation"):
        generate_behavioral_profile(
            CASE,
            output,
            HybridPlanningConfig(model="fake"),
            client=client,
        )

    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert len(client.prompts) == 3


def test_profile_generation_preserves_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(HybridPlanningError, match="already exists"):
        generate_behavioral_profile(CASE, output, HybridPlanningConfig(model="fake"))
