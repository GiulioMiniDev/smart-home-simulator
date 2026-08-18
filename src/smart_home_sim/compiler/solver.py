from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from math import gcd
from typing import Literal
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from smart_home_sim.domain.models import Activity, DayPlan, DependencyMode, Scenario
from smart_home_sim.domain.plan import ObjectiveValues

MICROSECONDS_PER_MINUTE = 60_000_000
MAX_SOLVER_VALUE = 2**60
MAX_DETERMINISTIC_TIME = 2.0
# Budget for the value-fixing probes alone. Their only observable result is the status, so this
# cannot reach the canonical plan; what it buys is a conclusive answer. A contended horizon —
# wide windows, real collisions to resolve — exhausts the frozen budget on some probes and
# reports `UNKNOWN`, which aborts an otherwise sound compilation with `SOLVER_NOT_OPTIMAL`.
FEASIBILITY_DETERMINISTIC_TIME = 30.0
# A ceiling on the whole canonicalisation, not on one probe. `MAX_DETERMINISTIC_TIME` bounds a
# single solve and never fired on the horizon that started this: each probe was individually
# quick, and it was their number — 7 740 of them — that turned compilation into a thirteen-hour
# silence with no error and no progress. A budget on the total is the only thing that can see
# that. Generous enough that no honest horizon meets it, small enough that a runaway is reported
# in minutes rather than discovered by giving up.
MAX_FEASIBILITY_PROBES = 20_000
# Above this many ticks a probe's model is wide enough that CP-SAT's presolve earns its keep; below
# it, propagation settles every probe on its own and presolving the same model thousands of times is
# the dominant cost. The two regimes measured eight orders of magnitude apart — 2.2e5 ticks for a
# minute-resolution five-month horizon against 1.3e13 for the same horizon in microseconds — so the
# boundary only has to fall somewhere in between, not be tuned.
PRESOLVE_FREE_HORIZON_TICKS = 10_000_000


