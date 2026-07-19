from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from smart_home_sim.domain.models import Activity, DayPlan, DependencyMode, Scenario
from smart_home_sim.domain.plan import ObjectiveValues

MICROSECONDS_PER_MINUTE = 60_000_000
MAX_SOLVER_VALUE = 2**60
MAX_DETERMINISTIC_TIME = 2.0


class TimePrecisionError(ValueError):
    def __init__(self, activity_id: str, field_name: str, value: float) -> None:
        self.activity_id = activity_id
        self.field_name = field_name
        self.value = value
        super().__init__(f"{activity_id}.{field_name}={value}")


class SolverRangeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceRecord:
    day_index: int
    activity_index: int
    day: DayPlan
    activity: Activity

    @property
    def path(self) -> str:
        return f"$.days[{self.day_index}].activities[{self.activity_index}]"


@dataclass(frozen=True, slots=True)
class ScheduledValue:
    record: SourceRecord
    start: int
    end: int
    selected_dependency_ids: tuple[str, ...]


@dataclass(slots=True)
class ActivityVariables:
    record: SourceRecord
    presence: cp_model.IntVar
    start: cp_model.IntVar
    duration: cp_model.IntVar
    end: cp_model.IntVar
    interval: cp_model.IntervalVar
    selected_any: dict[str, cp_model.IntVar] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SolveOutcome:
    status: str
    values: dict[str, ScheduledValue]
    omitted_activity_ids: tuple[str, ...]
    objective_values: ObjectiveValues | None
    failure: Literal["infeasible", "model_invalid", "not_optimal"] | None = None
    model_error: str | None = None


@dataclass(frozen=True, slots=True)
class TimeAxis:
    origin: datetime
    zone: ZoneInfo
    simulation_end: int
    horizon: int

    @classmethod
    def from_scenario(
        cls,
        scenario: Scenario,
        records: list[SourceRecord],
    ) -> TimeAxis:
        origin = scenario.simulation_window.start.astimezone(UTC)
        zone = ZoneInfo(scenario.time_zone)
        simulation_end = timedelta_microseconds(
            scenario.simulation_window.end.astimezone(UTC) - origin
        )
        max_duration = 1
        for record in records:
            activity = record.activity
            if activity.duration is not None:
                max_duration = max(
                    max_duration,
                    duration_microseconds(
                        activity.activity_id,
                        "maximumMinutes",
                        activity.duration.maximum_minutes,
                    ),
                )
        horizon = simulation_end + max_duration
        if horizon <= 0 or horizon > MAX_SOLVER_VALUE:
            raise SolverRangeError(f"solver horizon {horizon} is outside the safe range")
        if horizon * max(1, len(records)) > MAX_SOLVER_VALUE:
            raise SolverRangeError("aggregate scheduling horizon is outside the safe range")
        return cls(origin=origin, zone=zone, simulation_end=simulation_end, horizon=horizon)

    def to_tick(self, value: datetime) -> int:
        return timedelta_microseconds(value.astimezone(UTC) - self.origin)

    def to_datetime(self, value: int) -> datetime:
        return (self.origin + timedelta(microseconds=value)).astimezone(self.zone)

    def day_bounds(self, value: date) -> tuple[int, int]:
        local_start = datetime.combine(value, time.min, self.zone)
        local_end = datetime.combine(value + timedelta(days=1), time.min, self.zone)
        return (
            max(0, self.to_tick(local_start)),
            min(self.simulation_end, self.to_tick(local_end)),
        )


def activity_records(scenario: Scenario) -> list[SourceRecord]:
    return [
        SourceRecord(day_index, activity_index, day, activity)
        for day_index, day in enumerate(scenario.days)
        for activity_index, activity in enumerate(day.activities)
    ]


def timedelta_microseconds(value: timedelta) -> int:
    return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds


def duration_microseconds(activity_id: str, field_name: str, value: float) -> int:
    exact = Decimal(str(value)) * MICROSECONDS_PER_MINUTE
    integral = exact.to_integral_value()
    if exact != integral:
        raise TimePrecisionError(activity_id, field_name, value)
    result = int(integral)
    if result <= 0 or result > MAX_SOLVER_VALUE:
        raise SolverRangeError(f"duration {result} is outside the safe range")
    return result


