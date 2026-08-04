from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.compiler.issues import compilation_issue
from smart_home_sim.compiler.solver import (
    CompilationBudgetError,
    ScheduledValue,
    ScheduleSolver,
    SolveOutcome,
    SolverRangeError,
    SourceRecord,
    TimeAxis,
    TimePrecisionError,
    activity_records,
)
from smart_home_sim.domain.compilation import (
    CompilationIssue,
    CompilationReport,
    CompilationSummary,
)
from smart_home_sim.domain.models import ActivationMode, DependencyMode, Scenario
from smart_home_sim.domain.plan import (
    CanonicalActivity,
    CanonicalDay,
    CanonicalPlan,
    ContingencyPlan,
    ObjectiveValues,
    OmittedActivity,
)
from smart_home_sim.validation.service import validate_file, validate_payload


@dataclass(frozen=True, slots=True)
class CompilationResult:
    plan: CanonicalPlan | None
    report: CompilationReport


# Days a single solve covers once the horizon is long enough to be worth splitting.
#
# Canonicalisation costs one full solve of the *whole* model per value it fixes, and it fixes a
# few per activity: measured on one generated case, 426 solves for 31 days, 1502 for 92, with the
# cost of each solve growing linearly in the horizon too. Both factors are linear, so the product
# is quadratic — 75s at one month, 13 minutes at three, and an extrapolated hour and a half at
# eight. Solving a week at a time makes the per-solve cost independent of the horizon and brings
# the total back to linear.
COMPILATION_WINDOW_DAYS = 7
# Below this the whole horizon is one cheap solve and splitting only adds boundaries.
COMPILATION_WINDOW_THRESHOLD_DAYS = 45


