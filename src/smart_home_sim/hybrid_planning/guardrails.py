from __future__ import annotations

from smart_home_sim.domain.behavior import ActivityCatalog
from smart_home_sim.domain.models import LocationKind
from smart_home_sim.hybrid_planning.behavioral_models import BehavioralProfile
from smart_home_sim.hybrid_planning.longitudinal_models import QualityViolation
from smart_home_sim.hybrid_planning.materialization import materialize_day_activities
from smart_home_sim.hybrid_planning.models import (
    DailyProposal,
    DurationClass,
    PlanningCase,
    ProposedActivity,
    TimeBand,
)

HOME_DEPARTURE_INTENTS = frozenset(
    {
        "collect_belongings_and_leave_home",
        "commute_to_work",
        "leave_home",
        "travel_to_mothers_home",
    }
)
HOME_RETURN_INTENTS = frozenset(
    {
        "commute_home",
        "enter_home",
        "return_home_and_store_purchases",
        "travel_home",
    }
)
# Pure return-travel intents: they represent the trip home and must start OUTSIDE, so a home
# room location makes their enter_home step fail (the resident is already home).
PURE_RETURN_INTENTS = frozenset({"commute_home", "enter_home", "travel_home"})

# Home locations for scaffolding a missing indoor goal intent, by activity-catalog category.
# External categories (errand, exercise, social_visit, travel, work) are intentionally absent:
# they need travel chains, are rarely goal-assigned, and are left to the model to realize.
_GOAL_CATEGORY_LOCATIONS: dict[str, tuple[str, ...]] = {
    "leisure": ("living_room_01",),
    "housekeeping": ("living_room_01", "kitchen_01"),
    "laundry": ("hallway_01", "bathroom_01"),
    "communication": ("living_room_01",),
    "dressing": ("bedroom_01",),
    "eating": ("kitchen_01",),
    "hygiene": ("bathroom_01",),
    "meal_preparation": ("kitchen_01",),
    "medication": ("bedroom_01",),
    "sleep": ("bedroom_01",),
}

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


def spatial_coherence_violations(
    planning_case: PlanningCase,
    proposal: DailyProposal,
) -> list[QualityViolation]:
    """Flag activities that would require teleporting the resident.

    Walks the day's activities in order, tracking whether the resident is away from home.
    An *away block* is opened only by an explicit departure intent (e.g. ``commute_to_work``)
    and closed only by an explicit return intent (e.g. ``commute_home``). Round-trip
    activities that leave and come back within one intent — a walk, a shopping trip — never
    open an away block, so a later home activity such as ``sleep`` is not misflagged. A
    home-interior activity scheduled inside an away block is a spatial impossibility that the
    simulator rejects at runtime, e.g. breakfast in the kitchen during the work shift.
    """

    away = False
    violations: list[QualityViolation] = []
    location_kind = {
        location.location_id: location.kind for location in planning_case.locations
    }
    for activity in proposal.activities:
        at_home = location_kind.get(activity.location_id) is not LocationKind.external
        if activity.intent in HOME_RETURN_INTENTS:
            if activity.intent in PURE_RETURN_INTENTS and at_home:
                violations.append(
                    _violation(
                        proposal,
                        "RETURN_AT_HOME_LOCATION",
                        activity.intent,
                        f"{activity.intent} is located at home '{activity.location_id}'; a "
                        "return-home trip must start at the outside location it returns from "
                        "(e.g. the workplace), not a home room",
                    )
                )
            away = False
            continue
        if activity.intent in HOME_DEPARTURE_INTENTS:
            away = True
            continue
        if away and at_home:
            violations.append(
                _violation(
                    proposal,
                    "HOME_ACTIVITY_WHILE_AWAY",
                    activity.intent,
                    f"{activity.intent} happens at home location "
                    f"'{activity.location_id}' while the resident is away from home; "
                    "add a return home before it or move it outside the time away",
                )
            )
    return violations


