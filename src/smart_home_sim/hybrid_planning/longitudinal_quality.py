from __future__ import annotations

import math
from datetime import date

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralProfile,
    HabitKind,
)
from smart_home_sim.hybrid_planning.guardrails import (
    daily_life_violations,
    semantic_violations,
)
from smart_home_sim.hybrid_planning.habit_gates import (
    effective_habit_time_bands,
    expected_habit_occurrences,
)
from smart_home_sim.hybrid_planning.longitudinal_models import (
    CausalViolation,
    LongitudinalHabitMetric,
    LongitudinalQualityReport,
)
from smart_home_sim.hybrid_planning.metrics import day_signature
from smart_home_sim.hybrid_planning.models import DailyProposal

WORK_TRAVEL_INTENTS = {"commute_to_work", "travel_to_work"}


def _day_type(value: date) -> str:
    return "workday" if value.weekday() < 5 else "weekend"


def _maximum_identical_run(proposals: list[DailyProposal]) -> int:
    maximum = 0
    current = 0
    previous: str | None = None
    for proposal in proposals:
        signature = day_signature(proposal)
        current = current + 1 if signature == previous else 1
        maximum = max(maximum, current)
        previous = signature
    return maximum


def _causal_violations(
    profile: BehavioralProfile,
    proposals: list[DailyProposal],
) -> list[CausalViolation]:
    habits = {item.intent: item for item in profile.habits}
    violations: list[CausalViolation] = []
    for proposal in proposals:
        intents = [item.intent for item in proposal.activities]
        for position, intent in enumerate(intents):
            if intent in WORK_TRAVEL_INTENTS and "work_shift" not in intents[position + 1 :]:
                violations.append(
                    CausalViolation(
                        code="WORK_TRAVEL_WITHOUT_SHIFT",
                        date=proposal.date,
                        intent=intent,
                        message="outbound work travel requires a later work_shift",
                    )
                )
            habit = habits.get(intent)
            if habit is None:
                continue
            missing_predecessors = [
                required
                for required in habit.predecessor_intents
                if required not in intents[:position]
            ]
            missing_successors = [
                required
                for required in habit.successor_intents
                if required not in intents[position + 1 :]
            ]
            for required in missing_predecessors:
                violations.append(
                    CausalViolation(
                        code="MISSING_HABIT_PREDECESSOR",
                        date=proposal.date,
                        intent=intent,
                        message=f"{intent} requires earlier {required}",
                    )
                )
            for required in missing_successors:
                violations.append(
                    CausalViolation(
                        code="MISSING_HABIT_SUCCESSOR",
                        date=proposal.date,
                        intent=intent,
                        message=f"{intent} requires later {required}",
                    )
                )
    return violations


def _semantic_quality_violations(
    profile: BehavioralProfile,
    proposals: list[DailyProposal],
) -> list[CausalViolation]:
    legacy = _causal_violations(profile, proposals)
    result = list(legacy)
    keys = {
        (item.code, item.date, item.intent, item.message)
        for item in result
    }
    legacy_chain_dates = {
        (item.date, item.intent)
        for item in legacy
        if item.code
        in {"MISSING_HABIT_PREDECESSOR", "MISSING_HABIT_SUCCESSOR"}
    }
    for proposal in proposals:
        for item in semantic_violations(profile, proposal):
            if (
                item.code == "MOTHER_VISIT_CHAIN_INCOMPLETE"
                and (item.date, item.intent) in legacy_chain_dates
            ):
                continue
            key = (item.code, item.date, item.intent, item.message)
            if key not in keys:
                keys.add(key)
                result.append(item)
    return result


def _habit_metrics(
    profile: BehavioralProfile,
    proposals: list[DailyProposal],
) -> tuple[list[LongitudinalHabitMetric], set[str]]:
    metrics: list[LongitudinalHabitMetric] = []
    reasons: set[str] = set()
    dates = [item.date for item in proposals]
    day_types = {value: _day_type(value) for value in dates}
    for habit in profile.habits:
        expected = expected_habit_occurrences(habit, dates, day_types)
        lower = math.floor(expected)
        upper = math.ceil(expected)
        matched = [
            (proposal, activity)
            for proposal in proposals
            for activity in proposal.activities
            if activity.intent == habit.intent
        ]
        observed = len(matched)
        temporal_matches = sum(
            activity.time_band
            in effective_habit_time_bands(habit, proposal.date)
            for proposal, activity in matched
        )
        location_matches = sum(
            activity.location_id in habit.location_ids
            for _proposal, activity in matched
        )
        temporal_adherence = temporal_matches / observed if observed else 1.0
        location_adherence = location_matches / observed if observed else 1.0
        metrics.append(
            LongitudinalHabitMetric(
                habit_id=habit.habit_id,
                intent=habit.intent,
                expected_occurrences=expected,
                lower_occurrences=lower,
                upper_occurrences=upper,
                observed_occurrences=observed,
                target_deviation=observed - expected,
                temporal_adherence=temporal_adherence,
                location_adherence=location_adherence,
            )
        )
        if observed < lower or observed > upper:
            reasons.add("HABIT_FREQUENCY_DEVIATION")
        if temporal_adherence < 1.0:
            reasons.add("HABIT_TEMPORAL_DEVIATION")
        if location_adherence < 1.0:
            reasons.add("HABIT_LOCATION_DEVIATION")
    return metrics, reasons


def _empty_variable_windows(
    proposals: list[DailyProposal],
    variable_intents: set[str],
) -> list[date]:
    empty: list[date] = []
    for start in range(0, len(proposals) - 6, 7):
        window = proposals[start : start + 7]
        has_variation = any(
            activity.intent in variable_intents
            for proposal in window
            for activity in proposal.activities
        )
        if not has_variation:
            empty.append(window[0].date)
    return empty


def evaluate_longitudinal_quality(
    profile: BehavioralProfile,
    proposals: list[DailyProposal],
) -> LongitudinalQualityReport:
    ordered = sorted(proposals, key=lambda item: item.date)
    variable_intents = {
        item.intent
        for item in profile.habits
        if item.kind in {HabitKind.optional, HabitKind.rare}
    }
    empty_windows = _empty_variable_windows(ordered, variable_intents)
    maximum_run = _maximum_identical_run(ordered)
    semantic = _semantic_quality_violations(profile, ordered)
    daily_life = [
        violation
        for proposal in ordered
        for violation in daily_life_violations(_day_type(proposal.date), proposal)
    ]
    habit_metrics, habit_reasons = _habit_metrics(profile, ordered)
    activity_counts = [len(item.activities) for item in ordered]
    reasons: list[str] = []
    if maximum_run > 3:
        reasons.append("CONSECUTIVE_DUPLICATE_DAYS")
    if empty_windows:
        reasons.append("MISSING_WEEKLY_VARIABLE_SHELL")
    if daily_life:
        reasons.append("DAILY_LIFE_VIOLATIONS")
    if semantic:
        reasons.append("SEMANTIC_VIOLATIONS")
    reasons.extend(sorted(habit_reasons))
    return LongitudinalQualityReport(
        valid=not reasons,
        day_count=len(ordered),
        maximum_consecutive_identical_days=maximum_run,
        mean_daily_activities=(
            sum(activity_counts) / len(activity_counts)
            if activity_counts
            else 0
        ),
        minimum_daily_activities=min(activity_counts, default=0),
        maximum_daily_activities=max(activity_counts, default=0),
        optional_windows_without_variation=empty_windows,
        causal_violations=semantic,
        daily_life_violations=daily_life,
        habit_metrics=habit_metrics,
        reasons=reasons,
    )
