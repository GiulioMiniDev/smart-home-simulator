"""Two away activities back to back are one outing: out of the door once, and back in once.

The authoring contract writes every away model as a round trip, a commute as its own commitment
before the shift and a night shift as two commitments either side of midnight. Executed as written,
a nurse went to work at 06:35, came back in through the front door at 07:02 and left again at 07:04,
and on a night shift came home at 00:10 for two minutes. Three mornings in a month the compiler also
put breakfast at home between the commute and the shift.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from smart_home_sim.domain.behavior import (
    PersonalProcessPackage,
    ProcessBinding,
    ProcessModel,
)
from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.domain.execution import ActivityExecution, ExecutionTrace
from smart_home_sim.domain.models import Resource, Scenario
from smart_home_sim.hybrid_planning.outline import FixedCommitment, HorizonOutline
from smart_home_sim.hybrid_planning.recurring_activities import Weekday
from smart_home_sim.simulation.service import simulate_bundle, validate_execution_trace
from tests.test_household_outing import _through_the_door
from tests.test_household_simulation import _RESIDENTS, _outline, _package, materialized_run

_ROOT = Path(__file__).parents[1]
_EARLY_TRAVEL = "luca_early_travel"
_EARLY_SHIFT = "luca_early_shift"
_NIGHT_BEFORE = "luca_night_before_midnight"
_NIGHT_AFTER = "luca_night_after_midnight"
_UNKNOWN_OBJECT = "yard_exercise_surface"


def _away_model(resident: str) -> ProcessModel:
    """Being at work as an authored bundle writes it, made into the round trip the contract asks."""
    package = json.loads(
        (_ROOT / "examples/authoring/nicoletta_palmi_horizon_bundle.json").read_text(
            encoding="utf-8"
        )
    )["personalProcessPackage"]
    model = next(
        item for item in package["processModels"] if item["processModelId"] == "pm_work_shift"
    )
    return _through_the_door(
        ProcessModel.model_validate_json(
            json.dumps(
                {**model, "processModelId": f"{resident}__work_shift", "residentId": resident}
            )
        )
    )


def _away_package() -> PersonalProcessPackage:
    package = _package()
    return package.model_copy(
        update={
            "process_models": [*package.process_models, *(_away_model(r) for r in _RESIDENTS)],
            "bindings": [
                *package.bindings,
                *(
                    ProcessBinding(
                        binding_id=f"{resident}__work_shift",
                        resident_id=resident,
                        intent="work_shift",
                        process_model_id=f"{resident}__work_shift",
                    )
                    for resident in _RESIDENTS
                ),
            ],
        }
    )


def _commuting_outline() -> HorizonOutline:
    """Luca's Tuesday: a short trip that ends when an early shift begins, and a night shift."""

    def commitment(commitment_id: str, start: str, end: str, weekday: Weekday) -> FixedCommitment:
        return FixedCommitment(
            commitment_id=commitment_id,
            label=commitment_id,
            weekdays=[weekday],
            start_time=start,
            end_time=end,
            intent="work_shift",
        )

    outline = _outline()
    residents = [
        resident.model_copy(
            update={
                "fixed_commitments": [
                    commitment(_EARLY_TRAVEL, "05:00", "05:30", Weekday.tuesday),
                    commitment(_EARLY_SHIFT, "05:30", "06:30", Weekday.tuesday),
                    commitment(_NIGHT_BEFORE, "23:00", "23:59", Weekday.tuesday),
                    commitment(_NIGHT_AFTER, "00:00", "01:00", Weekday.wednesday),
                ]
            }
        )
        if resident.resident_id == "luca"
        else resident
        for resident in outline.residents
    ]
    # An object of a type the vocabulary does not know, where the shifts happen. Such an object
    # offers every capability, and the Ferri outline's outdoor `exercise_surface` became the place a
    # nurse worked and a piece of furniture every meal preparation held.
    world = outline.world.model_copy(
        update={
            "resources": [
                *outline.world.resources,
                Resource(
                    resource_id=_UNKNOWN_OBJECT,
                    resource_type="exercise_surface",
                    location_id="outdoors",
                    capacity=2,
                ),
            ]
        }
    )
    return HorizonOutline.model_validate_json(
        outline.model_copy(update={"residents": residents, "world": world}).model_dump_json(
            by_alias=True
        )
    )


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return materialized_run(
        _commuting_outline(), tmp_path_factory.mktemp("commuting"), _away_package()
    )


@pytest.fixture(scope="module")
def trace(run: Path) -> ExecutionTrace:
    return ExecutionTrace.model_validate_json(
        (run / "execution-trace.json").read_text(encoding="utf-8")
    )


def _labelled(executions: list[ActivityExecution], commitment_id: str) -> ActivityExecution:
    return next(
        item for item in executions if item.source_activity_id.endswith(f"_{commitment_id}")
    )


def _crossings(trace: ExecutionTrace, execution: ActivityExecution) -> list[str]:
    return [
        item.action_type
        for item in sorted(trace.action_executions, key=lambda row: row.started_at)
        if item.activity_execution_id == execution.activity_execution_id
        and item.action_type in {"leave_home", "enter_home"}
    ]