def canonical_sha256(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compile_file(path: Path) -> CompilationResult:
    validation_report = validate_file(path)
    if not validation_report.valid:
        return _invalid_input_result(validation_report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenario = Scenario.model_validate_json(json.dumps(payload, separators=(",", ":")))
    return compile_scenario(scenario)


def compile_payload(
    payload: Any,
    on_progress: Callable[[int, int], None] | None = None,
) -> CompilationResult:
    validation_report = validate_payload(payload)
    if not validation_report.valid:
        return _invalid_input_result(validation_report)
    scenario = Scenario.model_validate_json(json.dumps(payload, separators=(",", ":")))
    return compile_scenario(scenario, on_progress)


def _windows_are_safe(records: list[SourceRecord]) -> bool:
    """Can this scenario be solved a window at a time without changing what the answer means?

    Two activities on different days interact in exactly one way: an activity that is still
    running when the next day begins, which here is the overnight sleep — 23 of one month's 31
    nights end after midnight. That reaches only the following day, so carrying the previous
    window's last day into the next solve as a fixed schedule preserves it.

    A dependency does not have that shape. It can name any activity anywhere in the horizon, and a
    predecessor the current window has not solved yet would silently drop its successor. The
    generated horizons declare none, so rather than reason about which ones would be safe, the
    split is simply refused when any exist.
    """
    return not any(record.activity.dependency_groups for record in records)


def _solve_in_windows(
    scenario: Scenario,
    axis: TimeAxis,
    records: list[SourceRecord],
    on_progress: Callable[[int, int], None] | None = None,
) -> SolveOutcome:
    """Solve the horizon a window at a time, each one seeing the previous window's last day.

    The objective is a sum over activities in every one of its five components, so adding the
    windows up reproduces what the single solve reports.
    """
    by_day: dict[int, list[SourceRecord]] = defaultdict(list)
    for record in records:
        by_day[record.day_index].append(record)
    ordered_days = sorted(by_day)

    values: dict[str, ScheduledValue] = {}
    omitted: list[str] = []
    totals = [0, 0, 0, 0, 0]
    for start in range(0, len(ordered_days), COMPILATION_WINDOW_DAYS):
        window_days = ordered_days[start : start + COMPILATION_WINDOW_DAYS]
        # One day of lookahead. Without it the window's last night is placed with nothing after it
        # to push against, takes its full preferred length, and leaves the next morning — whose
        # activities are mandatory and narrow — nowhere to go: the following window is then
        # infeasible. The lookahead day is solved here and committed by the next window, so what
        # that window fixes is a night it has already seen a feasible morning for.
        after = start + COMPILATION_WINDOW_DAYS
        lookahead = ordered_days[after : after + 1]
        solved_days = [*window_days, *lookahead]
        window_records = [record for day in solved_days for record in by_day[day]]
        committed_ids = {
            record.activity.activity_id for day in window_days for record in by_day[day]
        }
        # Only the day immediately before the window can still be occupying the resident when it
        # opens; everything earlier has certainly finished and would just enlarge the model.
        carried = {
            activity_id: value
            for activity_id, value in values.items()
            if value.record.day_index == window_days[0] - 1
        }
        outcome = ScheduleSolver(
            scenario,
            axis,
            window_records,
            fixed_schedule=carried,
            reported_activity_ids=committed_ids,
        ).solve()
        if outcome.failure is not None:
            return outcome
        assert outcome.objective_values is not None
        values.update(
            {
                activity_id: value
                for activity_id, value in outcome.values.items()
                if activity_id in committed_ids
            }
        )
        omitted.extend(
            activity_id
            for activity_id in outcome.omitted_activity_ids
            if activity_id in committed_ids
        )
        totals = [
            totals[0] + outcome.objective_values.optional_priority_score,
            totals[1] + outcome.objective_values.optional_activity_count,
            totals[2] + outcome.objective_values.duration_deviation_microseconds,
            totals[3] + outcome.objective_values.temporal_deviation_microseconds,
            totals[4] + outcome.objective_values.scheduled_start_sum_microseconds,
        ]
        if on_progress is not None:
            on_progress(len(values) + len(omitted), len(records))
    return SolveOutcome(
        status="OPTIMAL",
        values=values,
        omitted_activity_ids=tuple(omitted),
        objective_values=ObjectiveValues(
            optional_priority_score=totals[0],
            optional_activity_count=totals[1],
            duration_deviation_microseconds=totals[2],
            temporal_deviation_microseconds=totals[3],
            scheduled_start_sum_microseconds=totals[4],
        ),
    )


def compile_scenario(
    scenario: Scenario,
    on_progress: Callable[[int, int], None] | None = None,
) -> CompilationResult:
    records = activity_records(scenario)
    branch_by_activity, branch_records, preflight_issues = _classify_branches(records)
    if preflight_issues:
        return _failure_result(
            scenario,
            preflight_issues,
            solver_status=None,
            objective_values=None,
        )

    try:
        axis = TimeAxis.from_scenario(scenario, records)
        main_records = [
            record for record in records if branch_by_activity[record.activity.activity_id] is None
        ]
        if len(scenario.days) > COMPILATION_WINDOW_THRESHOLD_DAYS and _windows_are_safe(
            main_records
        ):
            main_outcome = _solve_in_windows(scenario, axis, main_records, on_progress)
        else:
            main_outcome = ScheduleSolver(scenario, axis, main_records).solve()
    except CompilationBudgetError as error:
        # The defect this exists for is not a wrong plan but an absent answer: a horizon whose
        # canonicalisation never finishes used to hold the request open with no error and no
        # progress. Reporting the budget turns that silence into something a researcher can read
        # and act on.
        return _failure_result(
            scenario,
            [
                compilation_issue(
                    "COMPILATION_BUDGET_EXCEEDED",
                    "main_plan",
                    "$",
                    "Canonicalisation exceeded the compilation budget: the scenario needs more "
                    "deterministic value-fixing probes than the compiler is allowed to spend. "
                    "Shorten the horizon or widen the declared windows so fewer preferred values "
                    "collide.",
                    details={
                        "probes": error.probes,
                        "budget": error.budget,
                        "activityCount": len(records),
                        "dayCount": len(scenario.days),
                    },
                )
            ],
            solver_status=None,
            objective_values=None,
        )
    except TimePrecisionError as error:
        return _failure_result(
            scenario,
            [
                compilation_issue(
                    "TIME_PRECISION_UNREPRESENTABLE",
                    "preflight",
                    "$.days",
                    "A time value cannot be represented exactly at microsecond resolution.",
                    details={
                        "activityId": error.activity_id,
                        "field": error.field_name,
                        "value": error.value,
                    },
                )
            ],
            solver_status=None,
            objective_values=None,
        )
    except SolverRangeError as error:
        return _failure_result(
            scenario,
            [
                compilation_issue(
                    "HORIZON_EXCEEDS_SOLVER_RANGE",
                    "preflight",
                    "$.simulationWindow",
                    str(error),
                )
            ],
            solver_status=None,
            objective_values=None,
        )

    if main_outcome.failure is not None:
        return _solver_failure_result(
            scenario,
            main_outcome.failure,
            main_outcome.status,
            "main_plan",
            "MAIN_PLAN_INFEASIBLE",
            main_outcome.model_error,
        )
    assert main_outcome.objective_values is not None

    issues: list[CompilationIssue] = []
    contingency_plans: list[tuple[SourceRecord, ContingencyPlan]] = []
    for branch_id, grouped_records in sorted(branch_records.items()):
        representative = grouped_records[0]
        activation = representative.activity.activation
        target_id = activation.fallback_for_activity_id
        if target_id is not None and target_id not in main_outcome.values:
            omitted = [
                OmittedActivity(
                    source_activity_id=record.activity.activity_id,
                    reason="contingency_target_not_scheduled",
                )
                for record in grouped_records
            ]
            contingency_plans.append(
                (
                    representative,
                    ContingencyPlan(
                        contingency_id=branch_id,
                        kind="fallback",
                        activation=activation,
                        replaces_activity_id=target_id,
                        activities=[],
                        rescheduled_activities=[],
                        omitted_activities=omitted,
                        objective_values=_zero_objectives(),
                    ),
                )
            )
            issues.append(
                compilation_issue(
                    "CONTINGENCY_TARGET_NOT_SCHEDULED",
                    "contingency",
                    representative.path,
                    f"Contingency '{branch_id}' is inactive because target '{target_id}' "
                    "was not selected in the main plan.",
                    details={"contingencyId": branch_id, "targetActivityId": target_id},
                )
            )
            continue

        branch_activity_ids = {record.activity.activity_id for record in grouped_records}
        selected_day_values = {
            activity_id: value
            for activity_id, value in main_outcome.values.items()
            if value.record.day.date == representative.day.date
        }
        selected_day_ids = set(selected_day_values)
        alternate_main_ids = selected_day_ids - ({target_id} if target_id is not None else set())
        alternate_records = [
            main_outcome.values[activity_id].record for activity_id in sorted(alternate_main_ids)
        ]
        anchors = (
            {
                record.activity.activity_id: main_outcome.values[target_id].start
                for record in grouped_records
            }
            if target_id is not None
            else {}
        )
        try:
            contingency_outcome = ScheduleSolver(
                scenario,
                axis,
                [*alternate_records, *grouped_records],
                fixed_schedule=main_outcome.values,
                excluded_fixed_activity_ids=selected_day_ids,
                default_start_anchors=anchors,
            ).solve()
        except (TimePrecisionError, SolverRangeError) as error:
            issue = (
                compilation_issue(
                    "TIME_PRECISION_UNREPRESENTABLE",
                    "contingency",
                    representative.path,
                    str(error),
                    details={"contingencyId": branch_id},
                )
                if isinstance(error, TimePrecisionError)
                else compilation_issue(
                    "HORIZON_EXCEEDS_SOLVER_RANGE",
                    "contingency",
                    representative.path,
                    str(error),
                    details={"contingencyId": branch_id},
                )
            )
            return _failure_result(
                scenario,
                [*issues, issue],
                solver_status=None,
                objective_values=main_outcome.objective_values,
            )
        if contingency_outcome.failure is not None:
            return _solver_failure_result(
                scenario,
                contingency_outcome.failure,
                contingency_outcome.status,
                "contingency",
                "CONTINGENCY_PLAN_INFEASIBLE",
                contingency_outcome.model_error,
                details={"contingencyId": branch_id},
                objective_values=main_outcome.objective_values,
                prior_issues=issues,
            )
        assert contingency_outcome.objective_values is not None
        contingency_plans.append(
            (
                representative,
                ContingencyPlan(
                    contingency_id=branch_id,
                    kind=(
                        "fallback" if activation.mode is ActivationMode.fallback else "conditional"
                    ),
                    activation=activation,
                    replaces_activity_id=target_id,
                    activities=_canonical_activities(
                        {
                            activity_id: value
                            for activity_id, value in contingency_outcome.values.items()
                            if activity_id in branch_activity_ids
                        },
                        axis,
                        scenario,
                    ),
                    rescheduled_activities=_rescheduled_activities(
                        contingency_outcome.values,
                        selected_day_values,
                        alternate_main_ids,
                        axis,
                        scenario,
                    ),
                    omitted_activities=[
                        OmittedActivity(
                            source_activity_id=activity_id,
                            reason=(
                                "contingency_optional_not_selected"
                                if activity_id in branch_activity_ids
                                else "contingency_main_activity_omitted"
                            ),
                        )
                        for activity_id in contingency_outcome.omitted_activity_ids
                    ],
                    objective_values=contingency_outcome.objective_values,
                ),
            )
        )

    plan = _build_plan(
        scenario,
        axis,
        records,
        main_outcome.values,
        main_outcome.omitted_activity_ids,
        main_outcome.objective_values,
        contingency_plans,
    )
    try:
        CanonicalPlan.model_validate(plan.model_dump(mode="python", by_alias=True))
    except ValidationError as error:
        return _failure_result(
            scenario,
            [
                compilation_issue(
                    "CANONICAL_PLAN_INVALID",
                    "output",
                    "$",
                    "The generated canonical plan violates its output contract.",
                    details={"errorCount": error.error_count()},
                )
            ],
            solver_status=main_outcome.status,
            objective_values=main_outcome.objective_values,
        )

    plan_digest = canonical_sha256(plan)
    report = _build_report(
        scenario=scenario,
        plan=plan,
        plan_digest=plan_digest,
        issues=issues,
        solver_status=main_outcome.status,
        objective_values=main_outcome.objective_values,
    )
    return CompilationResult(plan=plan, report=report)


def _classify_branches(
    records: list[SourceRecord],
) -> tuple[
    dict[str, str | None],
    dict[str, list[SourceRecord]],
    list[CompilationIssue],
]:
    branch_by_activity: dict[str, str | None] = {}
    grouped: dict[str, list[SourceRecord]] = defaultdict(list)
    record_by_id = {record.activity.activity_id: record for record in records}
    for record in records:
        activity = record.activity
        if activity.activation.mode is ActivationMode.always:
            branch_id = None
        elif activity.activation.mode is ActivationMode.fallback:
            branch_id = (
                f"fallback__{record.day.date}__"
                f"{activity.activation.fallback_for_activity_id}__"
                f"{activity.activation.fallback_trigger}"
            )
        else:
            condition_digest = canonical_sha256(activity.activation.condition)[:16]
            branch_id = f"conditional__{record.day.date}__{condition_digest}"
        branch_by_activity[activity.activity_id] = branch_id
        if branch_id is not None:
            grouped[branch_id].append(record)

    issues: list[CompilationIssue] = []
    for record in records:
        activity_id = record.activity.activity_id
        activity_branch = branch_by_activity[activity_id]
        replacement_target = record.activity.activation.fallback_for_activity_id
        if (
            replacement_target is not None
            and branch_by_activity.get(replacement_target) is not None
        ):
            issues.append(
                compilation_issue(
                    "CROSS_BRANCH_DEPENDENCY",
                    "preflight",
                    record.path,
                    f"Fallback '{activity_id}' cannot replace a contingent activity.",
                )
            )
        for group_index, group in enumerate(record.activity.dependency_groups):
            predecessor_branches = {
                branch_by_activity[predecessor_id] for predecessor_id in group.activity_ids
            }
            main_has_candidate = None in predecessor_branches
            for predecessor_id in group.activity_ids:
                predecessor = record_by_id[predecessor_id]
                predecessor_branch = branch_by_activity[predecessor_id]
                main_to_contingency = activity_branch is None and predecessor_branch is not None
                allowed_main_alternative = (
                    main_to_contingency and group.mode is DependencyMode.any and main_has_candidate
                )
                invalid = (
                    (main_to_contingency and not allowed_main_alternative)
                    or (
                        activity_branch is not None
                        and predecessor_branch not in {None, activity_branch}
                    )
                    or (replacement_target is not None and predecessor_id == replacement_target)
                )
                if invalid:
                    issues.append(
                        compilation_issue(
                            "CROSS_BRANCH_DEPENDENCY",
                            "preflight",
                            f"{record.path}.dependencyGroups[{group_index}]",
                            f"Activity '{activity_id}' has unsupported dependency "
                            f"'{predecessor.activity.activity_id}' across contingency branches.",
                        )
                    )
    issues.sort(key=lambda item: (item.path, item.code, item.message))
    return branch_by_activity, dict(grouped), issues


def _canonical_activities(
    values: dict[str, ScheduledValue],
    axis: TimeAxis,
    scenario: Scenario,
) -> list[CanonicalActivity]:
    ordered = sorted(
        values.values(),
        key=lambda item: (item.start, item.end, item.record.activity.activity_id),
    )
    result: list[CanonicalActivity] = []
    for sequence_index, value in enumerate(ordered):
        activity = value.record.activity
        result.append(
            CanonicalActivity(
                source_activity_id=activity.activity_id,
                sequence_index=sequence_index,
                actor_id=activity.actor_id,
                intent=activity.intent,
                location_ids=activity.location_ids,
                scheduled_start=axis.to_datetime(value.start),
                scheduled_end=axis.to_datetime(value.end),
                duration_microseconds=value.end - value.start,
                mandatory=activity.mandatory,
                priority=activity.priority,
                can_overlap_for_actor=activity.can_overlap_for_actor,
                participant_ids=activity.participant_ids,
                required_resources=activity.required_resources,
                selected_dependency_ids=list(value.selected_dependency_ids),
                preconditions=activity.preconditions,
                effects=activity.effects,
                activation=activity.activation,
                commitment_id=activity.commitment_id,
                truncated_at_simulation_end=value.end > axis.simulation_end,
            )
        )
    return result


def _rescheduled_activities(
    contingency_values: dict[str, ScheduledValue],
    main_values: dict[str, ScheduledValue],
    candidate_ids: set[str],
    axis: TimeAxis,
    scenario: Scenario,
) -> list[CanonicalActivity]:
    changed = {
        activity_id: contingency_values[activity_id]
        for activity_id in candidate_ids
        if activity_id in contingency_values
        and (
            contingency_values[activity_id].start != main_values[activity_id].start
            or contingency_values[activity_id].end != main_values[activity_id].end
            or contingency_values[activity_id].selected_dependency_ids
            != main_values[activity_id].selected_dependency_ids
        )
    }
    return _canonical_activities(changed, axis, scenario)


def _build_plan(
    scenario: Scenario,
    axis: TimeAxis,
    records: list[SourceRecord],
    main_values: dict[str, ScheduledValue],
    omitted_ids: tuple[str, ...],
    objective_values: ObjectiveValues,
    contingency_plans: list[tuple[SourceRecord, ContingencyPlan]],
) -> CanonicalPlan:
    values_by_date: dict[Any, dict[str, ScheduledValue]] = defaultdict(dict)
    record_by_id = {record.activity.activity_id: record for record in records}
    for activity_id, value in main_values.items():
        values_by_date[value.record.day.date][activity_id] = value
    omitted_by_date: dict[Any, list[OmittedActivity]] = defaultdict(list)
    for activity_id in omitted_ids:
        omitted_by_date[record_by_id[activity_id].day.date].append(
            OmittedActivity(
                source_activity_id=activity_id,
                reason="optional_not_selected",
            )
        )
    contingencies_by_date: dict[Any, list[ContingencyPlan]] = defaultdict(list)
    for representative, contingency in contingency_plans:
        contingencies_by_date[representative.day.date].append(contingency)

    days = [
        CanonicalDay(
            date=day.date,
            activities=_canonical_activities(values_by_date[day.date], axis, scenario),
            contingencies=sorted(
                contingencies_by_date[day.date],
                key=lambda item: item.contingency_id,
            ),
            omitted_activities=sorted(
                omitted_by_date[day.date],
                key=lambda item: item.source_activity_id,
            ),
        )
        for day in sorted(scenario.days, key=lambda item: item.date)
    ]
    return CanonicalPlan(
        source_scenario_id=scenario.scenario_id,
        source_scenario_sha256=canonical_sha256(scenario),
        time_zone=scenario.time_zone,
        simulation_window=scenario.simulation_window,
        objective_values=objective_values,
        days=days,
    )


def _zero_objectives() -> ObjectiveValues:
    return ObjectiveValues(
        optional_priority_score=0,
        optional_activity_count=0,
        duration_deviation_microseconds=0,
        temporal_deviation_microseconds=0,
        scheduled_start_sum_microseconds=0,
    )


def _invalid_input_result(validation_report: Any) -> CompilationResult:
    issue = compilation_issue(
        "INPUT_SCENARIO_INVALID",
        "input",
        "$",
        "The input scenario did not pass scenario validation 1.0.0.",
        details={
            "validationIssueCodes": [item.code for item in validation_report.issues],
            "validationErrorCount": validation_report.summary.error_count,
            "validationWarningCount": validation_report.summary.warning_count,
        },
    )
    report = CompilationReport(
        success=False,
        source_scenario_version=validation_report.schema_version,
        source_scenario_id=validation_report.scenario_id,
        issues=[issue],
        summary=CompilationSummary(
            scheduled_activity_count=0,
            omitted_activity_count=0,
            contingency_count=0,
            contingency_activity_count=0,
            rescheduled_activity_count=0,
            error_count=1,
            warning_count=0,
        ),
    )
    return CompilationResult(plan=None, report=report)


def _solver_failure_result(
    scenario: Scenario,
    failure: str,
    status: str,
    stage: str,
    infeasible_code: str,
    model_error: str | None,
    details: dict[str, Any] | None = None,
    objective_values: ObjectiveValues | None = None,
    prior_issues: list[CompilationIssue] | None = None,
) -> CompilationResult:
    if failure == "infeasible":
        code = infeasible_code
        message = "The scheduling constraints are infeasible."
    elif failure == "model_invalid":
        code = "SOLVER_MODEL_INVALID"
        message = model_error or "CP-SAT rejected the scheduling model."
    else:
        code = "SOLVER_NOT_OPTIMAL"
        message = "CP-SAT did not prove an optimal canonical solution."
    issue = compilation_issue(
        code,
        stage,  # type: ignore[arg-type]
        "$",
        message,
        details={"solverStatus": status, **(details or {})},
    )
    return _failure_result(
        scenario,
        [*(prior_issues or []), issue],
        solver_status=status,
        objective_values=objective_values,
    )


def _failure_result(
    scenario: Scenario,
    issues: list[CompilationIssue],
    solver_status: str | None,
    objective_values: ObjectiveValues | None,
) -> CompilationResult:
    ordered = sorted(issues, key=lambda item: (item.path, item.code, item.message))
    report = CompilationReport(
        success=False,
        source_scenario_version=scenario.schema_version,
        source_scenario_id=scenario.scenario_id,
        solver_status=solver_status,
        objective_values=objective_values,
        issues=ordered,
        summary=CompilationSummary(
            scheduled_activity_count=0,
            omitted_activity_count=0,
            contingency_count=0,
            contingency_activity_count=0,
            rescheduled_activity_count=0,
            error_count=sum(item.severity == "error" for item in ordered),
            warning_count=sum(item.severity == "warning" for item in ordered),
        ),
    )
    return CompilationResult(plan=None, report=report)


def _build_report(
    scenario: Scenario,
    plan: CanonicalPlan,
    plan_digest: str,
    issues: list[CompilationIssue],
    solver_status: str,
    objective_values: ObjectiveValues,
) -> CompilationReport:
    ordered = sorted(issues, key=lambda item: (item.path, item.code, item.message))
    scheduled = sum(len(day.activities) for day in plan.days)
    omitted = sum(len(day.omitted_activities) for day in plan.days)
    contingencies = sum(len(day.contingencies) for day in plan.days)
    contingency_activities = sum(
        len(contingency.activities) for day in plan.days for contingency in day.contingencies
    )
    rescheduled_activities = sum(
        len(contingency.rescheduled_activities)
        for day in plan.days
        for contingency in day.contingencies
    )
    return CompilationReport(
        success=True,
        source_scenario_version=scenario.schema_version,
        source_scenario_id=scenario.scenario_id,
        canonical_plan_sha256=plan_digest,
        solver_status=solver_status,
        objective_values=objective_values,
        issues=ordered,
        summary=CompilationSummary(
            scheduled_activity_count=scheduled,
            omitted_activity_count=omitted,
            contingency_count=contingencies,
            contingency_activity_count=contingency_activities,
            rescheduled_activity_count=rescheduled_activities,
            error_count=0,
            warning_count=sum(item.severity == "warning" for item in ordered),
        ),
    )
