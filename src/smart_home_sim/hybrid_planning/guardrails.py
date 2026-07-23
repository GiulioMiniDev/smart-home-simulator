from __future__ import annotations

from smart_home_sim.domain.behavior import ActivityCatalog
from smart_home_sim.hybrid_planning.behavioral_models import BehavioralProfile
from smart_home_sim.hybrid_planning.longitudinal_models import QualityViolation
from smart_home_sim.hybrid_planning.models import DailyProposal

NOURISHMENT_INTENTS = frozenset(
    {
        "cook_dinner",
        "eat_breakfast",
        "eat_breakfast_and_listen_to_radio",
        "eat_breakfast_and_read_news",
        "eat_breakfast_with_radio_news",
        "eat_dinner",
        "eat_light_dinner",
        "eat_lunch",
        "prepare_and_eat_breakfast",
        "prepare_breakfast",
        "prepare_light_dinner",
        "prepare_simple_lunch",
        "prepare_sunday_lunch",
        "prepare_weekend_breakfast",
        "reheat_leftover_dinner_and_prepare_salad",
        "visit_mother_and_have_dinner",
        "weekly_meal_preparation",
    }
)
HYGIENE_INTENTS = frozenset(
    {
        "evening_hygiene",
        "morning_toilet_and_shower",
        "morning_toilet_and_wash",
        "post_walk_shower",
        "shower_and_get_ready_to_go_out",
    }
)
WALK_INTENTS = frozenset(
    {
        "evening_walk",
        "long_sunday_walk",
        "short_evening_walk",
    }
)
MINIMUM_ACTIVITY_COUNT = {
    "workday": 6,
    "weekend": 5,
}


def _violation(
    proposal: DailyProposal,
    code: str,
    intent: str,
    message: str,
) -> QualityViolation:
    return QualityViolation(
        code=code,
        date=proposal.date,
        intent=intent,
        message=message,
    )


def daily_life_violations(
    day_type: str,
    proposal: DailyProposal,
) -> list[QualityViolation]:
    intents = {item.intent for item in proposal.activities}
    violations: list[QualityViolation] = []
    if not NOURISHMENT_INTENTS.intersection(intents):
        violations.append(
            _violation(
                proposal,
                "MISSING_NOURISHMENT",
                "nourishment",
                "day requires a nourishment activity",
            )
        )
    if not HYGIENE_INTENTS.intersection(intents):
        violations.append(
            _violation(
                proposal,
                "MISSING_HYGIENE",
                "hygiene",
                "day requires a hygiene activity",
            )
        )
    minimum = MINIMUM_ACTIVITY_COUNT.get(day_type)
    if minimum is not None and len(proposal.activities) < minimum:
        violations.append(
            _violation(
                proposal,
                "DAILY_DENSITY_TOO_LOW",
                "activity_count",
                f"{day_type} requires at least {minimum} activities; "
                f"found {len(proposal.activities)}",
            )
        )
    return violations


def semantic_violations(
    profile: BehavioralProfile,
    proposal: DailyProposal,
) -> list[QualityViolation]:
    habits = {item.intent: item for item in profile.habits}
    intents = [item.intent for item in proposal.activities]
    violations: list[QualityViolation] = []
    for position, intent in enumerate(intents):
        earlier = intents[:position]
        later = intents[position + 1 :]
        if intent == "post_walk_shower" and not WALK_INTENTS.intersection(earlier):
            violations.append(
                _violation(
                    proposal,
                    "SHOWER_WITHOUT_WALK",
                    intent,
                    "post_walk_shower requires an earlier walk",
                )
            )
        if intent == "visit_mother_and_have_dinner" and (
            "travel_to_mothers_home" not in earlier or "travel_home" not in later
        ):
            violations.append(
                _violation(
                    proposal,
                    "MOTHER_VISIT_CHAIN_INCOMPLETE",
                    intent,
                    "visit_mother_and_have_dinner requires earlier "
                    "travel_to_mothers_home and later travel_home",
                )
            )
        if intent == "work_shift" and (
            "commute_to_work" not in earlier or "commute_home" not in later
        ):
            violations.append(
                _violation(
                    proposal,
                    "WORK_SHIFT_CHAIN_INCOMPLETE",
                    intent,
                    "work_shift requires earlier commute_to_work and later commute_home",
                )
            )
        if intent == "commute_to_work" and "work_shift" not in later:
            violations.append(
                _violation(
                    proposal,
                    "WORK_TRAVEL_WITHOUT_SHIFT",
                    intent,
                    "outbound work travel requires a later work_shift",
                )
            )
        if intent == "commute_home" and "work_shift" not in earlier:
            violations.append(
                _violation(
                    proposal,
                    "RETURN_TRAVEL_WITHOUT_SHIFT",
                    intent,
                    "return work travel requires an earlier work_shift",
                )
            )
        habit = habits.get(intent)
        if habit is None:
            continue
        for required in habit.predecessor_intents:
            if required not in earlier:
                violations.append(
                    _violation(
                        proposal,
                        "MISSING_HABIT_PREDECESSOR",
                        intent,
                        f"{intent} requires earlier {required}",
                    )
                )
        for required in habit.successor_intents:
            if required not in later:
                violations.append(
                    _violation(
                        proposal,
                        "MISSING_HABIT_SUCCESSOR",
                        intent,
                        f"{intent} requires later {required}",
                    )
                )
    unique: dict[tuple[str, object, str, str], QualityViolation] = {}
    for item in violations:
        key = (item.code, item.date, item.intent, item.message)
        unique[key] = item
    return list(unique.values())


def normalize_habit_preferences(
    profile: BehavioralProfile,
    proposal: DailyProposal,
) -> tuple[DailyProposal, list[dict[str, object]]]:
    habits = {item.intent: item for item in profile.habits}
    activities = []
    changes: list[dict[str, object]] = []
    for activity in proposal.activities:
        habit = habits.get(activity.intent)
        if habit is None:
            activities.append(activity)
            continue
        updates: dict[str, object] = {}
        if activity.time_band not in habit.preferred_time_bands:
            selected_band = habit.preferred_time_bands[0]
            updates["time_band"] = selected_band
            changes.append(
                {
                    "date": proposal.date.isoformat(),
                    "habitId": habit.habit_id,
                    "intent": habit.intent,
                    "field": "timeBand",
                    "from": activity.time_band.value,
                    "to": selected_band.value,
                    "reason": "profile_preference",
                }
            )
        if activity.location_id not in habit.location_ids:
            selected_location = habit.location_ids[0]
            updates["location_id"] = selected_location
            changes.append(
                {
                    "date": proposal.date.isoformat(),
                    "habitId": habit.habit_id,
                    "intent": habit.intent,
                    "field": "locationId",
                    "from": activity.location_id,
                    "to": selected_location,
                    "reason": "profile_preference",
                }
            )
        activities.append(activity.model_copy(update=updates) if updates else activity)
    return proposal.model_copy(update={"activities": activities}), changes


def guardrail_prompt_payload(catalog: ActivityCatalog) -> dict[str, object]:
    known = {item.intent for item in catalog.activities}
    return {
        "minimumActivities": dict(MINIMUM_ACTIVITY_COUNT),
        "requiredDailyCategories": {
            "nourishment": sorted(NOURISHMENT_INTENTS.intersection(known)),
            "hygiene": sorted(HYGIENE_INTENTS.intersection(known)),
        },
        "semanticRules": [
            "post_walk_shower requires an earlier walking intent",
            "visit_mother_and_have_dinner requires travel_to_mothers_home "
            "before and travel_home after",
            "work_shift requires commute_to_work before and commute_home after",
        ],
    }
