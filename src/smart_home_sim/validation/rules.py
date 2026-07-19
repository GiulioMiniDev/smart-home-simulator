from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations
from zoneinfo import ZoneInfo

from smart_home_sim.domain.models import (
    ActivationMode,
    Activity,
    DayPlan,
    DependencyMode,
    LocationKind,
    RepairStep,
    RuntimeEventOperation,
    Scenario,
)
from smart_home_sim.domain.report import ValidationIssue
from smart_home_sim.validation.issues import duplicate_values, issue


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    day_index: int
    activity_index: int
    day: DayPlan
    activity: Activity

    @property
    def path(self) -> str:
        return f"$.days[{self.day_index}].activities[{self.activity_index}]"


def _activity_records(scenario: Scenario) -> list[ActivityRecord]:
    return [
        ActivityRecord(day_index, activity_index, day, activity)
        for day_index, day in enumerate(scenario.days)
        for activity_index, activity in enumerate(day.activities)
    ]


def validate_rules(scenario: Scenario) -> list[ValidationIssue]:
    records = _activity_records(scenario)
    issues: list[ValidationIssue] = []
    issues.extend(_validate_unique_ids(scenario, records))
    issues.extend(_validate_references(scenario, records))
    issues.extend(_validate_lists_and_policy(scenario, records))
    issues.extend(_validate_time_zone_offsets(scenario, records))
    issues.extend(_validate_temporal_bounds(scenario, records))
    issues.extend(_validate_dependencies(records))
    issues.extend(_validate_fallbacks(records))
    issues.extend(_validate_fixed_conflicts(scenario, records))
    issues.extend(_validate_resource_semantics(scenario, records))
    return issues


def _validate_unique_ids(
    scenario: Scenario,
    records: list[ActivityRecord],
) -> list[ValidationIssue]:
    groups = [
        (
            [resident.resident_id for resident in scenario.residents],
            "DUPLICATE_RESIDENT_ID",
            "$.residents",
            "resident",
        ),
        (
            [person.external_person_id for person in scenario.external_people],
            "DUPLICATE_EXTERNAL_PERSON_ID",
            "$.externalPeople",
            "external person",
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
            [state.resident_id for state in scenario.initial_state.residents],
            "DUPLICATE_INITIAL_STATE",
            "$.initialState.residents",
            "resident initial state",
        ),
        (
            [commitment.commitment_id for commitment in scenario.commitments],
            "DUPLICATE_COMMITMENT_ID",
            "$.commitments",
            "commitment",
        ),
        (
            [day.date.isoformat() for day in scenario.days],
            "DUPLICATE_DAY",
            "$.days",
            "day",
        ),
        (
            [record.activity.activity_id for record in records],
            "DUPLICATE_ACTIVITY_ID",
            "$.days",
            "activity",
        ),
        (
            [event.event_id for event in scenario.runtime_event_candidates],
            "DUPLICATE_RUNTIME_EVENT_ID",
            "$.runtimeEventCandidates",
            "runtime event",
        ),
    ]
    issues: list[ValidationIssue] = []
    for values, code, path, label in groups:
        for duplicate in sorted(duplicate_values(values)):
            issues.append(
                issue(code, "referential", path, f"Duplicate {label} identifier '{duplicate}'.")
            )
    return issues


