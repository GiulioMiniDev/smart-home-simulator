from __future__ import annotations

import math
from datetime import date, timedelta

from smart_home_sim.hybrid_planning.behavioral_models import (
    BehavioralHabit,
    BehavioralProfile,
    HabitBudget,
    HabitBudgetItem,
    HabitCadence,
    HabitGateReport,
    HabitKind,
    HabitLedger,
    HabitLedgerEntry,
    HabitTraceMetric,
    HabitViolation,
    PlannedHabitOccurrence,
    PlannedHabitTrace,
)
from smart_home_sim.hybrid_planning.behavioral_validation import (
    behavioral_profile_digest,
)
from smart_home_sim.hybrid_planning.models import DailyProposal, WeeklyBrief

GATE_CODES = (
    "HABIT_REQUIRED_MISSING",
    "HABIT_FREQUENCY_EXCEEDED",
    "HABIT_DAILY_ANCHOR_MISSING",
    "HABIT_DAILY_ANCHOR_EXCEEDED",
    "HABIT_COOLDOWN_VIOLATION",
    "HABIT_CHAIN_PREDECESSOR_MISSING",
    "HABIT_CHAIN_SUCCESSOR_MISSING",
    "HABIT_INCOMPATIBLE_PAIR",
    "WEEKLY_GOAL_UNREALIZED",
)


def initial_habit_ledger(profile_digest: str, profile: BehavioralProfile) -> HabitLedger:
    if profile_digest != behavioral_profile_digest(profile):
        raise ValueError("behavioral profile digest does not match the profile")
    return HabitLedger(
        profile_digest=profile_digest,
        entries=[HabitLedgerEntry(habit_id=item.habit_id) for item in profile.habits],
    )


def _effective_cadence(habit: BehavioralHabit, on_date: date) -> HabitCadence:
    active = [item for item in habit.drifts if item.effective_from <= on_date]
    if not active:
        return habit.cadence
    latest = max(active, key=lambda item: item.effective_from)
    return latest.cadence_override or habit.cadence


def _eligible_dates(
    habit: BehavioralHabit,
    dates: list[date],
    day_types: dict[date, str],
) -> list[date]:
    if not habit.applicable_day_types:
        return list(dates)
    return [value for value in dates if day_types[value] in habit.applicable_day_types]


def _ledger_entries(profile: BehavioralProfile, ledger: HabitLedger) -> dict[str, HabitLedgerEntry]:
    expected = {item.habit_id for item in profile.habits}
    actual = {item.habit_id for item in ledger.entries}
    if actual != expected:
        raise ValueError("habit ledger entries do not match the behavioral profile")
    return {item.habit_id: item for item in ledger.entries}


def derive_habit_budget(
    profile: BehavioralProfile,
    ledger: HabitLedger,
    dates: list[date],
    day_types: dict[date, str],
) -> HabitBudget:
    digest = behavioral_profile_digest(profile)
    if ledger.profile_digest != digest:
        raise ValueError("habit ledger profile digest does not match behavioral profile")
    if not dates:
        raise ValueError("habit budget requires at least one date")
    entries = _ledger_entries(profile, ledger)
    items: list[HabitBudgetItem] = []
    for habit in profile.habits:
        cadence = _effective_cadence(habit, dates[0])
        eligible_days = len(_eligible_dates(habit, dates, day_types))
        expected = cadence.typical_occurrences * eligible_days / cadence.period_days
        minimum = math.floor(cadence.minimum_occurrences * eligible_days / cadence.period_days)
        maximum = math.ceil(cadence.maximum_occurrences * eligible_days / cadence.period_days)
        if habit.kind is not HabitKind.anchor and cadence.maximum_occurrences and eligible_days:
            maximum = max(1, maximum)
        target = max(minimum, math.floor(entries[habit.habit_id].cadence_carry + expected))
        target = min(target, maximum)
        forbidden_until = None
        entry = entries[habit.habit_id]
        if entry.last_seen is not None and habit.cooldown_days:
            candidate = entry.last_seen + timedelta(days=habit.cooldown_days)
            if candidate >= dates[0]:
                forbidden_until = candidate
        items.append(
            HabitBudgetItem(
                habit_id=habit.habit_id,
                intent=habit.intent,
                required_occurrences=minimum,
                target_occurrences=target,
                maximum_occurrences=maximum,
                forbidden_until=forbidden_until,
            )
        )
    return HabitBudget(
        profile_digest=digest,
        start_date=dates[0],
        end_date=dates[-1],
        items=items,
    )


def _proposal_map(proposals: list[DailyProposal]) -> dict[date, DailyProposal]:
    return {item.date: item for item in proposals}


