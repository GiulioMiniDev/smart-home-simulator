from __future__ import annotations

from datetime import date

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralProfile,
    HabitKind,
)
from smart_home_sim.hybrid_planning.longitudinal_models import (
    CausalViolation,
    LongitudinalQualityReport,
)
from smart_home_sim.hybrid_planning.metrics import day_signature
from smart_home_sim.hybrid_planning.models import DailyProposal

WORK_TRAVEL_INTENTS = {"commute_to_work", "travel_to_work"}


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
    causal = _causal_violations(profile, ordered)
    reasons: list[str] = []
    if maximum_run > 3:
        reasons.append("CONSECUTIVE_DUPLICATE_DAYS")
    if empty_windows:
        reasons.append("MISSING_WEEKLY_VARIABLE_SHELL")
    if causal:
        reasons.append("CAUSAL_VIOLATIONS")
    return LongitudinalQualityReport(
        valid=not reasons,
        day_count=len(ordered),
        maximum_consecutive_identical_days=maximum_run,
        optional_windows_without_variation=empty_windows,
        causal_violations=causal,
        reasons=reasons,
    )