def _scaffold_activity(
    intent: str,
    location_id: str,
    time_band: TimeBand,
    duration_class: DurationClass,
    rationale: str,
) -> ProposedActivity:
    return ProposedActivity(
        intent=intent,
        location_id=location_id,
        time_band=time_band,
        duration_class=duration_class,
        mandatory=True,
        priority=100,
        rationale=rationale,
    )


def fit_day_to_time_budget(
    planning_case: PlanningCase,
    proposal: DailyProposal,
    protected_intents: frozenset[str],
    final_date: object,
) -> tuple[DailyProposal, list[str]]:
    """Deterministically drop optional activities until the day fits in 24 hours.

    The model chooses intents and coarse duration classes but cannot do the minute-level
    packing, so it cannot tell whether a day overflows. Rather than bounce an overflow back
    to the model, the machine trims the lowest-priority removable activity — one that is not
    mandatory and whose intent is not protected (routine, goal or habit anchor) — until the
    day is feasible. This keeps feasibility a deterministic property and reserves the model
    for creative choices. If nothing removable remains the proposal is returned unchanged and
    the downstream validator surfaces the (genuine) infeasibility.
    """

    activities = list(proposal.activities)
    # Keep the highest-priority nourishment and hygiene activity so the trim never violates
    # the daily-life guardrail (every day needs at least one of each).
    keep_ids: set[int] = set()
    for category in (NOURISHMENT_INTENTS, HYGIENE_INTENTS):
        members = [activity for activity in activities if activity.intent in category]
        if members:
            keep_ids.add(id(max(members, key=lambda activity: activity.priority)))
    removed: list[str] = []
    while True:
        candidate = proposal.model_copy(update={"activities": activities})
        try:
            materialize_day_activities(planning_case, candidate, final_date=final_date)
            return candidate, removed
        except ValueError as error:
            if "overflow" not in str(error):
                return candidate, removed
            removable = [
                activity
                for activity in activities
                if not activity.mandatory
                and activity.intent not in protected_intents
                and id(activity) not in keep_ids
            ]
            if not removable:
                return candidate, removed
            victim = min(
                removable, key=lambda activity: (activity.priority, activities.index(activity))
            )
            activities.remove(victim)
            removed.append(victim.intent)