def _default_day_types(proposals: list[DailyProposal]) -> dict[date, str]:
    return {
        item.date: "workday" if item.date.weekday() < 5 else "weekend" for item in proposals
    }


def _repair_date(
    habit: BehavioralHabit,
    proposals: list[DailyProposal],
    day_types: dict[date, str],
) -> date:
    eligible = _eligible_dates(habit, [item.date for item in proposals], day_types)
    return eligible[0] if eligible else proposals[0].date


def evaluate_habit_plan(
    profile: BehavioralProfile,
    ledger: HabitLedger,
    budget: HabitBudget,
    brief: WeeklyBrief,
    proposals: list[DailyProposal],
) -> HabitGateReport:
    if ledger.profile_digest != budget.profile_digest:
        raise ValueError("habit gate inputs use different profile digests")
    if not proposals:
        raise ValueError("habit gate requires daily proposals")
    violations: list[HabitViolation] = []
    budget_by_habit = {item.habit_id: item for item in budget.items}
    proposals_by_date = _proposal_map(proposals)
    day_types = {item.date: item.day_type for item in brief.days}
    occurrences: dict[str, list[date]] = {}
    for habit in profile.habits:
        dates = [
            proposal.date
            for proposal in proposals
            for activity in proposal.activities
            if activity.intent == habit.intent
        ]
        occurrences[habit.habit_id] = dates
        item = budget_by_habit[habit.habit_id]
        if len(dates) < item.required_occurrences:
            violations.append(
                HabitViolation(
                    code="HABIT_REQUIRED_MISSING",
                    message=(
                        f"{habit.intent} requires {item.required_occurrences}; found {len(dates)}"
                    ),
                    date=_repair_date(habit, proposals, day_types),
                    habit_id=habit.habit_id,
                    intent=habit.intent,
                )
            )
        if len(dates) > item.maximum_occurrences:
            violations.append(
                HabitViolation(
                    code="HABIT_FREQUENCY_EXCEEDED",
                    message=(
                        f"{habit.intent} allows {item.maximum_occurrences}; found {len(dates)}"
                    ),
                    date=dates[-1],
                    habit_id=habit.habit_id,
                    intent=habit.intent,
                )
            )
        cadence = _effective_cadence(habit, proposals[0].date)
        if habit.kind is HabitKind.anchor and cadence.period_days == 1:
            for value in _eligible_dates(habit, [item.date for item in proposals], day_types):
                count = sum(
                    activity.intent == habit.intent
                    for activity in proposals_by_date[value].activities
                )
                if count < cadence.minimum_occurrences:
                    violations.append(
                        HabitViolation(
                            code="HABIT_DAILY_ANCHOR_MISSING",
                            message=f"daily anchor {habit.intent} is missing",
                            date=value,
                            habit_id=habit.habit_id,
                            intent=habit.intent,
                        )
                    )
                if count > cadence.maximum_occurrences:
                    violations.append(
                        HabitViolation(
                            code="HABIT_DAILY_ANCHOR_EXCEEDED",
                            message=f"daily anchor {habit.intent} occurs {count} times",
                            date=value,
                            habit_id=habit.habit_id,
                            intent=habit.intent,
                        )
                    )
        previous = next(
            (item.last_seen for item in ledger.entries if item.habit_id == habit.habit_id),
            None,
        )
        for value in sorted(dates):
            if (
                previous is not None
                and habit.cooldown_days
                and value <= previous + timedelta(days=habit.cooldown_days)
            ):
                violations.append(
                    HabitViolation(
                        code="HABIT_COOLDOWN_VIOLATION",
                        message=(
                            f"{habit.intent} violates its {habit.cooldown_days}-day cooldown"
                        ),
                        date=value,
                        habit_id=habit.habit_id,
                        intent=habit.intent,
                    )
                )
            previous = value
        for proposal in proposals:
            intents = [item.intent for item in proposal.activities]
            for position, intent in enumerate(intents):
                if intent != habit.intent:
                    continue
                for required in habit.predecessor_intents:
                    if required not in intents[:position]:
                        violations.append(
                            HabitViolation(
                                code="HABIT_CHAIN_PREDECESSOR_MISSING",
                                message=f"{habit.intent} requires earlier {required}",
                                date=proposal.date,
                                habit_id=habit.habit_id,
                                intent=habit.intent,
                            )
                        )
                for required in habit.successor_intents:
                    if required not in intents[position + 1 :]:
                        violations.append(
                            HabitViolation(
                                code="HABIT_CHAIN_SUCCESSOR_MISSING",
                                message=f"{habit.intent} requires later {required}",
                                date=proposal.date,
                                habit_id=habit.habit_id,
                                intent=habit.intent,
                            )
                        )
            incompatible_intents = {
                item.intent
                for item in profile.habits
                if item.habit_id in habit.incompatible_habit_ids
            }
            if habit.intent in intents and incompatible_intents.intersection(intents):
                violations.append(
                    HabitViolation(
                        code="HABIT_INCOMPATIBLE_PAIR",
                        message=f"{habit.intent} occurs with an incompatible habit",
                        date=proposal.date,
                        habit_id=habit.habit_id,
                        intent=habit.intent,
                    )
                )
    for day in brief.days:
        proposal = proposals_by_date.get(day.date)
        planned = {item.intent for item in proposal.activities} if proposal else set()
        for intent in day.goal_intents:
            if intent not in planned:
                violations.append(
                    HabitViolation(
                        code="WEEKLY_GOAL_UNREALIZED",
                        message=f"weekly goal intent is absent: {intent}",
                        date=day.date,
                        intent=intent,
                    )
                )
    return HabitGateReport(valid=not violations, violations=violations)