def test_a_commitment_that_ends_when_another_begins_is_followed_by_it(run: Path) -> None:
    """Nothing is planned in between: the shift starts on the minute the trip ends."""
    scenario = Scenario.model_validate_json((run / "scenario.json").read_text(encoding="utf-8"))
    activities = {item.activity_id: item for day in scenario.days for item in day.activities}
    travel = next(key for key in activities if key.endswith(f"_{_EARLY_TRAVEL}"))
    shift = activities[next(key for key in activities if key.endswith(f"_{_EARLY_SHIFT}"))]
    assert [
        (group.activity_ids, group.maximum_lag_minutes) for group in shift.dependency_groups
    ] == [([travel], 0)]

    plan = json.loads((run / "canonical-plan.json").read_text(encoding="utf-8"))
    scheduled = {
        item["sourceActivityId"]: item for day in plan["days"] for item in day["activities"]
    }
    assert scheduled[shift.activity_id]["scheduledStart"] == scheduled[travel]["scheduledEnd"]


def test_back_to_back_away_activities_cross_the_door_once_each_way(trace: ExecutionTrace) -> None:
    travel = _labelled(trace.activity_executions, _EARLY_TRAVEL)
    shift = _labelled(trace.activity_executions, _EARLY_SHIFT)

    assert _crossings(trace, travel) == ["leave_home"]
    assert _crossings(trace, shift) == ["enter_home"]
    at_home = [
        item.value
        for item in sorted(trace.state_transitions, key=lambda row: row.at)
        if item.subject_id == "luca"
        and item.fact == "at_home"
        and travel.actual_start <= item.at <= shift.actual_end
    ]
    assert at_home == [False, True]


def _night_bundle(run: Path, *, filler_between: bool) -> SimulationBundle:
    """The run's bundle with the half after midnight mandatory, as it is on any day but the last.

    The fixture's second day is the truncatable one, so everything on it is optional; an optional
    second half is exactly what the engine refuses to join, since it may never bring her home.
    With `filler_between`, one of luca's own optional activities is moved to just before the second
    half, so it comes due while he is out.
    """
    bundle = SimulationBundle.model_validate_json(
        (run / "simulation-bundle.json").read_text(encoding="utf-8")
    )
    plan = bundle.canonical_plan.model_copy(deep=True)
    activities = [item for day in plan.days for item in day.activities]
    before = next(item for item in activities if item.source_activity_id.endswith(_NIGHT_BEFORE))
    after = next(item for item in activities if item.source_activity_id.endswith(_NIGHT_AFTER))
    after.mandatory = True
    if filler_between:
        filler = next(
            item
            for item in activities
            if item.actor_id == "luca"
            and not item.mandatory
            and not item.participant_ids
            and item.scheduled_start < before.scheduled_start
        )
        # Just before the second half is due: the compiler usually leaves no gap at all.
        start = after.scheduled_start - timedelta(seconds=30)
        filler.scheduled_start = start
        filler.scheduled_end = start + timedelta(microseconds=filler.duration_microseconds)
    return bundle.model_copy(update={"canonical_plan": plan})


def test_a_night_shift_either_side_of_midnight_is_one_night_out(run: Path) -> None:
    bundle = _night_bundle(run, filler_between=False)
    result = simulate_bundle(bundle)
    assert result.report.success, result.report.issues
    assert result.trace is not None
    assert not validate_execution_trace(result.trace, bundle)

    before = _labelled(result.trace.activity_executions, _NIGHT_BEFORE)
    after = _labelled(result.trace.activity_executions, _NIGHT_AFTER)
    assert _crossings(result.trace, before) == ["leave_home"]
    assert _crossings(result.trace, after) == ["enter_home"]


def test_nothing_at_home_happens_while_she_is_between_two_halves(run: Path) -> None:
    """An optional activity due in the gap is given up, not walked home to through the street."""
    bundle = _night_bundle(run, filler_between=True)
    result = simulate_bundle(bundle)
    assert result.report.success, result.report.issues
    assert result.trace is not None

    dropped = [
        item
        for item in result.trace.plan_deviations
        if item.cause_id == "resident_away" and item.kind == "optional_dropped"
    ]
    assert len(dropped) == 1
    after = _labelled(result.trace.activity_executions, _NIGHT_AFTER)
    assert _crossings(result.trace, after) == ["enter_home"]


def test_an_object_of_no_known_type_is_nobody_s_workplace(run: Path, trace: ExecutionTrace) -> None:
    """The room's own service point answers before it, and no activity is planned as holding it."""
    scenario = Scenario.model_validate_json((run / "scenario.json").read_text(encoding="utf-8"))
    held = {
        requirement.resource_id
        for day in scenario.days
        for activity in day.activities
        for requirement in activity.required_resources
    }
    assert _UNKNOWN_OBJECT not in held
    shifts = {
        item.activity_execution_id
        for item in trace.activity_executions
        if item.intent == "work_shift" and item.status != "dropped"
    }
    work = [
        item
        for item in trace.action_executions
        if item.activity_execution_id in shifts and item.action_type == "perform_work"
    ]
    assert work
    assert all(_UNKNOWN_OBJECT not in item.provider_ids for item in work)
