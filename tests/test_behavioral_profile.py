from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralHabit,
    BehavioralProfile,
    HabitCadence,
    HabitKind,
)
from smart_home_sim.hybrid_planning.models import TimeBand


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