def _sequence_complete(habit: BehavioralHabit, proposal: DailyProposal, position: int) -> bool:
    intents = [item.intent for item in proposal.activities]
    return all(item in intents[:position] for item in habit.predecessor_intents) and all(
        item in intents[position + 1 :] for item in habit.successor_intents
    )


def planned_habit_trace(
    profile: BehavioralProfile,
    profile_digest: str,
    budget: HabitBudget,
    proposals: list[DailyProposal],
) -> PlannedHabitTrace:
    if profile_digest != behavioral_profile_digest(profile):
        raise ValueError("planned trace profile digest does not match behavioral profile")
    budget_by_habit = {item.habit_id: item for item in budget.items}
    occurrences: list[PlannedHabitOccurrence] = []
    metrics: list[HabitTraceMetric] = []
    for habit in profile.habits:
        matched: list[tuple[DailyProposal, int]] = []
        for proposal in proposals:
            for position, activity in enumerate(proposal.activities):
                if activity.intent == habit.intent:
                    matched.append((proposal, position))
                    occurrences.append(
                        PlannedHabitOccurrence(
                            habit_id=habit.habit_id,
                            intent=habit.intent,
                            date=proposal.date,
                            time_band=activity.time_band,
                        )
                    )
        temporal = (
            sum(
                proposal.activities[position].time_band in habit.preferred_time_bands
                for proposal, position in matched
            )
            / len(matched)
            if matched
            else 1.0
        )
        sequence = (
            sum(_sequence_complete(habit, proposal, position) for proposal, position in matched)
            / len(matched)
            if matched
            else 1.0
        )
        metrics.append(
            HabitTraceMetric(
                habit_id=habit.habit_id,
                expected_occurrences=float(budget_by_habit[habit.habit_id].target_occurrences),
                planned_occurrences=len(matched),
                temporal_adherence=temporal,
                sequence_adherence=sequence,
                mining_difficulty=habit.mining_difficulty,
            )
        )
    return PlannedHabitTrace(
        profile_digest=profile_digest,
        occurrences=occurrences,
        metrics=metrics,
    )


def update_habit_ledger(
    profile: BehavioralProfile,
    profile_digest: str,
    ledger: HabitLedger,
    proposals: list[DailyProposal],
) -> HabitLedger:
    if (
        profile_digest != behavioral_profile_digest(profile)
        or ledger.profile_digest != profile_digest
    ):
        raise ValueError("habit ledger profile digest does not match behavioral profile")
    if not proposals:
        raise ValueError("habit ledger update requires daily proposals")
    entries = _ledger_entries(profile, ledger)
    dates = [item.date for item in proposals]
    day_types = _default_day_types(proposals)
    updated: list[HabitLedgerEntry] = []
    for habit in profile.habits:
        entry = entries[habit.habit_id]
        matched_dates = [
            proposal.date
            for proposal in proposals
            if any(activity.intent == habit.intent for activity in proposal.activities)
        ]
        eligible_days = len(_eligible_dates(habit, dates, day_types))
        cadence = _effective_cadence(habit, dates[0])
        expected = cadence.typical_occurrences * eligible_days / cadence.period_days
        updated.append(
            HabitLedgerEntry(
                habit_id=habit.habit_id,
                total_occurrences=entry.total_occurrences + len(matched_dates),
                last_seen=max(matched_dates) if matched_dates else entry.last_seen,
                cadence_carry=entry.cadence_carry + expected - len(matched_dates),
            )
        )
    return HabitLedger(
        profile_digest=profile_digest,
        through_date=max(dates),
        entries=updated,
    )