def occupied_residents(activity: Activity, resident_ids: set[str]) -> set[str]:
    occupied = set(activity.participant_ids) & resident_ids
    if not activity.can_overlap_for_actor:
        occupied.add(activity.actor_id)
    return occupied


class ScheduleSolver:
    def __init__(
        self,
        scenario: Scenario,
        axis: TimeAxis,
        records: list[SourceRecord],
        fixed_schedule: dict[str, ScheduledValue] | None = None,
        excluded_fixed_activity_ids: set[str] | None = None,
        default_start_anchors: dict[str, int] | None = None,
        forced_present_activity_ids: set[str] | None = None,
    ) -> None:
        self.scenario = scenario
        self.axis = axis
        self.records = sorted(records, key=lambda item: item.activity.activity_id)
        self.fixed_schedule = fixed_schedule or {}
        self.excluded_fixed_activity_ids = excluded_fixed_activity_ids or set()
        self.default_start_anchors = default_start_anchors or {}
        self.forced_present_activity_ids = forced_present_activity_ids or set()
        self.model = cp_model.CpModel()
        self.variables: dict[str, ActivityVariables] = {}
        self.duration_deviations: list[cp_model.IntVar] = []
        self.temporal_deviations: list[cp_model.IntVar] = []
        self.effective_starts: list[cp_model.IntVar] = []
        self.resident_ids = {item.resident_id for item in scenario.residents}
        self.commitments = {item.commitment_id: item for item in scenario.commitments}

    def solve(self) -> SolveOutcome:
        self._create_activity_variables()
        self._add_dependencies()
        self._add_resident_constraints()
        self._add_commitment_constraints()
        self._add_resource_constraints()
        objective_variables = self._create_objective_variables()
        self.model.add_decision_strategy(
            [item.presence for item in self.variables.values()],
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MAX_VALUE,
        )
        self.model.add_decision_strategy(
            [item.start for item in self.variables.values()],
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MIN_VALUE,
        )
        self.model.add_decision_strategy(
            [item.duration for item in self.variables.values()],
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MIN_VALUE,
        )

        model_error = self.model.validate()
        if model_error:
            return SolveOutcome(
                status="MODEL_INVALID",
                values={},
                omitted_activity_ids=(),
                objective_values=None,
                failure="model_invalid",
                model_error=model_error,
            )

        selection_stages = [
            ("max", objective_variables["optional_priority"]),
            ("max", objective_variables["optional_count"]),
        ]
        solver: cp_model.CpSolver | None = None
        status = cp_model.UNKNOWN
        for direction, variable in selection_stages:
            if direction == "max":
                self.model.maximize(variable)
            else:
                self.model.minimize(variable)
            solver = self._new_solver()
            status = solver.solve(self.model)
            if status == cp_model.INFEASIBLE:
                return SolveOutcome(
                    status=solver.status_name(status),
                    values={},
                    omitted_activity_ids=(),
                    objective_values=None,
                    failure="infeasible",
                )
            if status == cp_model.MODEL_INVALID:
                return SolveOutcome(
                    status=solver.status_name(status),
                    values={},
                    omitted_activity_ids=(),
                    objective_values=None,
                    failure="model_invalid",
                    model_error=self.model.validate() or "CP-SAT rejected the model",
                )
            if status != cp_model.OPTIMAL:
                return SolveOutcome(
                    status=solver.status_name(status),
                    values={},
                    omitted_activity_ids=(),
                    objective_values=None,
                    failure="not_optimal",
                )
            optimum = solver.value(variable)
            self.model.add(variable == optimum)
            self.model.clear_objective()

        for variables in sorted(
            self.variables.values(),
            key=lambda item: item.record.activity.activity_id,
        ):
            if variables.record.activity.mandatory:
                continue
            status, solver = self._try_lock_value(
                variables.presence,
                1,
                f"canonical_optional__{variables.record.activity.activity_id}",
            )
            if status not in {cp_model.OPTIMAL, cp_model.INFEASIBLE}:
                return self._not_optimal_outcome(status, solver)

        for variables in sorted(
            self.variables.values(),
            key=lambda item: (item.record.day_index, item.record.activity_index),
        ):
            activity = variables.record.activity
            preferences: list[tuple[cp_model.IntVar, int, str]] = []
            if activity.duration is not None:
                preferences.append(
                    (
                        variables.duration,
                        duration_microseconds(
                            activity.activity_id,
                            "preferredMinutes",
                            activity.duration.preferred_minutes,
                        ),
                        "duration",
                    )
                )
            if activity.start_window is not None:
                preferences.append(
                    (
                        variables.start,
                        self.axis.to_tick(activity.start_window.preferred),
                        "start",
                    )
                )
            if activity.end_window is not None:
                preferences.append(
                    (
                        variables.end,
                        self.axis.to_tick(activity.end_window.preferred),
                        "end",
                    )
                )
            for variable, target, field_name in preferences:
                status, solver = self._try_lock_value(
                    variable,
                    target,
                    f"preferred_{field_name}__{activity.activity_id}",
                    presence=variables.presence,
                )
                if status not in {cp_model.OPTIMAL, cp_model.INFEASIBLE}:
                    return self._not_optimal_outcome(status, solver)

        solver = self._new_solver()
        status = solver.solve(self.model)
        if status != cp_model.OPTIMAL:
            if status == cp_model.INFEASIBLE:
                return SolveOutcome(
                    status=solver.status_name(status),
                    values={},
                    omitted_activity_ids=(),
                    objective_values=None,
                    failure="infeasible",
                )
            return self._not_optimal_outcome(status, solver)

        assert solver is not None
        values: dict[str, ScheduledValue] = {}
        omitted: list[str] = []
        for activity_id, variables in self.variables.items():
            if solver.value(variables.presence) == 0:
                omitted.append(activity_id)
                continue
            selected = [
                predecessor_id
                for group in variables.record.activity.dependency_groups
                if group.mode is DependencyMode.all
                for predecessor_id in group.activity_ids
            ]
            selected.extend(
                predecessor_id
                for predecessor_id, choice in variables.selected_any.items()
                if solver.value(choice) == 1
            )
            values[activity_id] = ScheduledValue(
                record=variables.record,
                start=solver.value(variables.start),
                end=solver.value(variables.end),
                selected_dependency_ids=tuple(sorted(selected)),
            )
        objective_values = ObjectiveValues(
            optional_priority_score=solver.value(objective_variables["optional_priority"]),
            optional_activity_count=solver.value(objective_variables["optional_count"]),
            duration_deviation_microseconds=solver.value(objective_variables["duration_deviation"]),
            temporal_deviation_microseconds=solver.value(objective_variables["temporal_deviation"]),
            scheduled_start_sum_microseconds=solver.value(objective_variables["start_sum"]),
        )
        return SolveOutcome(
            status=solver.status_name(status),
            values=values,
            omitted_activity_ids=tuple(sorted(omitted)),
            objective_values=objective_values,
        )

    def _try_lock_value(
        self,
        variable: cp_model.IntVar,
        target: int,
        name: str,
        presence: cp_model.IntVar | None = None,
    ) -> tuple[int, cp_model.CpSolver]:
        lock = self.model.new_bool_var(f"lock__{name}")
        enforcement = [lock] if presence is None else [lock, presence]
        self.model.add(variable == target).only_enforce_if(enforcement)
        self.model.add_assumption(lock)
        solver = self._new_solver()
        status = solver.solve(self.model)
        self.model.clear_assumptions()
        self.model.add(lock == (1 if status == cp_model.OPTIMAL else 0))
        if presence is None and status == cp_model.INFEASIBLE:
            self.model.add(variable != target)
        return status, solver

    @staticmethod
    def _not_optimal_outcome(
        status: int,
        solver: cp_model.CpSolver,
    ) -> SolveOutcome:
        return SolveOutcome(
            status=solver.status_name(status),
            values={},
            omitted_activity_ids=(),
            objective_values=None,
            failure="not_optimal",
        )

    def _new_solver(self) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        solver.parameters.max_deterministic_time = MAX_DETERMINISTIC_TIME
        solver.parameters.log_search_progress = False
        return solver

    def _create_activity_variables(self) -> None:
        for record in self.records:
            activity = record.activity
            activity_id = activity.activity_id
            day_start, day_end = self.axis.day_bounds(record.day.date)
            if activity.start_window is not None:
                start_min = self.axis.to_tick(activity.start_window.earliest)
                start_max = self.axis.to_tick(activity.start_window.latest)
                preferred_start = self.axis.to_tick(activity.start_window.preferred)
            else:
                anchor = self.default_start_anchors.get(activity_id, day_start)
                start_min = max(day_start, anchor)
                start_max = max(start_min, day_end - 1)
                preferred_start = start_min

            presence = self.model.new_bool_var(f"present__{activity_id}")
            if activity.mandatory or activity_id in self.forced_present_activity_ids:
                self.model.add(presence == 1)
            start = self.model.new_int_var(start_min, start_max, f"start__{activity_id}")

            if activity.duration is not None:
                duration_min = duration_microseconds(
                    activity_id,
                    "minimumMinutes",
                    activity.duration.minimum_minutes,
                )
                duration_max = duration_microseconds(
                    activity_id,
                    "maximumMinutes",
                    activity.duration.maximum_minutes,
                )
                preferred_duration = duration_microseconds(
                    activity_id,
                    "preferredMinutes",
                    activity.duration.preferred_minutes,
                )
                duration = self.model.new_int_var(
                    duration_min,
                    duration_max,
                    f"duration__{activity_id}",
                )
                end = self.model.new_int_var(0, self.axis.horizon, f"end__{activity_id}")
                self.duration_deviations.append(
                    self._conditional_deviation(
                        duration,
                        preferred_duration,
                        presence,
                        f"duration_deviation__{activity_id}",
                    )
                )
            else:
                assert activity.end_window is not None
                end_min = self.axis.to_tick(activity.end_window.earliest)
                end_max = self.axis.to_tick(activity.end_window.latest)
                preferred_end = self.axis.to_tick(activity.end_window.preferred)
                duration = self.model.new_int_var(1, self.axis.horizon, f"duration__{activity_id}")
                end = self.model.new_int_var(end_min, end_max, f"end__{activity_id}")
                preferred_duration = max(1, preferred_end - preferred_start)
                if activity.start_window is not None:
                    self.duration_deviations.append(
                        self._conditional_deviation(
                            duration,
                            preferred_duration,
                            presence,
                            f"duration_deviation__{activity_id}",
                        )
                    )
                self.temporal_deviations.append(
                    self._conditional_deviation(
                        end,
                        preferred_end,
                        presence,
                        f"end_deviation__{activity_id}",
                    )
                )

            interval = self.model.new_optional_interval_var(
                start,
                duration,
                end,
                presence,
                f"interval__{activity_id}",
            )
            if not activity.allow_boundary_truncation:
                self.model.add(end <= self.axis.simulation_end).only_enforce_if(presence)
            commitment = (
                self.commitments.get(activity.commitment_id)
                if activity.commitment_id is not None
                else None
            )
            if commitment is not None:
                self.model.add(start == self.axis.to_tick(commitment.start)).only_enforce_if(
                    presence
                )
                self.model.add(end == self.axis.to_tick(commitment.end)).only_enforce_if(presence)

            if activity.start_window is not None:
                self.temporal_deviations.append(
                    self._conditional_deviation(
                        start,
                        preferred_start,
                        presence,
                        f"start_deviation__{activity_id}",
                    )
                )
            effective_start = self.model.new_int_var(
                0,
                self.axis.horizon,
                f"effective_start__{activity_id}",
            )
            self.model.add(effective_start == start).only_enforce_if(presence)
            self.model.add(effective_start == 0).only_enforce_if(presence.negated())
            self.effective_starts.append(effective_start)
            self.variables[activity_id] = ActivityVariables(
                record=record,
                presence=presence,
                start=start,
                duration=duration,
                end=end,
                interval=interval,
            )

    def _conditional_deviation(
        self,
        variable: cp_model.IntVar,
        target: int,
        presence: cp_model.IntVar,
        name: str,
    ) -> cp_model.IntVar:
        raw = self.model.new_int_var(0, self.axis.horizon, f"raw__{name}")
        self.model.add_abs_equality(raw, variable - target)
        effective = self.model.new_int_var(0, self.axis.horizon, name)
        self.model.add(effective == raw).only_enforce_if(presence)
        self.model.add(effective == 0).only_enforce_if(presence.negated())
        return effective

    def _add_dependencies(self) -> None:
        for activity_id, variables in self.variables.items():
            activity = variables.record.activity
            for group_index, group in enumerate(activity.dependency_groups):
                minimum_lag = (
                    duration_microseconds(
                        activity_id,
                        f"dependencyGroups[{group_index}].minimumLagMinutes",
                        group.minimum_lag_minutes,
                    )
                    if group.minimum_lag_minutes > 0
                    else 0
                )
                maximum_lag = (
                    duration_microseconds(
                        activity_id,
                        f"dependencyGroups[{group_index}].maximumLagMinutes",
                        group.maximum_lag_minutes,
                    )
                    if group.maximum_lag_minutes is not None and group.maximum_lag_minutes > 0
                    else 0
                    if group.maximum_lag_minutes == 0
                    else None
                )
                if group.mode is DependencyMode.all:
                    for predecessor_id in group.activity_ids:
                        self._add_all_dependency(
                            variables,
                            predecessor_id,
                            minimum_lag,
                            maximum_lag,
                        )
                else:
                    choices: list[cp_model.IntVar] = []
                    for predecessor_id in group.activity_ids:
                        choice = self.model.new_bool_var(
                            f"dependency_choice__{activity_id}__{group_index}__{predecessor_id}"
                        )
                        variables.selected_any[predecessor_id] = choice
                        choices.append(choice)
                        self._add_any_dependency_choice(
                            variables,
                            predecessor_id,
                            choice,
                            minimum_lag,
                            maximum_lag,
                        )
                    self.model.add(sum(choices) == variables.presence)

    def _add_all_dependency(
        self,
        successor: ActivityVariables,
        predecessor_id: str,
        minimum_lag: int,
        maximum_lag: int | None,
    ) -> None:
        predecessor = self.variables.get(predecessor_id)
        if predecessor is not None:
            self.model.add(successor.presence <= predecessor.presence)
            predecessor_end = predecessor.end
        elif (
            predecessor_id in self.fixed_schedule
            and predecessor_id not in self.excluded_fixed_activity_ids
        ):
            predecessor_end = self.fixed_schedule[predecessor_id].end
        else:
            self.model.add(successor.presence == 0)
            return
        self.model.add(successor.start >= predecessor_end + minimum_lag).only_enforce_if(
            successor.presence
        )
        if maximum_lag is not None:
            self.model.add(successor.start <= predecessor_end + maximum_lag).only_enforce_if(
                successor.presence
            )

    def _add_any_dependency_choice(
        self,
        successor: ActivityVariables,
        predecessor_id: str,
        choice: cp_model.IntVar,
        minimum_lag: int,
        maximum_lag: int | None,
    ) -> None:
        predecessor = self.variables.get(predecessor_id)
        if predecessor is not None:
            self.model.add(choice <= predecessor.presence)
            predecessor_end = predecessor.end
        elif (
            predecessor_id in self.fixed_schedule
            and predecessor_id not in self.excluded_fixed_activity_ids
        ):
            predecessor_end = self.fixed_schedule[predecessor_id].end
        else:
            self.model.add(choice == 0)
            return
        self.model.add(successor.start >= predecessor_end + minimum_lag).only_enforce_if(choice)
        if maximum_lag is not None:
            self.model.add(successor.start <= predecessor_end + maximum_lag).only_enforce_if(choice)

    def _add_resident_constraints(self) -> None:
        intervals: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)
        for variables in self.variables.values():
            for resident_id in occupied_residents(variables.record.activity, self.resident_ids):
                intervals[resident_id].append(variables.interval)
        for fixed in self._included_fixed_values():
            interval = self.model.new_fixed_size_interval_var(
                fixed.start,
                fixed.end - fixed.start,
                f"fixed__{fixed.record.activity.activity_id}",
            )
            for resident_id in occupied_residents(fixed.record.activity, self.resident_ids):
                intervals[resident_id].append(interval)
        for resident_intervals in intervals.values():
            self.model.add_no_overlap(resident_intervals)

    def _add_commitment_constraints(self) -> None:
        for variables in self.variables.values():
            activity = variables.record.activity
            occupied = occupied_residents(activity, self.resident_ids)
            for commitment in self.scenario.commitments:
                if activity.commitment_id == commitment.commitment_id:
                    continue
                if not occupied & set(commitment.participant_ids) & self.resident_ids:
                    continue
                before = self.model.new_bool_var(
                    f"before_commitment__{activity.activity_id}__{commitment.commitment_id}"
                )
                self.model.add(
                    variables.end <= self.axis.to_tick(commitment.start)
                ).only_enforce_if([variables.presence, before])
                self.model.add(
                    variables.start >= self.axis.to_tick(commitment.end)
                ).only_enforce_if([variables.presence, before.negated()])

    def _add_resource_constraints(self) -> None:
        intervals: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)
        demands: dict[str, list[int]] = defaultdict(list)
        resources = {item.resource_id: item for item in self.scenario.resources}
        for variables in self.variables.values():
            for requirement in variables.record.activity.required_resources:
                intervals[requirement.resource_id].append(variables.interval)
                demands[requirement.resource_id].append(requirement.units)
        for fixed in self._included_fixed_values():
            if not fixed.record.activity.required_resources:
                continue
            interval = self.model.new_fixed_size_interval_var(
                fixed.start,
                fixed.end - fixed.start,
                f"fixed_resource__{fixed.record.activity.activity_id}",
            )
            for requirement in fixed.record.activity.required_resources:
                intervals[requirement.resource_id].append(interval)
                demands[requirement.resource_id].append(requirement.units)
        for resource_id, resource_intervals in intervals.items():
            self.model.add_cumulative(
                resource_intervals,
                demands[resource_id],
                resources[resource_id].capacity,
            )

    def _included_fixed_values(self) -> list[ScheduledValue]:
        return [
            value
            for activity_id, value in sorted(self.fixed_schedule.items())
            if activity_id not in self.excluded_fixed_activity_ids
        ]

    def _create_objective_variables(self) -> dict[str, cp_model.IntVar]:
        optional = [
            variables
            for variables in self.variables.values()
            if not variables.record.activity.mandatory
        ]
        optional_priority = self.model.new_int_var(
            0,
            sum(item.record.activity.priority for item in optional),
            "objective_optional_priority",
        )
        self.model.add(
            optional_priority
            == sum(item.record.activity.priority * item.presence for item in optional)
        )
        optional_count = self.model.new_int_var(0, len(optional), "objective_optional_count")
        self.model.add(optional_count == sum(item.presence for item in optional))
        duration_deviation = self.model.new_int_var(
            0,
            self.axis.horizon * max(1, len(self.duration_deviations)),
            "objective_duration_deviation",
        )
        self.model.add(duration_deviation == sum(self.duration_deviations))
        temporal_deviation = self.model.new_int_var(
            0,
            self.axis.horizon * max(1, len(self.temporal_deviations)),
            "objective_temporal_deviation",
        )
        self.model.add(temporal_deviation == sum(self.temporal_deviations))
        start_sum = self.model.new_int_var(
            0,
            self.axis.horizon * max(1, len(self.effective_starts)),
            "objective_start_sum",
        )
        self.model.add(start_sum == sum(self.effective_starts))
        return {
            "optional_priority": optional_priority,
            "optional_count": optional_count,
            "duration_deviation": duration_deviation,
            "temporal_deviation": temporal_deviation,
            "start_sum": start_sum,
        }