def normalize_daily_guardrails(
    planning_case: PlanningCase,
    catalog: ActivityCatalog,
    day_type: str,
    proposal: DailyProposal,
    *,
    final_date: object | None = None,
    protected_intents: frozenset[str] = frozenset(),
    required_goal_intents: frozenset[str] = frozenset(),
    habit_placements: dict[str, tuple[str, str]] | None = None,
    enforce_simulatable: bool = False,
) -> tuple[DailyProposal, list[dict[str, object]]]:
    known_intents = {item.intent for item in catalog.activities}
    known_locations = {item.location_id for item in planning_case.locations}
    activities = list(proposal.activities)
    changes: list[dict[str, object]] = []

    def record(intent: str, reason: str) -> None:
        changes.append(
            {
                "date": proposal.date.isoformat(),
                "action": "insert",
                "intent": intent,
                "reason": reason,
            }
        )

    intents = [item.intent for item in activities]
    for position, intent in enumerate(intents):
        if (
            intent == "post_walk_shower"
            and not WALK_INTENTS.intersection(intents[:position])
            and "evening_hygiene" in known_intents
        ):
            original = activities[position]
            activities[position] = original.model_copy(
                update={
                    "intent": "evening_hygiene",
                    "rationale": (
                        "Deterministic ordinary hygiene replacement because "
                        "no walk occurred."
                    ),
                }
            )
            changes.append(
                {
                    "date": proposal.date.isoformat(),
                    "action": "replace",
                    "intent": "evening_hygiene",
                    "reason": "orphan_post_walk_shower",
                    "replaces": "post_walk_shower",
                }
            )

    intents = [item.intent for item in activities]
    if not HYGIENE_INTENTS.intersection(intents):
        candidates = [
            ("morning_toilet_and_shower", "bathroom_01"),
            ("morning_toilet_and_wash", "bathroom_01"),
        ]
        available = [
            item
            for item in candidates
            if item[0] in known_intents and item[1] in known_locations
        ]
        if available:
            intent, location = available[proposal.date.toordinal() % len(available)]
            insert_at = next(
                (
                    index + 1
                    for index, item in enumerate(activities)
                    if item.intent == "take_morning_medication"
                ),
                0,
            )
            activities.insert(
                insert_at,
                _scaffold_activity(
                    intent,
                    location,
                    TimeBand.early_morning,
                    DurationClass.short,
                    "Deterministic daily hygiene scaffold.",
                ),
            )
            record(intent, "missing_hygiene")

    intents = [item.intent for item in activities]
    if not NOURISHMENT_INTENTS.intersection(intents):
        workday_candidates = [
            "prepare_and_eat_breakfast",
            "eat_breakfast_and_read_news",
            "eat_breakfast_with_radio_news",
        ]
        weekend_candidates = [
            "prepare_weekend_breakfast",
            "prepare_and_eat_breakfast",
            "eat_breakfast_and_listen_to_radio",
        ]
        candidates = (
            workday_candidates if day_type == "workday" else weekend_candidates
        )
        available = [item for item in candidates if item in known_intents]
        if available and "kitchen_01" in known_locations:
            intent = available[proposal.date.toordinal() % len(available)]
            insert_at = next(
                (
                    index
                    for index, item in enumerate(activities)
                    if item.intent in {"commute_to_work", "work_shift", "sleep"}
                ),
                len(activities),
            )
            activities.insert(
                insert_at,
                _scaffold_activity(
                    intent,
                    "kitchen_01",
                    TimeBand.morning,
                    DurationClass.medium,
                    "Deterministic daily nourishment scaffold.",
                ),
            )
            record(intent, "missing_nourishment")

    intents = [item.intent for item in activities]
    if "work_shift" in intents:
        work_index = intents.index("work_shift")
        if "commute_to_work" not in intents[:work_index]:
            location = (
                "garden_workplace"
                if "garden_workplace" in known_locations
                else activities[work_index].location_id
            )
            activities.insert(
                work_index,
                _scaffold_activity(
                    "commute_to_work",
                    location,
                    TimeBand.morning,
                    DurationClass.short,
                    "Deterministic outbound work-travel scaffold.",
                ),
            )
            record("commute_to_work", "work_shift_chain")
        # commute_to_work only travels; the resident must be marked as having left home first
        # (leave_home) or the later commute_home enter_home step fails. Scaffold the explicit
        # departure before the outbound commute when the day does not already provide one.
        # This matters only when the plan is simulated, so it is gated behind a package.
        intents = [item.intent for item in activities]
        commute_out_index = intents.index("commute_to_work")
        if (
            enforce_simulatable
            and "collect_belongings_and_leave_home" in known_intents
            and "collect_belongings_and_leave_home" not in intents[:commute_out_index]
            and "leave_home" not in intents[:commute_out_index]
        ):
            leave_location = (
                "hallway_01"
                if "hallway_01" in known_locations
                else activities[commute_out_index].location_id
            )
            activities.insert(
                commute_out_index,
                _scaffold_activity(
                    "collect_belongings_and_leave_home",
                    leave_location,
                    TimeBand.morning,
                    DurationClass.short,
                    "Deterministic leave-home scaffold before the outbound commute.",
                ),
            )
            record("collect_belongings_and_leave_home", "work_shift_chain")
        intents = [item.intent for item in activities]
        work_index = intents.index("work_shift")
        if "commute_home" not in intents[work_index + 1 :]:
            # The return trip starts at the workplace; only relocate there when the plan is
            # simulated (otherwise keep the historical hallway placement for compatibility).
            preferred_return = "garden_workplace" if enforce_simulatable else "hallway_01"
            location = (
                preferred_return
                if preferred_return in known_locations
                else activities[work_index].location_id
            )
            activities.insert(
                work_index + 1,
                _scaffold_activity(
                    "commute_home",
                    location,
                    TimeBand.afternoon,
                    DurationClass.short,
                    "Deterministic return work-travel scaffold.",
                ),
            )
            record("commute_home", "work_shift_chain")

    intents = [item.intent for item in activities]
    if "visit_mother_and_have_dinner" in intents:
        visit_index = intents.index("visit_mother_and_have_dinner")
        if "travel_to_mothers_home" not in intents[:visit_index]:
            activities.insert(
                visit_index,
                _scaffold_activity(
                    "travel_to_mothers_home",
                    "mother_house_barcelona",
                    TimeBand.afternoon,
                    DurationClass.short,
                    "Deterministic outbound family-visit scaffold.",
                ),
            )
            record("travel_to_mothers_home", "mother_visit_chain")
        intents = [item.intent for item in activities]
        visit_index = intents.index("visit_mother_and_have_dinner")
        if "travel_home" not in intents[visit_index + 1 :]:
            home_location = (
                "hallway_01"
                if "hallway_01" in known_locations
                else "living_room_01"
            )
            activities.insert(
                visit_index + 1,
                _scaffold_activity(
                    "travel_home",
                    home_location,
                    TimeBand.evening,
                    DurationClass.short,
                    "Deterministic return family-visit scaffold.",
                ),
            )
            record("travel_home", "mother_visit_chain")

    # Drop exact duplicate activities (same intent, location and time band): the model
    # sometimes emits a routine twice, which wastes a slot and inflates day-to-day similarity.
    if enforce_simulatable:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[ProposedActivity] = []
        for activity in activities:
            key = (activity.intent, activity.location_id, activity.time_band.value)
            if key in seen:
                changes.append(
                    {
                        "date": proposal.date.isoformat(),
                        "action": "remove",
                        "intent": activity.intent,
                        "reason": "duplicate_activity",
                    }
                )
                continue
            seen.add(key)
            deduped.append(activity)
        activities = deduped

    # Realize any assigned goal intent the model dropped: placing an indoor variety activity
    # is mechanical (the model already chose the goal in the weekly brief), so the machine
    # scaffolds it deterministically rather than bouncing the day back to the model.
    if enforce_simulatable and required_goal_intents:
        present = {item.intent for item in activities}
        placements = habit_placements or {}
        category_by_intent = {item.intent: item.category for item in catalog.activities}
        for intent in sorted(required_goal_intents - present):
            # Prefer the resident's own habit placement (covers external round-trip habits
            # such as short_evening_walk); otherwise fall back to the indoor category map.
            location: str | None = None
            band = TimeBand.evening
            placement = placements.get(intent)
            if placement is not None and placement[0] in known_locations:
                location = placement[0]
                band = TimeBand(placement[1])
            else:
                preferred = _GOAL_CATEGORY_LOCATIONS.get(category_by_intent.get(intent, ""))
                if preferred:
                    location = next((loc for loc in preferred if loc in known_locations), None)
            if location is None:
                continue
            insert_at = next(
                (index for index, item in enumerate(activities) if item.intent == "sleep"),
                len(activities),
            )
            activities.insert(
                insert_at,
                _scaffold_activity(
                    intent,
                    location,
                    band,
                    DurationClass.short,
                    "Deterministic goal-intent realization scaffold.",
                ),
            )
            record(intent, "goal_intent")

    normalized = proposal.model_copy(update={"activities": activities})
    if enforce_simulatable and final_date is not None:
        normalized, removed = fit_day_to_time_budget(
            planning_case, normalized, protected_intents, final_date
        )
        for intent in removed:
            changes.append(
                {
                    "date": proposal.date.isoformat(),
                    "action": "remove",
                    "intent": intent,
                    "reason": "time_budget_trim",
                }
            )
    return normalized, changes


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
