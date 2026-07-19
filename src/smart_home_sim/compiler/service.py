from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.compiler.issues import compilation_issue
from smart_home_sim.compiler.solver import (
    ScheduledValue,
    ScheduleSolver,
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


def compile_payload(payload: Any) -> CompilationResult:
    validation_report = validate_payload(payload)
    if not validation_report.valid:
        return _invalid_input_result(validation_report)
    scenario = Scenario.model_validate_json(json.dumps(payload, separators=(",", ":")))
    return compile_scenario(scenario)


def compile_scenario(scenario: Scenario) -> CompilationResult:
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
        main_outcome = ScheduleSolver(scenario, axis, main_records).solve()
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