class CompilationBudgetError(RuntimeError):
    """The canonicalisation needed more feasibility probes than the budget allows."""

    def __init__(self, probes: int, budget: int) -> None:
        self.probes = probes
        self.budget = budget
        super().__init__(
            f"exhausted the compilation budget of {budget} after {probes} feasibility probes"
        )


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
class LockRequest:
    """One deterministic value-fixing attempt of the `priority-preference-1.0.0` policy."""

    variable: cp_model.IntVar
    target: int
    name: str
    presence: cp_model.IntVar | None = None


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
    """The scheduling model's unit of time, and the only place instants become integers.

    ``step`` is how many microseconds one solver tick is worth. It is not a fixed constant but the
    greatest common divisor of every instant and duration this scenario can ask for, so no
    representable value is lost: every window bound, every duration and every day boundary is an
    exact multiple of it, and therefore so is every schedule satisfying them.

    The unit matters because it is the width of what the solver has to search. Working in
    microseconds gave a two-day window start variables with 207 billion possible values to
    represent 3 458 reachable minutes. That costs nothing while unit propagation settles the
    schedule on its own, which is what happens on almost every day. But where propagation is not
    enough and CP-SAT has to search, the fixed CHOOSE_FIRST/SELECT_MIN_VALUE strategy walks those
    domains: one week of a five-month horizon took 714 seconds against 25 for its neighbours,
    burning 258 887 branches for 2 399 conflicts — a hundred decisions per thing learned.
    """

    origin: datetime
    zone: ZoneInfo
    step: int
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
        # Judged on the span itself, before the resolution shrinks it: how much time a scenario is
        # allowed to ask for is a statement about the input, and must not quietly widen because
        # this particular document happens to be expressible in coarser ticks.
        if horizon <= 0 or horizon > MAX_SOLVER_VALUE:
            raise SolverRangeError(f"solver horizon {horizon} is outside the safe range")
        if horizon * max(1, len(records)) > MAX_SOLVER_VALUE:
            raise SolverRangeError("aggregate scheduling horizon is outside the safe range")
        step = cls._resolution(scenario, records, origin, zone, simulation_end)
        horizon //= step
        return cls(
            origin=origin,
            zone=zone,
            step=step,
            simulation_end=simulation_end // step,
            horizon=horizon,
        )

    @staticmethod
    def _resolution(
        scenario: Scenario,
        records: list[SourceRecord],
        origin: datetime,
        zone: ZoneInfo,
        simulation_end: int,
    ) -> int:
        """The coarsest tick that still lands exactly on everything this scenario declares.

        Deliberately derived, not chosen: a scenario written in whole minutes gets minute ticks, one
        that declares a ten-second gesture gets ten-second ticks, and one that needs microseconds
        gets microseconds and is no worse off than before. The divisor has to cover every quantity
        that becomes a bound in the model — window edges, durations, commitments and the local
        midnights that delimit a day — because a value it did not divide would be unrepresentable
        rather than merely coarse.
        """
        step = simulation_end

        def observe(value: int) -> None:
            nonlocal step
            step = gcd(step, abs(value))

        def observe_instant(value: datetime) -> None:
            observe(timedelta_microseconds(value.astimezone(UTC) - origin))

        for record in records:
            activity = record.activity
            for window in (activity.start_window, activity.end_window):
                if window is not None:
                    observe_instant(window.earliest)
                    observe_instant(window.preferred)
                    observe_instant(window.latest)
            if activity.duration is not None:
                for field_name, value in (
                    ("minimumMinutes", activity.duration.minimum_minutes),
                    ("preferredMinutes", activity.duration.preferred_minutes),
                    ("maximumMinutes", activity.duration.maximum_minutes),
                ):
                    observe(duration_microseconds(activity.activity_id, field_name, value))
            for group in activity.dependency_groups:
                for field_name, lag in (
                    ("minimumLagMinutes", group.minimum_lag_minutes),
                    ("maximumLagMinutes", group.maximum_lag_minutes),
                ):
                    if lag is not None and lag > 0:
                        observe(duration_microseconds(activity.activity_id, field_name, lag))
        for commitment in scenario.commitments:
            observe_instant(commitment.start)
            observe_instant(commitment.end)
        for day in scenario.days:
            for boundary in (day.date, day.date + timedelta(days=1)):
                observe_instant(datetime.combine(boundary, time.min, zone))
        return max(1, step)

    def ticks(self, microseconds: int) -> int:
        quotient, remainder = divmod(microseconds, self.step)
        if remainder:
            raise SolverRangeError(
                f"{microseconds} microseconds is not a multiple of the {self.step} microsecond "
                "resolution this scenario resolves to"
            )
        return quotient

    def to_microseconds(self, value: int) -> int:
        """A tick count back in the unit every published document reports."""
        return value * self.step

    def duration_ticks(self, activity_id: str, field_name: str, value: float) -> int:
        return self.ticks(duration_microseconds(activity_id, field_name, value))

    def to_tick(self, value: datetime) -> int:
        return self.ticks(timedelta_microseconds(value.astimezone(UTC) - self.origin))

    def to_datetime(self, value: int) -> datetime:
        return (self.origin + timedelta(microseconds=self.to_microseconds(value))).astimezone(
            self.zone
        )

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
        reported_activity_ids: set[str] | None = None,
    ) -> None:
        self.scenario = scenario
        self.axis = axis
        self.records = sorted(records, key=lambda item: item.activity.activity_id)
        self.fixed_schedule = fixed_schedule or {}
        self.excluded_fixed_activity_ids = excluded_fixed_activity_ids or set()
        self.default_start_anchors = default_start_anchors or {}
        self.forced_present_activity_ids = forced_present_activity_ids or set()
        # None keeps the whole-model objective the single-solve path has always reported.
        self.reported_activity_ids = reported_activity_ids
        self.model = cp_model.CpModel()
        self.variables: dict[str, ActivityVariables] = {}
        self.duration_deviations: list[cp_model.IntVar] = []
        self.temporal_deviations: list[cp_model.IntVar] = []
        self.effective_starts: list[cp_model.IntVar] = []
        # The same terms again, keyed by activity, so a caller solving one window of a horizon can
        # be told the objective of the days it keeps rather than of the days it looked at. Every
        # component is a sum over activities, so the restriction is exact.
        self.deviations_by_activity: dict[str, list[cp_model.IntVar]] = defaultdict(list)
        self.effective_start_by_activity: dict[str, cp_model.IntVar] = {}
        self.resident_ids = {item.resident_id for item in scenario.residents}
        self.probe_count = 0
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

        optional_requests = [
            LockRequest(
                variables.presence,
                1,
                f"canonical_optional__{variables.record.activity.activity_id}",
            )
            for variables in sorted(
                self.variables.values(),
                key=lambda item: item.record.activity.activity_id,
            )
            if not variables.record.activity.mandatory
        ]
        aborted = self._lock_requests(optional_requests)
        if aborted is not None:
            return self._not_optimal_outcome(*aborted)

        preference_requests: list[LockRequest] = []
        for variables in sorted(
            self.variables.values(),
            key=lambda item: (item.record.day_index, item.record.activity_index),
        ):
            activity = variables.record.activity
            if activity.duration is not None:
                preference_requests.append(
                    LockRequest(
                        variables.duration,
                        self.axis.duration_ticks(
                            activity.activity_id,
                            "preferredMinutes",
                            activity.duration.preferred_minutes,
                        ),
                        f"preferred_duration__{activity.activity_id}",
                        variables.presence,
                    )
                )
            if activity.start_window is not None:
                preference_requests.append(
                    LockRequest(
                        variables.start,
                        self.axis.to_tick(activity.start_window.preferred),
                        f"preferred_start__{activity.activity_id}",
                        variables.presence,
                    )
                )
            if activity.end_window is not None:
                preference_requests.append(
                    LockRequest(
                        variables.end,
                        self.axis.to_tick(activity.end_window.preferred),
                        f"preferred_end__{activity.activity_id}",
                        variables.presence,
                    )
                )
        aborted = self._lock_requests(preference_requests)
        if aborted is not None:
            return self._not_optimal_outcome(*aborted)

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
        objective_values = (
            self._restricted_objective(solver, self.reported_activity_ids)
            if self.reported_activity_ids is not None
            else ObjectiveValues(
                optional_priority_score=solver.value(objective_variables["optional_priority"]),
                optional_activity_count=solver.value(objective_variables["optional_count"]),
                # The model counts in ticks; every published number is in microseconds.
                duration_deviation_microseconds=self.axis.to_microseconds(
                    solver.value(objective_variables["duration_deviation"])
                ),
                temporal_deviation_microseconds=self.axis.to_microseconds(
                    solver.value(objective_variables["temporal_deviation"])
                ),
                scheduled_start_sum_microseconds=self.axis.to_microseconds(
                    solver.value(objective_variables["start_sum"])
                ),
            )
        )
        return SolveOutcome(
            status=solver.status_name(status),
            values=values,
            omitted_activity_ids=tuple(sorted(omitted)),
            objective_values=objective_values,
        )

    def _track(self, activity_id: str, deviation: cp_model.IntVar) -> cp_model.IntVar:
        """Record one objective term against its activity, and hand it back unchanged."""
        self.deviations_by_activity[activity_id].append(deviation)
        return deviation

    def _restricted_objective(
        self,
        solver: cp_model.CpSolver,
        activity_ids: set[str],
    ) -> ObjectiveValues:
        """The objective of ``activity_ids`` alone, read off the solved model.

        Used when a window was solved with one day of lookahead: that day shapes the night before
        it and must be in the model, but it belongs to the next window and would otherwise be
        counted twice. Every component is a sum over activities, so dropping its terms is exact.
        """
        priority = 0
        count = 0
        deviation = 0
        temporal = 0
        start_sum = 0
        for activity_id in sorted(activity_ids):
            variables = self.variables[activity_id]
            present = solver.value(variables.presence)
            if not variables.record.activity.mandatory and present:
                priority += variables.record.activity.priority
                count += 1
            start_sum += solver.value(self.effective_start_by_activity[activity_id])
        # The two deviation totals are kept apart by which list the model summed them into.
        duration_terms = {id(item) for item in self.duration_deviations}
        for activity_id in sorted(activity_ids):
            for term in self.deviations_by_activity.get(activity_id, ()):
                if id(term) in duration_terms:
                    deviation += solver.value(term)
                else:
                    temporal += solver.value(term)
        return ObjectiveValues(
            optional_priority_score=priority,
            optional_activity_count=count,
            duration_deviation_microseconds=self.axis.to_microseconds(deviation),
            temporal_deviation_microseconds=self.axis.to_microseconds(temporal),
            scheduled_start_sum_microseconds=self.axis.to_microseconds(start_sum),
        )

    def _declare_lock(self, request: LockRequest) -> cp_model.IntVar:
        lock = self.model.new_bool_var(f"lock__{request.name}")
        enforcement = [lock] if request.presence is None else [lock, request.presence]
        self.model.add(request.variable == request.target).only_enforce_if(enforcement)
        return lock

    def _decide_lock(
        self,
        lock: cp_model.IntVar,
        request: LockRequest,
    ) -> tuple[int, cp_model.CpSolver]:
        self.probe_count += 1
        if self.probe_count > MAX_FEASIBILITY_PROBES:
            raise CompilationBudgetError(self.probe_count, MAX_FEASIBILITY_PROBES)
        self.model.add_assumption(lock)
        solver = self._new_feasibility_solver()
        status = solver.solve(self.model)
        self.model.clear_assumptions()
        self.model.add(lock == (1 if status == cp_model.OPTIMAL else 0))
        if request.presence is None and status == cp_model.INFEASIBLE:
            self.model.add(request.variable != request.target)
        return status, solver

    def _lock_requests(
        self,
        requests: list[LockRequest],
    ) -> tuple[int, cp_model.CpSolver] | None:
        """Fix every request the sequential policy would fix, in the same order.

        A single solve settles the whole batch when the targets are jointly feasible: the
        sequential loop would then accept each of them in turn, having strictly fewer active
        constraints at every step. An unsatisfiable batch yields a conflict core; a core holding
        exactly one request proves that request infeasible on its own, so the sequential loop
        rejects it too regardless of what it had already fixed. Any larger core leaves the order
        undecided, and the first rejection is then located by bisection over the greedy prefix.

        Returns ``None`` once every request is decided, or the ``(status, solver)`` pair whose
        inconclusive status must abort the solve.
        """
        pending = [(self._declare_lock(request), request) for request in requests]
        while pending:
            status, solver = self._probe([lock for lock, _ in pending])
            if status == cp_model.OPTIMAL:
                for lock, _ in pending:
                    self.model.add(lock == 1)
                return None
            if status != cp_model.INFEASIBLE:
                return status, solver
            core = set(solver.sufficient_assumptions_for_infeasibility())
            conflicting = [item for item in pending if item[0].index in core]
            if len(conflicting) == 1:
                self._decide_lock(*conflicting[0])
                pending.remove(conflicting[0])
                continue
            # The core bounds where the first rejection can be: the prefix ending at its last
            # member is already unsatisfiable, so nothing past it needs searching. Collisions are
            # local — two activities of one evening — so this usually shrinks a search over
            # thousands of requests to one over a handful.
            positions = {item[0].index: position for position, item in enumerate(pending)}
            horizon = max(positions[item[0].index] for item in conflicting) + 1
            aborted = self._lock_by_bisection(pending, horizon)
            if aborted is not None:
                return aborted
            return None
        return None

    def _probe(self, locks: list[cp_model.IntVar]) -> tuple[int, cp_model.CpSolver]:
        self.probe_count += 1
        if self.probe_count > MAX_FEASIBILITY_PROBES:
            raise CompilationBudgetError(self.probe_count, MAX_FEASIBILITY_PROBES)
        for lock in locks:
            self.model.add_assumption(lock)
        solver = self._new_feasibility_solver()
        status = solver.solve(self.model)
        self.model.clear_assumptions()
        return status, solver

    def _lock_by_bisection(
        self,
        pending: list[tuple[cp_model.IntVar, LockRequest]],
        horizon: int | None = None,
    ) -> tuple[int, cp_model.CpSolver] | None:
        """Decide the remaining requests in greedy order, finding each rejection by bisection.

        The sequential loop is exact but pays one full solve per request. It is also unnecessary:
        the requests the loop accepts are exactly the longest prefix that is jointly feasible, so
        the only thing worth locating is where that prefix ends. Bisecting for it costs a
        logarithmic number of solves per rejection instead of a linear one, and accepts the whole
        prefix in a single step.

        Exactness follows from the same induction as the batch path. If `p_i..p_k` are jointly
        feasible with what is already fixed, the loop would have accepted every one of them, each
        step facing strictly fewer constraints than the conjunction. And `p_{k+1}` is rejected
        because the loop reaches it holding precisely that prefix.
        """
        index = 0
        while index < len(pending):
            remaining = pending[index:]
            status, solver = self._probe([lock for lock, _ in remaining])
            if status == cp_model.OPTIMAL:
                for lock, _ in remaining:
                    self.model.add(lock == 1)
                return None
            if status != cp_model.INFEASIBLE:
                return status, solver
            # Smallest `length` whose prefix is already unsatisfiable; the request it ends on is
            # the one the loop rejects. A caller-supplied conflict core bounds the first search.
            bound = len(remaining) if horizon is None else min(horizon - index, len(remaining))
            horizon = None
            low, high = 1, max(1, bound)
            while low < high:
                middle = (low + high) // 2
                status, solver = self._probe([lock for lock, _ in remaining[:middle]])
                if status == cp_model.INFEASIBLE:
                    high = middle
                elif status == cp_model.OPTIMAL:
                    low = middle + 1
                else:
                    return status, solver
            for lock, _ in remaining[: low - 1]:
                self.model.add(lock == 1)
            self._decide_lock(*remaining[low - 1])
            index += low
        return None

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

    def _new_feasibility_solver(self) -> cp_model.CpSolver:
        """Solver for value-fixing probes, whose only observable result is the status.

        Those probes discard their assignment, so these parameters cannot reach the canonical
        plan. The linear relaxation and probing only pay off when search has to backtrack, which
        never happens here: dropping them keeps long horizons conclusive within the frozen
        deterministic-time budget instead of exhausting it and reporting `UNKNOWN`.

        Presolve is dropped too once the axis is tight, and that condition is not decoration. There
        is no incremental solving: the value-fixing loop hands CP-SAT the same model thousands of
        times over — 13 183 on a five-month horizon — and presolves it from scratch every time. On
        a tight model that is the whole cost, since the probes settle by propagation with zero
        conflicts and zero branches. On a model whose variables span 10^11 microseconds it is the
        opposite: presolve is what keeps the search tractable, and removing it made one week of
        Marco's horizon four times *worse* (831s to 3 296s) where the tight axis with no presolve
        does it in 18s. So the two travel together, and a scenario that genuinely needs microsecond
        resolution keeps the presolve it depends on.
        """
        solver = self._new_solver()
        solver.parameters.linearization_level = 0
        solver.parameters.cp_model_probing_level = 0
        solver.parameters.max_deterministic_time = FEASIBILITY_DETERMINISTIC_TIME
        if self.axis.horizon <= PRESOLVE_FREE_HORIZON_TICKS:
            solver.parameters.cp_model_presolve = False
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
                duration_min = self.axis.duration_ticks(
                    activity_id,
                    "minimumMinutes",
                    activity.duration.minimum_minutes,
                )
                duration_max = self.axis.duration_ticks(
                    activity_id,
                    "maximumMinutes",
                    activity.duration.maximum_minutes,
                )
                preferred_duration = self.axis.duration_ticks(
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
                    self._track(
                        activity_id,
                        self._conditional_deviation(
                            duration,
                            preferred_duration,
                            presence,
                            f"duration_deviation__{activity_id}",
                        ),
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
                        self._track(
                            activity_id,
                            self._conditional_deviation(
                                duration,
                                preferred_duration,
                                presence,
                                f"duration_deviation__{activity_id}",
                            ),
                        )
                    )
                self.temporal_deviations.append(
                    self._track(
                        activity_id,
                        self._conditional_deviation(
                            end,
                            preferred_end,
                            presence,
                            f"end_deviation__{activity_id}",
                        ),
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
                    self._track(
                        activity_id,
                        self._conditional_deviation(
                            start,
                            preferred_start,
                            presence,
                            f"start_deviation__{activity_id}",
                        ),
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
            self.effective_start_by_activity[activity_id] = effective_start
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
                    self.axis.duration_ticks(
                        activity_id,
                        f"dependencyGroups[{group_index}].minimumLagMinutes",
                        group.minimum_lag_minutes,
                    )
                    if group.minimum_lag_minutes > 0
                    else 0
                )
                maximum_lag = (
                    self.axis.duration_ticks(
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
