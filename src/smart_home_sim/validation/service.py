from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.domain.models import Activity, DayPlan, Scenario
from smart_home_sim.domain.report import ValidationIssue, ValidationReport
from smart_home_sim.validation.issues import duplicate_values, issue, minutes_since_midnight


def _json_path(location: tuple[Any, ...]) -> str:
    result = "$"
    for part in location:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


def _structure_report(error: ValidationError) -> ValidationReport:
    issues = [
        issue(
            "STRUCTURE_INVALID",
            "structure",
            _json_path(item["loc"]),
            item["msg"],
        )
        for item in error.errors(include_url=False, include_context=False, include_input=False)
    ]
    return ValidationReport.from_issues(issues)


def validate_file(path: Path) -> ValidationReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return ValidationReport.from_issues(
            [
                issue(
                    "JSON_SYNTAX",
                    "structure",
                    "$",
                    f"Invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}",
                )
            ]
        )
    except OSError as error:
        return ValidationReport.from_issues(
            [issue("JSON_SYNTAX", "structure", "$", f"Cannot read scenario: {error}")]
        )
    return validate_payload(payload)


def validate_payload(payload: Any) -> ValidationReport:
    try:
        scenario = Scenario.model_validate(payload)
    except ValidationError as error:
        return _structure_report(error)
    return validate_scenario(scenario)


def validate_scenario(scenario: Scenario) -> ValidationReport:
    issues: list[ValidationIssue] = []
    issues.extend(_validate_unique_ids(scenario))
    issues.extend(_validate_entity_references(scenario))
    issues.extend(_validate_days(scenario))
    return ValidationReport.from_issues(
        sorted(issues, key=lambda item: (item.path, item.code, item.message)),
        schema_version=scenario.schema_version,
        scenario_id=scenario.scenario_id,
    )


def _validate_unique_ids(scenario: Scenario) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    groups = [
        (
            [resident.resident_id for resident in scenario.residents],
            "DUPLICATE_RESIDENT_ID",
            "$.residents",
            "resident",
        ),
        (
            [location.location_id for location in scenario.locations],
            "DUPLICATE_LOCATION_ID",
            "$.locations",
            "location",
        ),
        (
            [resource.resource_id for resource in scenario.resources],
            "DUPLICATE_RESOURCE_ID",
            "$.resources",
            "resource",
        ),
        (
            [day.date.isoformat() for day in scenario.days],
            "DUPLICATE_DAY",
            "$.days",
            "day",
        ),
        (
            [activity.activity_id for day in scenario.days for activity in day.activities],
            "DUPLICATE_ACTIVITY_ID",
            "$.days",
            "activity",
        ),
    ]
    for values, code, path, label in groups:
        for duplicate in sorted(duplicate_values(values)):
            issues.append(
                issue(code, "referential", path, f"Duplicate {label} identifier '{duplicate}'.")
            )
    return issues


def _validate_entity_references(scenario: Scenario) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    resident_ids = {resident.resident_id for resident in scenario.residents}
    location_ids = {location.location_id for location in scenario.locations}
    resources = {resource.resource_id: resource for resource in scenario.resources}

    for index, resident in enumerate(scenario.residents):
        if resident.initial_location_id not in location_ids:
            issues.append(
                issue(
                    "UNKNOWN_INITIAL_LOCATION",
                    "referential",
                    f"$.residents[{index}].initialLocationId",
                    f"Resident '{resident.resident_id}' references unknown location "
                    f"'{resident.initial_location_id}'.",
                )
            )

    for index, resource in enumerate(scenario.resources):
        if resource.location_id not in location_ids:
            issues.append(
                issue(
                    "UNKNOWN_RESOURCE_LOCATION",
                    "referential",
                    f"$.resources[{index}].locationId",
                    f"Resource '{resource.resource_id}' references unknown location "
                    f"'{resource.location_id}'.",
                )
            )

    for day_index, day in enumerate(scenario.days):
        for activity_index, activity in enumerate(day.activities):
            path = f"$.days[{day_index}].activities[{activity_index}]"
            if activity.actor_id not in resident_ids:
                issues.append(
                    issue(
                        "UNKNOWN_ACTOR",
                        "referential",
                        f"{path}.actorId",
                        f"Activity '{activity.activity_id}' references unknown resident "
                        f"'{activity.actor_id}'.",
                    )
                )
            if activity.destination_id not in location_ids:
                issues.append(
                    issue(
                        "UNKNOWN_DESTINATION",
                        "referential",
                        f"{path}.destinationId",
                        f"Activity '{activity.activity_id}' references unknown location "
                        f"'{activity.destination_id}'.",
                    )
                )
            for participant in activity.participants:
                if participant not in resident_ids:
                    issues.append(
                        issue(
                            "UNKNOWN_PARTICIPANT",
                            "referential",
                            f"{path}.participants",
                            f"Activity '{activity.activity_id}' references unknown participant "
                            f"'{participant}'.",
                        )
                    )
                if participant == activity.actor_id:
                    issues.append(
                        issue(
                            "ACTOR_REPEATED_AS_PARTICIPANT",
                            "semantic",
                            f"{path}.participants",
                            f"Activity '{activity.activity_id}' repeats its actor as participant.",
                        )
                    )
            for resource_id in activity.required_resources:
                resource = resources.get(resource_id)
                if resource is None:
                    issues.append(
                        issue(
                            "UNKNOWN_REQUIRED_RESOURCE",
                            "referential",
                            f"{path}.requiredResources",
                            f"Activity '{activity.activity_id}' references unknown resource "
                            f"'{resource_id}'.",
                        )
                    )
                elif resource.location_id != activity.destination_id:
                    issues.append(
                        issue(
                            "RESOURCE_LOCATION_MISMATCH",
                            "semantic",
                            f"{path}.requiredResources",
                            f"Resource '{resource_id}' is at '{resource.location_id}', while "
                            f"activity '{activity.activity_id}' is at '{activity.destination_id}'.",
                            severity="warning",
                        )
                    )
    return issues


