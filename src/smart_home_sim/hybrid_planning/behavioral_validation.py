from __future__ import annotations

import hashlib
import json
from collections import Counter

from pydantic import Field

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.behavior import ActivityCatalog
from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralProfile,
    HabitKind,
)
from smart_home_sim.hybrid_planning.models import PlanningCase

PROFILE_CODES = {
    "PROFILE_CASE_MISMATCH",
    "PROFILE_RESIDENT_MISMATCH",
    "PROFILE_FACTS_MISMATCH",
    "PROFILE_EFFECTIVE_DATE_MISMATCH",
    "PROFILE_UNKNOWN_INTENT",
    "PROFILE_UNKNOWN_CHAIN_INTENT",
    "PROFILE_UNKNOWN_LOCATION",
    "PROFILE_SELF_INCOMPATIBLE",
    "PROFILE_MISSING_ROUTINE_ANCHOR",
    "PROFILE_PORTFOLIO_UNBALANCED",
    "PROFILE_DAILY_OVERLOAD",
}


class ProfileIssue(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    habit_id: str | None = None


class ProfileValidationReport(ContractModel):
    valid: bool
    issues: list[ProfileIssue] = Field(default_factory=list)


def behavioral_profile_digest(profile: BehavioralProfile) -> str:
    payload = profile.model_dump(mode="json", by_alias=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _issue(code: str, message: str, habit_id: str | None = None) -> ProfileIssue:
    return ProfileIssue(code=code, message=message, habit_id=habit_id)


def validate_behavioral_profile(
    planning_case: PlanningCase,
    catalog: ActivityCatalog,
    profile: BehavioralProfile,
) -> ProfileValidationReport:
    issues: list[ProfileIssue] = []
    known_intents = {item.intent for item in catalog.activities}
    known_locations = {item.location_id for item in planning_case.locations}
    expected_effective_date = planning_case.dates()[0]
    if profile.source_case_id != planning_case.case_id:
        issues.append(_issue("PROFILE_CASE_MISMATCH", "sourceCaseId differs from planning case"))
    if profile.resident_id != planning_case.resident.resident_id:
        issues.append(_issue("PROFILE_RESIDENT_MISMATCH", "residentId differs from planning case"))
    if profile.immutable_facts != planning_case.resident.profile:
        issues.append(
            _issue("PROFILE_FACTS_MISMATCH", "immutableFacts differ from resident profile")
        )
    if profile.effective_from != expected_effective_date:
        issues.append(
            _issue(
                "PROFILE_EFFECTIVE_DATE_MISMATCH",
                f"effectiveFrom must be {expected_effective_date.isoformat()}",
            )
        )
    for habit in profile.habits:
        if habit.intent not in known_intents:
            issues.append(
                _issue("PROFILE_UNKNOWN_INTENT", f"unknown intent: {habit.intent}", habit.habit_id)
            )
        for intent in [*habit.predecessor_intents, *habit.successor_intents]:
            if intent not in known_intents:
                issues.append(
                    _issue(
                        "PROFILE_UNKNOWN_CHAIN_INTENT",
                        f"unknown chain intent: {intent}",
                        habit.habit_id,
                    )
                )
        unknown_locations = sorted(set(habit.location_ids) - known_locations)
        if unknown_locations:
            issues.append(
                _issue(
                    "PROFILE_UNKNOWN_LOCATION",
                    f"unknown locations: {unknown_locations}",
                    habit.habit_id,
                )
            )
        if habit.habit_id in habit.incompatible_habit_ids:
            issues.append(
                _issue(
                    "PROFILE_SELF_INCOMPATIBLE",
                    "habit cannot be incompatible with itself",
                    habit.habit_id,
                )
            )
    anchors = {item.intent: item for item in profile.habits if item.kind is HabitKind.anchor}
    for requirement in planning_case.routine_requirements:
        anchor = anchors.get(requirement.intent)
        band_missing = (
            anchor is not None
            and requirement.time_band is not None
            and requirement.time_band not in anchor.preferred_time_bands
        )
        if anchor is None or band_missing:
            issues.append(
                _issue(
                    "PROFILE_MISSING_ROUTINE_ANCHOR",
                    f"routine is not represented by a compatible anchor: {requirement.intent}",
                )
            )
            continue
        cadence_mismatch = (
            anchor.cadence.period_days != 1
            or anchor.cadence.minimum_occurrences < requirement.minimum_occurrences
            or anchor.cadence.maximum_occurrences > requirement.maximum_occurrences
            or set(anchor.applicable_day_types) != set(requirement.day_types)
        )
        if cadence_mismatch:
            issues.append(
                _issue(
                    "PROFILE_ROUTINE_CADENCE_MISMATCH",
                    "routine anchor must use a one-day cadence and exactly the supplied "
                    f"day types and occurrence bounds: {requirement.intent}",
                    anchor.habit_id,
                )
            )
    counts = Counter(item.kind for item in profile.habits)
    if (
        counts[HabitKind.anchor] < 3
        or counts[HabitKind.contextual] < 2
        or counts[HabitKind.optional] < 2
        or counts[HabitKind.rare] < 1
    ):
        issues.append(
            _issue(
                "PROFILE_PORTFOLIO_UNBALANCED",
                "profile requires at least 3 anchor, 2 contextual, 2 optional and 1 rare habits",
            )
        )
    for day_type in {planning_case.calendar_day(value).day_type for value in planning_case.dates()}:
        maximum = sum(
            item.cadence.maximum_occurrences
            for item in profile.habits
            if item.kind is HabitKind.anchor
            and item.cadence.period_days == 1
            and (not item.applicable_day_types or day_type in item.applicable_day_types)
        )
        if maximum > 12:
            issues.append(
                _issue(
                    "PROFILE_DAILY_OVERLOAD",
                    f"anchor maximum is {maximum} on {day_type}; limit is 12",
                )
            )
    return ProfileValidationReport(valid=not issues, issues=issues)
