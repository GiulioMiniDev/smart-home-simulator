"""A weekday the shared dinner does not fit: they eat separately, and the answer sheet says so.

Luca works until half past seven and Marco has a class from a quarter to eight, so on a working day
they have fifteen minutes in common inside the dinner band. The household declares that a dinner
shorter than fifty minutes is not a shared one. The compiler is the only layer that knows the
day's slack, and it takes the separate arm; the run executes two ordinary dinners; and the habit
ground truth, measured on that run, describes two dinners and no shared episode — which is the
whole of what "the ground truth is always true" has to mean on the day that is hardest to get right.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

from smart_home_sim.domain.behavior import ProcessBinding, ProcessModel
from smart_home_sim.domain.execution import ExecutionTrace
from smart_home_sim.domain.materialization import SensorDeploymentPolicy
from smart_home_sim.domain.models import Scenario, SimulationWindow
from smart_home_sim.hybrid_planning.expander import expand_outline
from smart_home_sim.hybrid_planning.habits import ground_truth_of_run
from smart_home_sim.hybrid_planning.outline import FixedCommitment, HorizonOutline, Household
from smart_home_sim.hybrid_planning.recurring_activities import Weekday
from smart_home_sim.materialization import materialize_workspace
from tests.test_household_simulation import _RESIDENTS, _outline, _package

_ROOT = Path(__file__).parents[1]
_WORKDAYS = [Weekday.monday, Weekday.tuesday, Weekday.wednesday, Weekday.thursday, Weekday.friday]
_FLOOR = 50


def _away_model(resident: str) -> ProcessModel:
    """Being at work, as an authored bundle writes it: go out, stay on your feet, work."""
    package = json.loads(
        (_ROOT / "examples/authoring/nicoletta_palmi_horizon_bundle.json").read_text(
            encoding="utf-8"
        )
    )["personalProcessPackage"]
    model = next(
        item for item in package["processModels"] if item["processModelId"] == "pm_work_shift"
    )
    return ProcessModel.model_validate_json(
        json.dumps({**model, "processModelId": f"{resident}__work_shift", "residentId": resident})
    )


def _squeezed_outline() -> HorizonOutline:
    outline = _outline()
    commitments = {
        "luca": FixedCommitment(
            commitment_id="luca_shift",
            label="Shift",
            intent="work_shift",
            weekdays=_WORKDAYS,
            start_time="13:00",
            end_time="19:30",
        ),
        "marco": FixedCommitment(
            commitment_id="marco_class",
            label="Class",
            intent="work_shift",
            weekdays=_WORKDAYS,
            start_time="19:45",
            end_time="22:30",
        ),
    }
    residents = []
    for resident in outline.residents:
        profile = resident.profile
        if resident.resident_id == "luca":
            # His afternoon belongs to the shift, so the habits he had there move to the morning.
            profile = profile.model_copy(
                update={
                    "recurring_activities": [
                        item.model_copy(
                            update={
                                "cadence": item.cadence.model_copy(
                                    update={"window_start": "09:00", "window_end": "12:30"}
                                )
                            }
                        )
                        if "12:00" <= item.cadence.window_start < "19:00"
                        else item
                        for item in profile.recurring_activities
                    ]
                }
            )
        residents.append(
            resident.model_copy(
                update={
                    "profile": profile,
                    "fixed_commitments": [commitments[resident.resident_id]],
                }
            )
        )
    dinner = next(
        item for item in outline.household.joint_activities if item.activity.intent == "eat_dinner"
    )
    outline = outline.model_copy(
        update={
            "residents": residents,
            "household": Household(
                relations=outline.household.relations,
                joint_activities=[dinner.model_copy(update={"minimum_shared_minutes": _FLOOR})],
            ),
        }
    )
    return HorizonOutline.model_validate_json(outline.model_dump_json(by_alias=True))


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    package = _package()
    package = package.model_copy(
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
    scenario = expand_outline(_squeezed_outline(), package, seed=1).bundle.scenario
    days = scenario.days[:2]
    days = [
        days[0],
        days[1].model_copy(
            update={
                "activities": [
                    item.model_copy(update={"allow_boundary_truncation": True, "mandatory": False})
                    for item in days[1].activities
                ]
            }
        ),
    ]
    tz = days[0].activities[0].start_window.preferred.tzinfo  # type: ignore[union-attr]
    window = SimulationWindow(
        start=datetime.combine(days[0].date, time.min, tz),
        end=datetime.combine(days[-1].date + timedelta(days=1), time.min, tz),
    )
    scenario = scenario.model_copy(
        update={
            "days": days,
            "simulation_window": window,
            "initial_state": scenario.initial_state.model_copy(update={"at": window.start}),
        }
    )
    root = tmp_path_factory.mktemp("squeezed")
    (root / "scenario.json").write_text(scenario.model_dump_json(by_alias=True), encoding="utf-8")
    (root / "package.json").write_text(package.model_dump_json(by_alias=True), encoding="utf-8")
    materialize_workspace(
        root / "scenario.json",
        root / "package.json",
        root / "run",
        sensor_policy=SensorDeploymentPolicy.realistic(),
    )
    return root / "run"


def test_on_a_day_the_shared_dinner_does_not_fit_they_eat_separately(run: Path) -> None:
    trace = ExecutionTrace.model_validate_json(
        (run / "execution-trace.json").read_text(encoding="utf-8")
    )
    first_day = trace.started_at.date()
    dinners = [
        item
        for item in trace.activity_executions
        if item.intent == "eat_dinner"
        and item.status != "dropped"
        and item.actual_start.date() == first_day
    ]

    assert sorted(item.actor_id for item in dinners) == list(_RESIDENTS)
    assert all(not item.participant_ids for item in dinners)


def test_the_answer_sheet_describes_the_separate_dinners_it_measured(run: Path) -> None:
    """No shared episode that did not happen, and each dinner in its own resident's evening."""
    trace = ExecutionTrace.model_validate_json(
        (run / "execution-trace.json").read_text(encoding="utf-8")
    )
    scenario = Scenario.model_validate_json((run / "scenario.json").read_text(encoding="utf-8"))
    measured = ground_truth_of_run(scenario, trace)
    assert measured is not None
    habits, household = measured
    first_day = trace.started_at.date()

    assert [
        item
        for item in household.shared_episodes
        if item.intent == "eat_dinner" and item.day == first_day
    ] == []
    for document in habits:
        evening = next(
            band for band in document.habits if band.habit_id == f"evening_{document.resident_id}"
        )
        assert "eat_dinner" in {row.intent for row in evening.composition}