def _validate_references(
    scenario: Scenario,
    records: list[ActivityRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    resident_ids = {resident.resident_id for resident in scenario.residents}
    external_person_ids = {person.external_person_id for person in scenario.external_people}
    person_ids = resident_ids | external_person_ids
    locations = {location.location_id: location for location in scenario.locations}
    resources = {resource.resource_id: resource for resource in scenario.resources}
    activities = {record.activity.activity_id: record for record in records}
    commitments = {commitment.commitment_id: commitment for commitment in scenario.commitments}

    for collision in sorted(resident_ids & external_person_ids):
        issues.append(
            issue(
                "PERSON_ID_COLLISION",
                "referential",
                "$.externalPeople",
                f"Identifier '{collision}' is used by both a resident and an external person.",
            )
        )

    for index, person in enumerate(scenario.external_people):
        for resident_id in person.relationship_to_residents:
            if resident_id not in resident_ids:
                issues.append(
                    issue(
                        "UNKNOWN_RELATIONSHIP_RESIDENT",
                        "referential",
                        f"$.externalPeople[{index}].relationshipToResidents",
                        f"External person '{person.external_person_id}' references unknown "
                        f"resident '{resident_id}'.",
                    )
                )

    initial_state_ids = {state.resident_id for state in scenario.initial_state.residents}
    for resident_id in sorted(resident_ids - initial_state_ids):
        issues.append(
            issue(
                "MISSING_RESIDENT_INITIAL_STATE",
                "referential",
                "$.initialState.residents",
                f"Resident '{resident_id}' has no initial state.",
            )
        )
    for index, state in enumerate(scenario.initial_state.residents):
        path = f"$.initialState.residents[{index}]"
        if state.resident_id not in resident_ids:
            issues.append(
                issue(
                    "UNKNOWN_INITIAL_STATE_RESIDENT",
                    "referential",
                    f"{path}.residentId",
                    f"Initial state references unknown resident '{state.resident_id}'.",
                )
            )
        if state.location_id not in locations:
            issues.append(
                issue(
                    "UNKNOWN_INITIAL_LOCATION",
                    "referential",
                    f"{path}.locationId",
                    f"Initial state references unknown location '{state.location_id}'.",
                )
            )

    for index, location in enumerate(scenario.locations):
        for member in location.member_location_ids:
            if member not in locations:
                issues.append(
                    issue(
                        "UNKNOWN_COMPOSITE_MEMBER",
                        "referential",
                        f"$.locations[{index}].memberLocationIds",
                        f"Composite location '{location.location_id}' references unknown member "
                        f"'{member}'.",
                    )
                )
            if member == location.location_id:
                issues.append(
                    issue(
                        "COMPOSITE_LOCATION_SELF_REFERENCE",
                        "semantic",
                        f"$.locations[{index}].memberLocationIds",
                        f"Composite location '{location.location_id}' contains itself.",
                    )
                )

    issues.extend(_validate_composite_cycles(scenario))

    for index, resource in enumerate(scenario.resources):
        if resource.location_id not in locations:
            issues.append(
                issue(
                    "UNKNOWN_RESOURCE_LOCATION",
                    "referential",
                    f"$.resources[{index}].locationId",
                    f"Resource '{resource.resource_id}' references unknown location "
                    f"'{resource.location_id}'.",
                )
            )
    for resource_id in scenario.initial_state.resource_facts:
        if resource_id not in resources:
            issues.append(
                issue(
                    "UNKNOWN_RESOURCE_STATE",
                    "referential",
                    "$.initialState.resourceFacts",
                    f"Initial state references unknown resource '{resource_id}'.",
                )
            )

    for index, commitment in enumerate(scenario.commitments):
        path = f"$.commitments[{index}]"
        for participant in commitment.participant_ids:
            if participant not in person_ids:
                issues.append(
                    issue(
                        "UNKNOWN_COMMITMENT_PARTICIPANT",
                        "referential",
                        f"{path}.participantIds",
                        f"Commitment '{commitment.commitment_id}' references unknown person "
                        f"'{participant}'.",
                    )
                )
        if commitment.location_id not in locations:
            issues.append(
                issue(
                    "UNKNOWN_COMMITMENT_LOCATION",
                    "referential",
                    f"{path}.locationId",
                    f"Commitment '{commitment.commitment_id}' references unknown location "
                    f"'{commitment.location_id}'.",
                )
            )

    for record in records:
        activity = record.activity
        if activity.actor_id not in resident_ids:
            issues.append(
                issue(
                    "UNKNOWN_ACTOR",
                    "referential",
                    f"{record.path}.actorId",
                    f"Activity '{activity.activity_id}' references unknown resident "
                    f"'{activity.actor_id}'.",
                )
            )
        for participant in activity.participant_ids:
            if participant not in person_ids:
                issues.append(
                    issue(
                        "UNKNOWN_PARTICIPANT",
                        "referential",
                        f"{record.path}.participantIds",
                        f"Activity '{activity.activity_id}' references unknown participant "
                        f"'{participant}'.",
                    )
                )
        for location_id in activity.location_ids:
            if location_id not in locations:
                issues.append(
                    issue(
                        "UNKNOWN_ACTIVITY_LOCATION",
                        "referential",
                        f"{record.path}.locationIds",
                        f"Activity '{activity.activity_id}' references unknown location "
                        f"'{location_id}'.",
                    )
                )
        for requirement in activity.required_resources:
            if requirement.resource_id not in resources:
                issues.append(
                    issue(
                        "UNKNOWN_REQUIRED_RESOURCE",
                        "referential",
                        f"{record.path}.requiredResources",
                        f"Activity '{activity.activity_id}' references unknown resource "
                        f"'{requirement.resource_id}'.",
                    )
                )
        for group in activity.dependency_groups:
            for predecessor_id in group.activity_ids:
                if predecessor_id not in activities:
                    issues.append(
                        issue(
                            "UNKNOWN_DEPENDENCY",
                            "referential",
                            f"{record.path}.dependencyGroups",
                            f"Activity '{activity.activity_id}' references unknown activity "
                            f"'{predecessor_id}'.",
                        )
                    )
                if predecessor_id == activity.activity_id:
                    issues.append(
                        issue(
                            "SELF_DEPENDENCY",
                            "temporal",
                            f"{record.path}.dependencyGroups",
                            f"Activity '{activity.activity_id}' depends on itself.",
                        )
                    )
        if activity.commitment_id is not None and activity.commitment_id not in commitments:
            issues.append(
                issue(
                    "UNKNOWN_COMMITMENT",
                    "referential",
                    f"{record.path}.commitmentId",
                    f"Activity '{activity.activity_id}' references unknown commitment "
                    f"'{activity.commitment_id}'.",
                )
            )
        fallback_target = activity.activation.fallback_for_activity_id
        if fallback_target is not None and fallback_target not in activities:
            issues.append(
                issue(
                    "UNKNOWN_FALLBACK_TARGET",
                    "referential",
                    f"{record.path}.activation.fallbackForActivityId",
                    f"Fallback '{activity.activity_id}' references unknown activity "
                    f"'{fallback_target}'.",
                )
            )

    for index, event in enumerate(scenario.runtime_event_candidates):
        path = f"$.runtimeEventCandidates[{index}]"
        zone = ZoneInfo(scenario.time_zone)
        eligible_first_day = event.eligible_window.earliest.astimezone(zone).date()
        eligible_last_day = event.eligible_window.latest.astimezone(zone).date()
        if event.trigger_activity_id is not None and event.trigger_activity_id not in activities:
            issues.append(
                issue(
                    "UNKNOWN_EVENT_TRIGGER_ACTIVITY",
                    "referential",
                    f"{path}.triggerActivityId",
                    f"Runtime event '{event.event_id}' references unknown trigger activity "
                    f"'{event.trigger_activity_id}'.",
                )
            )
        elif event.trigger_activity_id is not None:
            trigger_day = activities[event.trigger_activity_id].day.date
            if not eligible_first_day <= trigger_day <= eligible_last_day:
                issues.append(
                    issue(
                        "EVENT_TRIGGER_DAY_MISMATCH",
                        "temporal",
                        f"{path}.triggerActivityId",
                        f"Runtime event '{event.event_id}' is not eligible on the day of "
                        f"trigger activity '{event.trigger_activity_id}'.",
                    )
                )
        for effect_index, effect in enumerate(event.effects):
            if (
                effect.operation
                in {
                    RuntimeEventOperation.delay_activity_start,
                    RuntimeEventOperation.extend_activity_duration,
                }
                and effect.target_id not in activities
            ):
                issues.append(
                    issue(
                        "UNKNOWN_EVENT_TARGET_ACTIVITY",
                        "referential",
                        f"{path}.effects[{effect_index}].targetId",
                        f"Runtime event '{event.event_id}' references unknown activity "
                        f"'{effect.target_id}'.",
                    )
                )
            elif effect.operation in {
                RuntimeEventOperation.delay_activity_start,
                RuntimeEventOperation.extend_activity_duration,
            }:
                target_day = activities[effect.target_id].day.date
                if not eligible_first_day <= target_day <= eligible_last_day:
                    issues.append(
                        issue(
                            "EVENT_TARGET_DAY_MISMATCH",
                            "temporal",
                            f"{path}.effects[{effect_index}].targetId",
                            f"Runtime event '{event.event_id}' is not eligible on the day of "
                            f"target activity '{effect.target_id}'.",
                        )
                    )
            if (
                effect.operation is RuntimeEventOperation.interrupt_actor
                and effect.target_id not in resident_ids
            ):
                issues.append(
                    issue(
                        "UNKNOWN_EVENT_TARGET_RESIDENT",
                        "referential",
                        f"{path}.effects[{effect_index}].targetId",
                        f"Runtime event '{event.event_id}' references unknown resident "
                        f"'{effect.target_id}'.",
                    )
                )
    return issues


def _validate_composite_cycles(scenario: Scenario) -> list[ValidationIssue]:
    graph = {
        location.location_id: list(location.member_location_ids)
        for location in scenario.locations
        if location.kind is LocationKind.composite
    }
    issues: list[ValidationIssue] = []
    state: dict[str, int] = {}
    reported: set[tuple[str, ...]] = set()

    def visit(location_id: str, stack: list[str]) -> None:
        marker = state.get(location_id, 0)
        if marker == 2:
            return
        if marker == 1 and location_id in stack:
            start = stack.index(location_id)
            cycle = tuple(stack[start:] + [location_id])
            if cycle not in reported:
                reported.add(cycle)
                issues.append(
                    issue(
                        "COMPOSITE_LOCATION_CYCLE",
                        "semantic",
                        "$.locations",
                        f"Composite location cycle detected: {' -> '.join(cycle)}.",
                    )
                )
            return
        state[location_id] = 1
        for member in graph.get(location_id, []):
            if member in graph:
                visit(member, [*stack, location_id])
        state[location_id] = 2

    for location_id in graph:
        visit(location_id, [])
    return issues


def _validate_lists_and_policy(
    scenario: Scenario,
    records: list[ActivityRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    checks: list[tuple[list[str], str, str, str]] = []
    for index, commitment in enumerate(scenario.commitments):
        checks.append(
            (
                commitment.participant_ids,
                "DUPLICATE_COMMITMENT_PARTICIPANT",
                f"$.commitments[{index}].participantIds",
                f"Commitment '{commitment.commitment_id}'",
            )
        )
    for record in records:
        activity = record.activity
        checks.extend(
            [
                (
                    activity.location_ids,
                    "DUPLICATE_ACTIVITY_LOCATION",
                    f"{record.path}.locationIds",
                    f"Activity '{activity.activity_id}'",
                ),
                (
                    activity.participant_ids,
                    "DUPLICATE_PARTICIPANT",
                    f"{record.path}.participantIds",
                    f"Activity '{activity.activity_id}'",
                ),
                (
                    [item.resource_id for item in activity.required_resources],
                    "DUPLICATE_RESOURCE_REQUIREMENT",
                    f"{record.path}.requiredResources",
                    f"Activity '{activity.activity_id}'",
                ),
                (
                    activity.labels,
                    "DUPLICATE_ACTIVITY_LABEL",
                    f"{record.path}.labels",
                    f"Activity '{activity.activity_id}'",
                ),
            ]
        )
        for group_index, group in enumerate(activity.dependency_groups):
            checks.append(
                (
                    group.activity_ids,
                    "DUPLICATE_DEPENDENCY",
                    f"{record.path}.dependencyGroups[{group_index}].activityIds",
                    f"Activity '{activity.activity_id}'",
                )
            )
        if activity.actor_id in activity.participant_ids:
            issues.append(
                issue(
                    "ACTOR_REPEATED_AS_PARTICIPANT",
                    "semantic",
                    f"{record.path}.participantIds",
                    f"Activity '{activity.activity_id}' repeats its actor as participant.",
                )
            )
    for values, code, path, owner in checks:
        for duplicate in sorted(duplicate_values(values)):
            issues.append(
                issue(code, "semantic", path, f"{owner} repeats identifier '{duplicate}'.")
            )

    repair_order = scenario.materialization_policy.repair_order
    for duplicate in sorted(duplicate_values([str(item) for item in repair_order])):
        issues.append(
            issue(
                "DUPLICATE_REPAIR_STEP",
                "semantic",
                "$.materializationPolicy.repairOrder",
                f"Repair step '{duplicate}' is repeated.",
            )
        )
    if not repair_order or repair_order[-1] is not RepairStep.reject_day_plan:
        issues.append(
            issue(
                "INVALID_REPAIR_ORDER",
                "semantic",
                "$.materializationPolicy.repairOrder",
                "The final repair step must be 'reject_day_plan'.",
            )
        )
    if not scenario.materialization_policy.allow_local_repair and any(
        step is not RepairStep.reject_day_plan for step in repair_order
    ):
        issues.append(
            issue(
                "REPAIR_DISABLED_WITH_LOCAL_STEPS",
                "semantic",
                "$.materializationPolicy",
                "Local repair is disabled but repairOrder contains local repair steps.",
            )
        )
    for duplicate in sorted(duplicate_values(scenario.requested_outputs.formats)):
        issues.append(
            issue(
                "DUPLICATE_OUTPUT_FORMAT",
                "semantic",
                "$.requestedOutputs.formats",
                f"Output format '{duplicate}' is repeated.",
            )
        )
    for duplicate in sorted(duplicate_values(scenario.declared_constraints)):
        issues.append(
            issue(
                "DUPLICATE_DECLARED_CONSTRAINT",
                "semantic",
                "$.declaredConstraints",
                f"Declared constraint '{duplicate}' is repeated.",
                severity="warning",
            )
        )
    return issues


def _validate_time_zone_offsets(
    scenario: Scenario,
    records: list[ActivityRecord],
) -> list[ValidationIssue]:
    zone = ZoneInfo(scenario.time_zone)
    values: list[tuple[str, datetime]] = [
        ("$.simulationWindow.start", scenario.simulation_window.start),
        ("$.simulationWindow.end", scenario.simulation_window.end),
        ("$.initialState.at", scenario.initial_state.at),
    ]
    for index, commitment in enumerate(scenario.commitments):
        values.extend(
            [
                (f"$.commitments[{index}].start", commitment.start),
                (f"$.commitments[{index}].end", commitment.end),
            ]
        )
    for record in records:
        for field_name in ("start_window", "end_window"):
            window = getattr(record.activity, field_name)
            if window is not None:
                alias = "startWindow" if field_name == "start_window" else "endWindow"
                values.extend(
                    [
                        (f"{record.path}.{alias}.earliest", window.earliest),
                        (f"{record.path}.{alias}.preferred", window.preferred),
                        (f"{record.path}.{alias}.latest", window.latest),
                    ]
                )
    for index, event in enumerate(scenario.runtime_event_candidates):
        window = event.eligible_window
        values.extend(
            [
                (f"$.runtimeEventCandidates[{index}].eligibleWindow.earliest", window.earliest),
                (f"$.runtimeEventCandidates[{index}].eligibleWindow.preferred", window.preferred),
                (f"$.runtimeEventCandidates[{index}].eligibleWindow.latest", window.latest),
            ]
        )

    issues: list[ValidationIssue] = []
    for path, value in values:
        expected_offset = value.astimezone(zone).utcoffset()
        if value.utcoffset() != expected_offset:
            issues.append(
                issue(
                    "TIMEZONE_OFFSET_MISMATCH",
                    "temporal",
                    path,
                    f"Timestamp offset does not match time zone '{scenario.time_zone}'.",
                )
            )
    return issues


def _validate_temporal_bounds(
    scenario: Scenario,
    records: list[ActivityRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    start = scenario.simulation_window.start
    end = scenario.simulation_window.end
    zone = ZoneInfo(scenario.time_zone)
    local_start_date = start.astimezone(zone).date()
    local_last_date = (end.astimezone(zone) - timedelta(microseconds=1)).date()

    if scenario.initial_state.at != start:
        issues.append(
            issue(
                "INITIAL_STATE_TIME_MISMATCH",
                "temporal",
                "$.initialState.at",
                "Initial state timestamp must equal simulationWindow.start.",
            )
        )

    day_dates = {day.date for day in scenario.days}
    for day_index, day in enumerate(scenario.days):
        if not local_start_date <= day.date <= local_last_date:
            issues.append(
                issue(
                    "DAY_OUTSIDE_SIMULATION",
                    "temporal",
                    f"$.days[{day_index}].date",
                    f"Day '{day.date}' is outside the simulation window.",
                )
            )
    if scenario.materialization_policy.require_every_date:
        current = local_start_date
        while current <= local_last_date:
            if current not in day_dates:
                issues.append(
                    issue(
                        "MISSING_REQUIRED_DAY",
                        "temporal",
                        "$.days",
                        f"Simulation date '{current}' has no day plan.",
                    )
                )
            current += timedelta(days=1)

    for record in records:
        activity = record.activity
        for alias, window in (
            ("startWindow", activity.start_window),
            ("endWindow", activity.end_window),
        ):
            if window is None:
                continue
            outside_before = window.earliest < start
            outside_after = window.latest > end
            allowed_truncation = (
                activity.allow_boundary_truncation
                and not outside_before
                and activity.start_window is not None
                and activity.start_window.earliest < end
            )
            if outside_before or (outside_after and not allowed_truncation):
                issues.append(
                    issue(
                        "ACTIVITY_WINDOW_OUTSIDE_SIMULATION",
                        "temporal",
                        f"{record.path}.{alias}",
                        f"Activity '{activity.activity_id}' has {alias} outside the simulation "
                        "window.",
                    )
                )
        derived_latest_end = (
            activity.start_window.latest + timedelta(minutes=activity.duration.maximum_minutes)
            if activity.start_window is not None
            and activity.end_window is None
            and activity.duration is not None
            else None
        )
        if (
            derived_latest_end is not None
            and derived_latest_end > end
            and not activity.allow_boundary_truncation
        ):
            issues.append(
                issue(
                    "ACTIVITY_WINDOW_OUTSIDE_SIMULATION",
                    "temporal",
                    f"{record.path}.duration",
                    f"Activity '{activity.activity_id}' can end outside the simulation window.",
                )
            )
        if (
            activity.start_window is not None
            and activity.start_window.preferred.astimezone(zone).date() != record.day.date
        ):
            issues.append(
                issue(
                    "ACTIVITY_ASSIGNED_TO_WRONG_DAY",
                    "temporal",
                    f"{record.path}.startWindow.preferred",
                    f"Activity '{activity.activity_id}' preferred start does not match day "
                    f"'{record.day.date}'.",
                )
            )

    for index, commitment in enumerate(scenario.commitments):
        if commitment.start < start or commitment.end > end:
            issues.append(
                issue(
                    "COMMITMENT_OUTSIDE_SIMULATION",
                    "temporal",
                    f"$.commitments[{index}]",
                    f"Commitment '{commitment.commitment_id}' is outside the simulation window.",
                )
            )
    for index, event in enumerate(scenario.runtime_event_candidates):
        window = event.eligible_window
        if window.earliest < start or window.latest > end:
            issues.append(
                issue(
                    "RUNTIME_EVENT_OUTSIDE_SIMULATION",
                    "temporal",
                    f"$.runtimeEventCandidates[{index}].eligibleWindow",
                    f"Runtime event '{event.event_id}' is outside the simulation window.",
                )
            )
    return issues


def _earliest_end(activity: Activity) -> datetime | None:
    if activity.end_window is not None:
        return activity.end_window.earliest
    if activity.start_window is not None and activity.duration is not None:
        return activity.start_window.earliest + timedelta(minutes=activity.duration.minimum_minutes)
    return None


def _latest_end(activity: Activity) -> datetime | None:
    if activity.end_window is not None:
        return activity.end_window.latest
    if activity.start_window is not None and activity.duration is not None:
        return activity.start_window.latest + timedelta(minutes=activity.duration.maximum_minutes)
    return None


def _dependency_is_feasible(
    predecessor: Activity,
    successor: Activity,
    minimum_lag: float,
    maximum_lag: float | None,
) -> bool | None:
    predecessor_earliest_end = _earliest_end(predecessor)
    if predecessor_earliest_end is None or successor.start_window is None:
        return None
    if predecessor_earliest_end + timedelta(minutes=minimum_lag) > successor.start_window.latest:
        return False
    if maximum_lag is not None:
        predecessor_latest_end = _latest_end(predecessor)
        if (
            predecessor_latest_end is not None
            and predecessor_latest_end + timedelta(minutes=maximum_lag)
            < successor.start_window.earliest
        ):
            return False
    return True


def _validate_dependencies(records: list[ActivityRecord]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    activities = {record.activity.activity_id: record.activity for record in records}
    record_by_id = {record.activity.activity_id: record for record in records}
    hard_graph: dict[str, list[str]] = defaultdict(list)

    for record in records:
        activity = record.activity
        for group_index, group in enumerate(activity.dependency_groups):
            feasibilities: list[bool | None] = []
            future_dependencies: list[str] = []
            for predecessor_id in group.activity_ids:
                predecessor = activities.get(predecessor_id)
                if predecessor is None or predecessor_id == activity.activity_id:
                    continue
                feasibility = _dependency_is_feasible(
                    predecessor,
                    activity,
                    group.minimum_lag_minutes,
                    group.maximum_lag_minutes,
                )
                feasibilities.append(feasibility)
                if record_by_id[predecessor_id].day.date > record.day.date:
                    future_dependencies.append(predecessor_id)
                    if group.mode is DependencyMode.all:
                        issues.append(
                            issue(
                                "FUTURE_DEPENDENCY",
                                "temporal",
                                f"{record.path}.dependencyGroups[{group_index}]",
                                f"Activity '{activity.activity_id}' depends on future activity "
                                f"'{predecessor_id}'.",
                            )
                        )
                if group.mode is DependencyMode.all:
                    hard_graph[activity.activity_id].append(predecessor_id)
                    if feasibility is False:
                        issues.append(
                            issue(
                                "IMPOSSIBLE_PRECEDENCE",
                                "temporal",
                                f"{record.path}.dependencyGroups[{group_index}]",
                                f"Activity '{predecessor_id}' cannot satisfy the timing "
                                f"constraints of '{activity.activity_id}'.",
                            )
                        )
            if (
                group.mode is DependencyMode.any
                and feasibilities
                and all(item is False for item in feasibilities)
            ):
                issues.append(
                    issue(
                        "IMPOSSIBLE_ANY_DEPENDENCY",
                        "temporal",
                        f"{record.path}.dependencyGroups[{group_index}]",
                        f"No alternative predecessor can satisfy activity "
                        f"'{activity.activity_id}'.",
                    )
                )
            if (
                group.mode is DependencyMode.any
                and future_dependencies
                and len(future_dependencies) == len(feasibilities)
            ):
                issues.append(
                    issue(
                        "FUTURE_DEPENDENCY",
                        "temporal",
                        f"{record.path}.dependencyGroups[{group_index}]",
                        f"Every alternative predecessor of '{activity.activity_id}' occurs "
                        "on a future day.",
                    )
                )

    state: dict[str, int] = {}
    reported: set[tuple[str, ...]] = set()

    def visit(activity_id: str, stack: list[str]) -> None:
        marker = state.get(activity_id, 0)
        if marker == 2:
            return
        if marker == 1 and activity_id in stack:
            start = stack.index(activity_id)
            cycle = tuple(stack[start:] + [activity_id])
            if cycle not in reported:
                reported.add(cycle)
                issues.append(
                    issue(
                        "DEPENDENCY_CYCLE",
                        "temporal",
                        "$.days",
                        f"Hard dependency cycle detected: {' -> '.join(cycle)}.",
                    )
                )
            return
        state[activity_id] = 1
        for predecessor_id in hard_graph.get(activity_id, []):
            visit(predecessor_id, [*stack, activity_id])
        state[activity_id] = 2

    for activity_id in hard_graph:
        visit(activity_id, [])
    return issues


def _validate_fallbacks(records: list[ActivityRecord]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    activities = {record.activity.activity_id: record for record in records}
    fallback_graph: dict[str, str] = {}
    for record in records:
        activity = record.activity
        if activity.activation.mode is not ActivationMode.fallback:
            continue
        target_id = activity.activation.fallback_for_activity_id
        if target_id is None or target_id not in activities:
            continue
        target_record = activities[target_id]
        target = target_record.activity
        fallback_graph[activity.activity_id] = target_id
        if target.activation.mode is ActivationMode.fallback:
            issues.append(
                issue(
                    "FALLBACK_TARGET_IS_FALLBACK",
                    "semantic",
                    f"{record.path}.activation.fallbackForActivityId",
                    f"Fallback '{activity.activity_id}' targets another fallback '{target_id}'.",
                )
            )
        if activity.actor_id != target.actor_id:
            issues.append(
                issue(
                    "FALLBACK_ACTOR_MISMATCH",
                    "semantic",
                    f"{record.path}.actorId",
                    f"Fallback '{activity.activity_id}' and target '{target_id}' have different "
                    "actors.",
                )
            )
        if record.day.date != target_record.day.date:
            issues.append(
                issue(
                    "FALLBACK_DAY_MISMATCH",
                    "semantic",
                    f"{record.path}.activation.fallbackForActivityId",
                    f"Fallback '{activity.activity_id}' and target '{target_id}' are on "
                    "different days.",
                )
            )
    state: dict[str, int] = {}
    reported: set[tuple[str, ...]] = set()

    def visit(activity_id: str, stack: list[str]) -> None:
        marker = state.get(activity_id, 0)
        if marker == 2:
            return
        if marker == 1 and activity_id in stack:
            start = stack.index(activity_id)
            cycle_nodes = stack[start:]
            canonical = min(
                tuple(cycle_nodes[index:] + cycle_nodes[:index])
                for index in range(len(cycle_nodes))
            )
            if canonical not in reported:
                reported.add(canonical)
                closed_cycle = [*canonical, canonical[0]]
                issues.append(
                    issue(
                        "FALLBACK_CYCLE",
                        "semantic",
                        "$.days",
                        f"Fallback cycle detected: {' -> '.join(closed_cycle)}.",
                    )
                )
            return
        state[activity_id] = 1
        target_id = fallback_graph.get(activity_id)
        if target_id in fallback_graph:
            visit(target_id, [*stack, activity_id])
        state[activity_id] = 2

    for fallback_id in fallback_graph:
        visit(fallback_id, [])
    return issues


def _fixed_interval(activity: Activity) -> tuple[datetime, datetime] | None:
    start = activity.start_window
    if start is None or not (start.earliest == start.preferred == start.latest):
        return None
    if activity.end_window is not None:
        end = activity.end_window
        if end.earliest == end.preferred == end.latest:
            return start.preferred, end.preferred
        return None
    if activity.duration is not None:
        duration = activity.duration
        if duration.minimum_minutes == duration.preferred_minutes == duration.maximum_minutes:
            return start.preferred, start.preferred + timedelta(minutes=duration.preferred_minutes)
    return None


def _overlap(first: tuple[datetime, datetime], second: tuple[datetime, datetime]) -> bool:
    return first[0] < second[1] and second[0] < first[1]


def _occupied_residents(activity: Activity, resident_ids: set[str]) -> set[str]:
    occupied = set(activity.participant_ids) & resident_ids
    if not activity.can_overlap_for_actor:
        occupied.add(activity.actor_id)
    return occupied


def _validate_fixed_conflicts(
    scenario: Scenario,
    records: list[ActivityRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    resident_ids = {resident.resident_id for resident in scenario.residents}
    fixed_records = [
        (record, interval)
        for record in records
        if record.activity.mandatory
        and record.activity.activation.mode is ActivationMode.always
        and (interval := _fixed_interval(record.activity)) is not None
    ]
    for (first_record, first_interval), (second_record, second_interval) in combinations(
        fixed_records, 2
    ):
        shared = _occupied_residents(first_record.activity, resident_ids) & _occupied_residents(
            second_record.activity, resident_ids
        )
        if shared and _overlap(first_interval, second_interval):
            issues.append(
                issue(
                    "FIXED_ACTIVITY_OVERLAP",
                    "temporal",
                    "$.days",
                    f"Mandatory fixed activities '{first_record.activity.activity_id}' and "
                    f"'{second_record.activity.activity_id}' overlap for residents "
                    f"{sorted(shared)}.",
                )
            )

    for first, second in combinations(scenario.commitments, 2):
        shared = set(first.participant_ids) & set(second.participant_ids) & resident_ids
        if (
            first.mandatory
            and second.mandatory
            and shared
            and _overlap((first.start, first.end), (second.start, second.end))
        ):
            issues.append(
                issue(
                    "COMMITMENT_OVERLAP",
                    "temporal",
                    "$.commitments",
                    f"Commitments '{first.commitment_id}' and '{second.commitment_id}' overlap "
                    f"for residents {sorted(shared)}.",
                )
            )

    commitments = {item.commitment_id: item for item in scenario.commitments}
    for record in records:
        activity = record.activity
        if activity.commitment_id is None or activity.commitment_id not in commitments:
            continue
        commitment = commitments[activity.commitment_id]
        involved = {activity.actor_id, *activity.participant_ids}
        if commitment.mandatory and not activity.mandatory:
            issues.append(
                issue(
                    "MANDATORY_COMMITMENT_OPTIONAL_ACTIVITY",
                    "semantic",
                    f"{record.path}.mandatory",
                    f"Activity '{activity.activity_id}' is optional but commitment "
                    f"'{commitment.commitment_id}' is mandatory.",
                )
            )
        if not involved.issubset(set(commitment.participant_ids)):
            issues.append(
                issue(
                    "ACTIVITY_COMMITMENT_PARTICIPANT_MISMATCH",
                    "semantic",
                    f"{record.path}.commitmentId",
                    f"Activity '{activity.activity_id}' participants do not match commitment "
                    f"'{commitment.commitment_id}'.",
                )
            )
        if commitment.location_id not in activity.location_ids:
            issues.append(
                issue(
                    "ACTIVITY_COMMITMENT_LOCATION_MISMATCH",
                    "semantic",
                    f"{record.path}.commitmentId",
                    f"Activity '{activity.activity_id}' does not include commitment location "
                    f"'{commitment.location_id}'.",
                )
            )
        if activity.start_window is not None and not (
            activity.start_window.earliest <= commitment.start <= activity.start_window.latest
        ):
            issues.append(
                issue(
                    "ACTIVITY_COMMITMENT_TIME_MISMATCH",
                    "temporal",
                    f"{record.path}.startWindow",
                    f"Activity '{activity.activity_id}' cannot start at commitment "
                    f"'{commitment.commitment_id}'.",
                )
            )

        earliest_end = _earliest_end(activity)
        latest_end = _latest_end(activity)
        if (
            earliest_end is not None
            and latest_end is not None
            and not earliest_end <= commitment.end <= latest_end
        ):
            issues.append(
                issue(
                    "ACTIVITY_COMMITMENT_END_MISMATCH",
                    "temporal",
                    record.path,
                    f"Activity '{activity.activity_id}' cannot end at commitment "
                    f"'{commitment.commitment_id}'.",
                )
            )

    for record, interval in fixed_records:
        activity = record.activity
        occupied = _occupied_residents(activity, resident_ids)
        for commitment in scenario.commitments:
            if activity.commitment_id == commitment.commitment_id:
                continue
            shared = occupied & set(commitment.participant_ids) & resident_ids
            if (
                commitment.mandatory
                and shared
                and _overlap(interval, (commitment.start, commitment.end))
            ):
                issues.append(
                    issue(
                        "FIXED_ACTIVITY_COMMITMENT_OVERLAP",
                        "temporal",
                        record.path,
                        f"Fixed activity '{activity.activity_id}' overlaps commitment "
                        f"'{commitment.commitment_id}' for residents {sorted(shared)}.",
                    )
                )

    linked_commitments = {
        record.activity.commitment_id
        for record in records
        if record.activity.commitment_id is not None
    }
    for commitment in scenario.commitments:
        if commitment.commitment_id not in linked_commitments:
            issues.append(
                issue(
                    "UNUSED_COMMITMENT",
                    "semantic",
                    "$.commitments",
                    f"Commitment '{commitment.commitment_id}' is not linked to an activity.",
                    severity="warning",
                )
            )
    return issues


def _expand_locations(scenario: Scenario, location_ids: list[str]) -> set[str]:
    locations = {location.location_id: location for location in scenario.locations}
    expanded: set[str] = set()

    def add(location_id: str) -> None:
        if location_id in expanded:
            return
        expanded.add(location_id)
        location = locations.get(location_id)
        if location is not None:
            for member in location.member_location_ids:
                add(member)

    for location_id in location_ids:
        add(location_id)
    return expanded


def _validate_resource_semantics(
    scenario: Scenario,
    records: list[ActivityRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    resources = {resource.resource_id: resource for resource in scenario.resources}
    fixed_usage: dict[str, list[tuple[datetime, int, str, int]]] = defaultdict(list)

    for record in records:
        activity = record.activity
        expanded_locations = _expand_locations(scenario, activity.location_ids)
        interval = _fixed_interval(activity)
        for requirement in activity.required_resources:
            resource = resources.get(requirement.resource_id)
            if resource is None:
                continue
            if requirement.units > resource.capacity:
                issues.append(
                    issue(
                        "RESOURCE_REQUIREMENT_EXCEEDS_CAPACITY",
                        "semantic",
                        f"{record.path}.requiredResources",
                        f"Activity '{activity.activity_id}' requests {requirement.units} units "
                        f"of '{resource.resource_id}', capacity {resource.capacity}.",
                    )
                )
            if resource.location_id not in expanded_locations:
                issues.append(
                    issue(
                        "RESOURCE_LOCATION_MISMATCH",
                        "semantic",
                        f"{record.path}.requiredResources",
                        f"Resource '{resource.resource_id}' is at '{resource.location_id}', "
                        f"outside activity '{activity.activity_id}' locations.",
                        severity="warning",
                    )
                )
            if (
                interval is not None
                and activity.mandatory
                and activity.activation.mode is ActivationMode.always
            ):
                fixed_usage[resource.resource_id].extend(
                    [
                        (interval[0], 1, activity.activity_id, requirement.units),
                        (interval[1], -1, activity.activity_id, requirement.units),
                    ]
                )

    for resource_id, events in fixed_usage.items():
        resource = resources[resource_id]
        current = 0
        active: set[str] = set()
        reported: set[tuple[str, ...]] = set()
        for _, direction, activity_id, units in sorted(
            events,
            key=lambda item: (item[0], item[1]),
        ):
            if direction == -1:
                current -= units
                active.discard(activity_id)
            else:
                current += units
                active.add(activity_id)
                if current > resource.capacity:
                    conflict = tuple(sorted(active))
                    if conflict not in reported:
                        reported.add(conflict)
                        issues.append(
                            issue(
                                "FIXED_RESOURCE_CAPACITY_EXCEEDED",
                                "temporal",
                                "$.days",
                                f"Fixed activities {list(conflict)} exceed resource "
                                f"'{resource_id}' capacity {resource.capacity}.",
                            )
                        )
    return issues