def _validate_days(scenario: Scenario) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for day_index, day in enumerate(scenario.days):
        if not scenario.start_date <= day.date <= scenario.end_date:
            issues.append(
                issue(
                    "DAY_OUTSIDE_SCENARIO",
                    "temporal",
                    f"$.days[{day_index}].date",
                    f"Day '{day.date.isoformat()}' is outside the scenario date range.",
                )
            )
        issues.extend(_validate_day_dependencies(day, day_index))
        issues.extend(_validate_fixed_overlaps(day, day_index))
    return issues


def _validate_day_dependencies(day: DayPlan, day_index: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    activities = {activity.activity_id: activity for activity in day.activities}
    dependencies: dict[str, list[str]] = {}

    for activity_index, activity in enumerate(day.activities):
        path = f"$.days[{day_index}].activities[{activity_index}].after"
        dependencies[activity.activity_id] = []
        for predecessor_id in activity.after:
            if predecessor_id == activity.activity_id:
                issues.append(
                    issue(
                        "SELF_DEPENDENCY",
                        "temporal",
                        path,
                        f"Activity '{activity.activity_id}' depends on itself.",
                    )
                )
                continue
            predecessor = activities.get(predecessor_id)
            if predecessor is None:
                issues.append(
                    issue(
                        "UNKNOWN_DEPENDENCY",
                        "referential",
                        path,
                        f"Activity '{activity.activity_id}' references unknown same-day activity "
                        f"'{predecessor_id}'.",
                    )
                )
                continue
            dependencies[activity.activity_id].append(predecessor_id)
            predecessor_earliest_end = (
                minutes_since_midnight(predecessor.timing.start.earliest)
                + predecessor.timing.duration.minimum_minutes
            )
            successor_latest_start = minutes_since_midnight(activity.timing.start.latest)
            if predecessor_earliest_end > successor_latest_start:
                issues.append(
                    issue(
                        "IMPOSSIBLE_PRECEDENCE",
                        "temporal",
                        path,
                        f"Activity '{predecessor_id}' cannot finish before the latest start of "
                        f"'{activity.activity_id}'.",
                    )
                )

    state: dict[str, int] = {}

    def visit(activity_id: str, stack: list[str]) -> None:
        marker = state.get(activity_id, 0)
        if marker == 2:
            return
        if marker == 1:
            cycle_start = stack.index(activity_id)
            cycle = stack[cycle_start:] + [activity_id]
            issues.append(
                issue(
                    "DEPENDENCY_CYCLE",
                    "temporal",
                    f"$.days[{day_index}].activities",
                    f"Dependency cycle detected: {' -> '.join(cycle)}.",
                )
            )
            return
        state[activity_id] = 1
        for predecessor_id in dependencies.get(activity_id, []):
            visit(predecessor_id, [*stack, activity_id])
        state[activity_id] = 2

    for activity_id in dependencies:
        visit(activity_id, [])

    return issues


def _is_fixed(activity: Activity) -> bool:
    start = activity.timing.start
    return start.earliest == start.preferred == start.latest


def _validate_fixed_overlaps(day: DayPlan, day_index: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    fixed = [activity for activity in day.activities if activity.mandatory and _is_fixed(activity)]
    fixed.sort(key=lambda activity: minutes_since_midnight(activity.timing.start.preferred))
    for previous, current in zip(fixed, fixed[1:], strict=False):
        previous_end = (
            minutes_since_midnight(previous.timing.start.preferred)
            + previous.timing.duration.minimum_minutes
        )
        current_start = minutes_since_midnight(current.timing.start.preferred)
        if previous_end > current_start:
            issues.append(
                issue(
                    "FIXED_ACTIVITY_OVERLAP",
                    "temporal",
                    f"$.days[{day_index}].activities",
                    f"Mandatory fixed activities '{previous.activity_id}' and "
                    f"'{current.activity_id}' overlap.",
                )
            )
    return issues
