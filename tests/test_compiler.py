from __future__ import annotations

import copy
import json
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.compiler import compile_file, compile_payload
from smart_home_sim.compiler import service as compiler_service
from smart_home_sim.compiler.issues import compilation_issue
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.compiler.solver import (
    MICROSECONDS_PER_MINUTE,
    SolveOutcome,
    TimeAxis,
    activity_records,
)
from smart_home_sim.domain.compilation import COMPILATION_ISSUE_CODES
from smart_home_sim.domain.models import (
    BRANCH_EXTENSION,
    PRIVACY_EXTENSION,
    DependencyGroup,
    Scenario,
)

PROJECT_ROOT = Path(__file__).parents[1]
EXAMPLES = PROJECT_ROOT / "examples"


def _payload(name: str = "minimal.json") -> dict[str, Any]:
    return json.loads((EXAMPLES / "valid" / name).read_text(encoding="utf-8"))


def _activities(plan: Any) -> list[Any]:
    return [activity for day in plan.days for activity in day.activities]


def _add_fallback(
    payload: dict[str, Any],
    *,
    duration_minutes: float = 10.0,
) -> dict[str, Any]:
    fallback = copy.deepcopy(payload["days"][0]["activities"][1])
    fallback.update(
        {
            "activityId": "fallback_2",
            "activation": {
                "mode": "fallback",
                "fallbackForActivityId": "activity_2",
                "fallbackTrigger": "precondition_failed",
            },
            "dependencyGroups": [],
            "duration": {
                "minimumMinutes": duration_minutes,
                "preferredMinutes": duration_minutes,
                "maximumMinutes": duration_minutes,
            },
        }
    )
    fallback.pop("startWindow", None)
    payload["days"][0]["activities"].append(fallback)
    return fallback


def test_minimal_scenario_compiles_deterministically() -> None:
    payload = _payload()
    first = compile_payload(payload)
    second = compile_payload(copy.deepcopy(payload))

    assert first.report.success
    assert first.report.solver_status == "OPTIMAL"
    assert first.plan is not None
    assert first.plan.model_dump_json(by_alias=True) == second.plan.model_dump_json(by_alias=True)
    assert first.report == second.report
    assert first.report.canonical_plan_sha256 == canonical_sha256(first.plan)
    assert [item.source_activity_id for item in _activities(first.plan)] == [
        "activity_1",
        "activity_2",
    ]


def test_full_week_compiles_and_matches_frozen_example() -> None:
    result = compile_file(EXAMPLES / "valid/mario_week.json")
    expected_plan = (EXAMPLES / "compiled/mario_week.plan.json").read_text(encoding="utf-8")
    expected_report = (EXAMPLES / "compiled/mario_week.compilation-report.json").read_text(
        encoding="utf-8"
    )

    assert result.plan is not None
    assert result.plan.model_dump_json(by_alias=True, indent=2) + "\n" == expected_plan
    assert result.report.model_dump_json(by_alias=True, indent=2) + "\n" == expected_report
    assert result.report.summary.scheduled_activity_count == 169
    assert result.report.summary.contingency_count == 3
    assert result.report.summary.contingency_activity_count == 4
    assert result.report.summary.rescheduled_activity_count == 3


def test_week_main_plan_respects_resident_and_resource_capacity() -> None:
    payload = _payload("mario_week.json")
    result = compile_payload(payload)
    assert result.plan is not None
    resident_ids = {item["residentId"] for item in payload["residents"]}
    activities = _activities(result.plan)

    occupied: dict[str, list[Any]] = defaultdict(list)
    for activity in activities:
        residents = set(activity.participant_ids) & resident_ids
        if not activity.can_overlap_for_actor:
            residents.add(activity.actor_id)
        for resident_id in residents:
            occupied[resident_id].append(activity)
    for resident_activities in occupied.values():
        ordered = sorted(resident_activities, key=lambda item: item.scheduled_start)
        assert all(
            first.scheduled_end <= second.scheduled_start
            for first, second in zip(ordered, ordered[1:], strict=False)
        )

    capacities = {item["resourceId"]: item["capacity"] for item in payload["resources"]}
    for resource_id, capacity in capacities.items():
        events: list[tuple[datetime, int]] = []
        for activity in activities:
            for requirement in activity.required_resources:
                if requirement.resource_id == resource_id:
                    events.extend(
                        [
                            (activity.scheduled_start, requirement.units),
                            (activity.scheduled_end, -requirement.units),
                        ]
                    )
        used = 0
        for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
            used += delta
            assert 0 <= used <= capacity


def test_week_dependencies_commitments_and_fallback_patch_are_materialized() -> None:
    payload = _payload("mario_week.json")
    result = compile_payload(payload)
    assert result.plan is not None
    by_id = {item.source_activity_id: item for item in _activities(result.plan)}
    source = {item["activityId"]: item for day in payload["days"] for item in day["activities"]}
    for activity in by_id.values():
        for predecessor_id in activity.selected_dependency_ids:
            assert by_id[predecessor_id].scheduled_end <= activity.scheduled_start
        original = source[activity.source_activity_id]
        if commitment_id := original.get("commitmentId"):
            commitment = next(
                item for item in payload["commitments"] if item["commitmentId"] == commitment_id
            )
            assert activity.scheduled_start == datetime.fromisoformat(commitment["start"])
            assert activity.scheduled_end == datetime.fromisoformat(commitment["end"])

    contingencies = [item for day in result.plan.days for item in day.contingencies]
    dinner = next(item for item in contingencies if item.replaces_activity_id == "d2_a18")
    assert [item.source_activity_id for item in dinner.activities] == ["d2_alt04"]
    assert [item.source_activity_id for item in dinner.rescheduled_activities] == [
        "d2_a19",
        "d2_a20",
        "d2_a21",
    ]
    assert dinner.rescheduled_activities[0].selected_dependency_ids == ["d2_alt04"]


def test_invalid_input_is_rejected_before_scheduling() -> None:
    result = compile_file(EXAMPLES / "invalid/unknown_references.json")

    assert result.plan is None
    assert result.report.issues[0].code == "INPUT_SCENARIO_INVALID"
    assert result.report.solver_status is None


def test_infeasible_valid_scenario_has_stable_failure() -> None:
    payload = _payload("mario_week.json")
    payload["commitments"][0]["start"] = "2026-10-12T08:00:00+02:00"
    result = compile_payload(payload)

    assert result.plan is None
    assert result.report.solver_status == "INFEASIBLE"
    assert result.report.issues[0].code == "MAIN_PLAN_INFEASIBLE"


def test_cross_branch_dependency_is_rejected_in_preflight() -> None:
    payload = _payload()
    second = payload["days"][0]["activities"][1]
    second["activation"] = {
        "mode": "conditional",
        "condition": {"fact": "rain", "operator": "truthy"},
    }
    third = copy.deepcopy(second)
    third["activityId"] = "activity_3"
    third["activation"]["condition"]["fact"] = "visitor_present"
    third["startWindow"] = {
        "earliest": "2026-10-12T08:50:00+02:00",
        "preferred": "2026-10-12T08:55:00+02:00",
        "latest": "2026-10-12T09:00:00+02:00",
    }
    third["dependencyGroups"] = [{"mode": "all", "activityIds": ["activity_2"]}]
    payload["days"][0]["activities"].append(third)
    result = compile_payload(payload)

    assert result.plan is None
    assert result.report.issues[0].code == "CROSS_BRANCH_DEPENDENCY"


def test_unrepresentable_submicrosecond_duration_is_rejected() -> None:
    payload = _payload()
    payload["days"][0]["activities"][1]["duration"] = {
        "minimumMinutes": 0.000000001,
        "preferredMinutes": 0.000000001,
        "maximumMinutes": 0.000000001,
    }
    result = compile_payload(payload)

    assert result.plan is None
    assert result.report.issues[0].code == "TIME_PRECISION_UNREPRESENTABLE"


def test_source_digest_is_based_on_canonical_scenario_not_file_whitespace(
    tmp_path: Path,
) -> None:
    payload = _payload()
    compact = tmp_path / "compact.json"
    pretty = tmp_path / "pretty.json"
    compact.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    pretty.write_text(json.dumps(payload, indent=4), encoding="utf-8")

    first = compile_file(compact)
    second = compile_file(pretty)

    assert first.plan is not None and second.plan is not None
    assert first.plan.source_scenario_sha256 == second.plan.source_scenario_sha256
    scenario = Scenario.model_validate_json(compact.read_text())
    assert first.plan.source_scenario_sha256 == canonical_sha256(scenario)


def test_inactive_fallback_is_reported_as_a_warning() -> None:
    payload = _payload()
    target = payload["days"][0]["activities"][1]
    target["startWindow"] = {
        "earliest": "2026-10-12T08:35:00+02:00",
        "preferred": "2026-10-12T08:35:30+02:00",
        "latest": "2026-10-12T08:36:00+02:00",
    }
    target["duration"] = {
        "minimumMinutes": 10.0,
        "preferredMinutes": 10.0,
        "maximumMinutes": 10.0,
    }
    competitor = copy.deepcopy(target)
    competitor["activityId"] = "activity_3"
    competitor["priority"] = 100
    payload["days"][0]["activities"].append(competitor)
    _add_fallback(payload)

    result = compile_payload(payload)

    assert result.plan is not None
    assert result.report.issues[0].code == "CONTINGENCY_TARGET_NOT_SCHEDULED"
    assert result.report.issues[0].severity == "warning"


def test_infeasible_contingency_prevents_partial_plan() -> None:
    payload = _payload()
    fallback = _add_fallback(payload, duration_minutes=1000.0)
    fallback["mandatory"] = True

    result = compile_payload(payload)

    assert result.plan is None
    assert result.report.issues[0].code == "CONTINGENCY_PLAN_INFEASIBLE"


def test_oversized_aggregate_horizon_is_rejected() -> None:
    payload = _payload()
    payload["simulationWindow"]["end"] = "9999-12-31T00:00:00+01:00"
    payload["materializationPolicy"] = {"requireEveryDate": False}
    template = payload["days"][0]["activities"][1]
    for number in range(3, 7):
        activity = copy.deepcopy(template)
        activity["activityId"] = f"activity_{number}"
        payload["days"][0]["activities"].append(activity)

    result = compile_payload(payload)

    assert result.plan is None
    assert result.report.issues[0].code == "HORIZON_EXCEEDS_SOLVER_RANGE"


@pytest.mark.parametrize(
    ("failure", "status", "expected_code", "model_error"),
    [
        ("model_invalid", "MODEL_INVALID", "SOLVER_MODEL_INVALID", "invalid model"),
        ("not_optimal", "UNKNOWN", "SOLVER_NOT_OPTIMAL", None),
    ],
)
def test_solver_failures_have_public_issue_codes(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    status: str,
    expected_code: str,
    model_error: str | None,
) -> None:
    outcome = SolveOutcome(
        status=status,
        values={},
        omitted_activity_ids=(),
        objective_values=None,
        failure=failure,  # type: ignore[arg-type]
        model_error=model_error,
    )
    monkeypatch.setattr(compiler_service.ScheduleSolver, "solve", lambda _: outcome)

    result = compile_payload(_payload())

    assert result.plan is None
    assert result.report.issues[0].code == expected_code


def test_invalid_generated_plan_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = compiler_service._build_plan

    def invalid_plan(*args: Any, **kwargs: Any) -> Any:
        plan = original(*args, **kwargs)
        return plan.model_copy(update={"source_scenario_sha256": "invalid"})

    monkeypatch.setattr(compiler_service, "_build_plan", invalid_plan)

    result = compile_payload(_payload())

    assert result.plan is None
    assert result.report.issues[0].code == "CANONICAL_PLAN_INVALID"


def test_compilation_issue_registry_is_closed() -> None:
    assert {
        "CANONICAL_PLAN_INVALID",
        "COMPILATION_BUDGET_EXCEEDED",
        "CONTINGENCY_PLAN_INFEASIBLE",
        "CONTINGENCY_TARGET_NOT_SCHEDULED",
        "CROSS_BRANCH_DEPENDENCY",
        "HORIZON_EXCEEDS_SOLVER_RANGE",
        "INPUT_SCENARIO_INVALID",
        "MAIN_PLAN_INFEASIBLE",
        "SOLVER_MODEL_INVALID",
        "SOLVER_NOT_OPTIMAL",
        "TIME_PRECISION_UNREPRESENTABLE",
    } == COMPILATION_ISSUE_CODES
    with pytest.raises(ValueError, match="Unregistered compilation issue code"):
        compilation_issue("UNKNOWN", "input", "$", "unknown")


def test_compilation_budget_turns_a_runaway_into_a_readable_error(monkeypatch) -> None:
    """The defect this guards is silence, not a wrong plan.

    The eight-month bundle that started this work needed 7 740 feasibility probes and produced no
    error, no progress and no answer for thirteen hours: `MAX_DETERMINISTIC_TIME` bounds one probe
    and every probe was individually quick. Only a budget on their total can see that, so the
    budget is squeezed here to a value the smallest real scenario passes.
    """
    from smart_home_sim.compiler import solver as solver_module

    monkeypatch.setattr(solver_module, "MAX_FEASIBILITY_PROBES", 1)
    payload = _payload()

    result = compile_payload(payload)

    assert result.plan is None
    issue = next(
        item for item in result.report.issues if item.code == "COMPILATION_BUDGET_EXCEEDED"
    )
    assert issue.details["budget"] == 1
    assert issue.details["dayCount"] == len(payload["days"])
    assert "Shorten the horizon" in issue.message


def _mutually_exclusive_preferences() -> dict[str, Any]:
    """Two activities that each fit their preferred moment alone, but never together.

    Both are mandatory, belong to the same resident and want the same hour with room to move.
    Non-overlap therefore makes the pair infeasible while either one on its own is fine, which is
    exactly the shape that yields a conflict core of size two.
    """
    payload = _payload()
    template = copy.deepcopy(payload["days"][0]["activities"][1])
    window = {
        "earliest": "2026-10-12T09:00:00+02:00",
        "preferred": "2026-10-12T10:00:00+02:00",
        "latest": "2026-10-12T12:00:00+02:00",
    }
    duration = {"minimumMinutes": 60.0, "preferredMinutes": 60.0, "maximumMinutes": 60.0}
    activities = []
    for index, activity_id in enumerate(("clash_first", "clash_second")):
        activity = copy.deepcopy(template)
        activity.update(
            {
                "activityId": activity_id,
                "startWindow": copy.deepcopy(window),
                "duration": copy.deepcopy(duration),
                "mandatory": True,
                "canOverlapForActor": False,
                "dependencyGroups": [],
                "activation": {"mode": "always"},
            }
        )
        activity.pop("endWindow", None)
        activities.append(activity)
        assert index < 2
    payload["days"][0]["activities"] = activities
    # The stock example pins a runtime event and a commitment to the activities just replaced.
    payload["runtimeEventCandidates"] = []
    payload["commitments"] = []
    return payload


def test_a_non_singleton_conflict_core_falls_to_bisection_and_keeps_the_policy(
    monkeypatch,
) -> None:
    """The batch path cannot decide a mutual conflict; the order must, and this proves it does.

    With both targets asserted the core names them both, and nothing in it says which one the
    sequential policy would have kept. The bisection resolves that by finding where the feasible
    prefix ends, so the earlier activity keeps its preferred moment and the later one yields —
    which is what the frozen `priority-preference-1.0.0` order means.
    """
    from smart_home_sim.compiler import solver as solver_module

    taken: list[int] = []
    original = solver_module.ScheduleSolver._lock_by_bisection

    def spy(self, pending, horizon=None):  # type: ignore[no-untyped-def]
        taken.append(len(pending))
        return original(self, pending, horizon)

    monkeypatch.setattr(solver_module.ScheduleSolver, "_lock_by_bisection", spy)

    result = compile_payload(_mutually_exclusive_preferences())

    assert result.plan is not None, [issue.code for issue in result.report.issues]
    assert taken, "a mutual conflict must reach the bisection branch"
    scheduled = {
        activity.source_activity_id: activity.scheduled_start
        for activity in _activities(result.plan)
    }
    preferred = datetime.fromisoformat("2026-10-12T10:00:00+02:00")
    assert scheduled["clash_first"] == preferred
    assert scheduled["clash_second"] != preferred
    # The two must not overlap, which is the constraint that made them exclusive to begin with.
    assert abs((scheduled["clash_second"] - preferred).total_seconds()) >= 3600


def test_window_split_reproduces_the_single_solve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Splitting the horizon is an optimisation, so it may not change the plan.

    Canonicalisation costs one solve of the whole model per value it fixes, which makes an eight
    month import quadratic in the horizon and unusable. Solving a few days at a time removes the
    horizon from the per-solve cost — but only if the answer is the one the single solve would
    have given, since the plan hash is what every downstream guarantee is anchored to.

    `mario_week` carries 122 dependencies and every one of them stays inside its day, so the split
    accepts it on the real path and the guard no longer has to be lifted to test the equivalence.
    """
    monkeypatch.setattr(compiler_service, "COMPILATION_WINDOW_THRESHOLD_DAYS", 10_000)
    whole = compile_file(EXAMPLES / "valid/mario_week.json")

    monkeypatch.setattr(compiler_service, "COMPILATION_WINDOW_THRESHOLD_DAYS", 0)
    monkeypatch.setattr(compiler_service, "COMPILATION_WINDOW_DAYS", 2)
    windowed = compile_file(EXAMPLES / "valid/mario_week.json")

    assert whole.plan is not None
    assert windowed.plan is not None
    assert windowed.plan.model_dump_json(by_alias=True) == whole.plan.model_dump_json(by_alias=True)
    assert windowed.report.canonical_plan_sha256 == whole.report.canonical_plan_sha256


def test_a_scenario_whose_dependencies_stay_in_their_day_is_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dependency inside one day cannot reach outside the window that day belongs to.

    This is the case that matters, because it is the only kind the generator emits — a meal
    waiting for the cooking that same evening. Refusing the split for it sent a five-month import
    down the single-solve path the windows exist to avoid: one undivided solve, hours long, with
    no progress to report while it ran.
    """
    monkeypatch.setattr(compiler_service, "COMPILATION_WINDOW_THRESHOLD_DAYS", 0)
    calls: list[int] = []
    original = compiler_service._solve_in_windows

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(compiler_service, "_solve_in_windows", counting)
    result = compile_file(EXAMPLES / "valid/mario_week.json")

    assert result.plan is not None
    assert calls == [1]


def test_a_dependency_that_leaves_its_day_refuses_the_split() -> None:
    """The unsafe shape is still refused, and it is the crossing that makes it unsafe.

    A predecessor in a window that has not been solved yet would see its successor silently
    dropped rather than scheduled, so one reference out of 122 is enough to take the whole
    scenario back to the single solve.
    """
    scenario = Scenario.model_validate_json(
        json.dumps(_payload("mario_week.json"), separators=(",", ":"))
    )
    records = activity_records(scenario)
    assert compiler_service._windows_are_safe(records)

    first_day = next(record for record in records if record.day_index == 0)
    later = next(record for record in records if record.day_index > 0)
    crossed = later.activity.model_copy(
        update={
            "dependency_groups": [DependencyGroup(activity_ids=[first_day.activity.activity_id])]
        }
    )
    mutated = [
        replace(record, activity=crossed) if record is later else record for record in records
    ]

    assert not compiler_service._windows_are_safe(mutated)


def test_an_infeasible_horizon_names_the_day_that_cannot_be_scheduled() -> None:
    """ "The scheduling constraints are infeasible" over 243 days is not actionable.

    The offending date has had to be located by hand twice, both times one day out of an eight-month
    horizon where a long absence and the meals it forgot to displace were required at once. A day
    that fails in isolation fails inside any horizon containing it, so the compiler can say which.
    """
    payload = _payload()
    original = payload["days"][0]["activities"][0]
    clash = copy.deepcopy(original)
    clash["activityId"] = "clashing_activity"
    # A window it can move inside, so scenario validation cannot call it a fixed overlap, and yet
    # nowhere in that window is free: the first activity occupies all of it.
    earliest = datetime.fromisoformat(original["startWindow"]["earliest"])
    clash["startWindow"] = {
        "earliest": earliest.isoformat(),
        "preferred": (earliest + timedelta(minutes=10)).isoformat(),
        "latest": (earliest + timedelta(minutes=20)).isoformat(),
    }
    clash["requiredResources"] = []
    payload["days"][0]["activities"].append(clash)

    result = compile_payload(payload)

    assert result.plan is None
    infeasible = [item for item in result.report.issues if item.code == "MAIN_PLAN_INFEASIBLE"]
    assert len(infeasible) == 1
    assert infeasible[0].details["infeasibleDate"] == payload["days"][0]["date"]
    assert "cannot be scheduled even on its own" in infeasible[0].message
    assert {item["activityId"] for item in infeasible[0].details["mandatoryActivities"]} >= {
        "clashing_activity"
    }


def test_the_time_axis_resolves_to_what_the_scenario_actually_declares() -> None:
    """The solver's unit of time is derived from the document, and no plan depends on it.

    Instants used to become integers in microseconds regardless of what the scenario said, so a
    horizon written entirely in whole minutes gave CP-SAT start variables with sixty million times
    more values than it could ever use. That is free while propagation settles a day on its own, and
    ruinous where it does not: one week of a five-month horizon cost 714 seconds against 25 for its
    neighbours. The resolution is now the greatest common divisor of everything the scenario
    declares, which is exactly the coarsest unit that loses nothing.
    """
    payload = _payload()
    scenario = Scenario.model_validate_json(json.dumps(payload))
    axis = TimeAxis.from_scenario(scenario, activity_records(scenario))
    # This example is written entirely in five-minute steps, and the axis says so: 294 ticks stand
    # in for the 88 200 000 000 microseconds the same horizon used to be measured in.
    assert axis.step == 5 * MICROSECONDS_PER_MINUTE
    assert axis.horizon == 294

    # Round-tripping through the axis has to be exact, or a scheduled instant would drift.
    for day in scenario.days:
        for activity in day.activities:
            if activity.start_window is not None:
                moment = activity.start_window.preferred
                assert axis.to_datetime(axis.to_tick(moment)) == moment

    # A scenario that needs a finer unit gets one rather than being rounded into the coarse one.
    finer = copy.deepcopy(payload)
    finer["days"][0]["activities"][0]["duration"]["minimumMinutes"] = 0.5
    finer_scenario = Scenario.model_validate_json(json.dumps(finer))
    finer_axis = TimeAxis.from_scenario(finer_scenario, activity_records(finer_scenario))
    assert finer_axis.step == MICROSECONDS_PER_MINUTE // 2

    # And the plan it produces does not depend on which unit was chosen.
    assert canonical_sha256(compile_payload(payload).plan) == canonical_sha256(
        compile_file(EXAMPLES / "valid" / "minimal.json").plan
    )


def _two_resident_payload(*, private: bool) -> dict[str, Any]:
    """The minimal scenario with a housemate who wants the kitchen at the same moment.

    Both activities are anchored on the same half hour and neither depends on the other, so the
    only thing that can separate them is the privacy rule. With it off they are free to overlap —
    two people in one room is ordinary — and with it on they cannot.
    """
    payload = _payload()
    payload["residents"].append({"residentId": "resident_2", "displayName": "Resident Two"})
    payload["initialState"]["residents"].append(
        {"residentId": "resident_2", "locationId": "bedroom", "facts": {"awake": False}}
    )
    first = copy.deepcopy(payload["days"][0]["activities"][0])
    first.update(
        {
            "activityId": "activity_private",
            "actorId": "resident_1",
            "intent": "take_shower",
            "requiredResources": [],
            "commitmentId": None,
            "startWindow": {
                "earliest": "2026-10-12T08:00:00+02:00",
                "preferred": "2026-10-12T08:00:00+02:00",
                "latest": "2026-10-12T09:00:00+02:00",
            },
        }
    )
    if private:
        first["extensions"] = {PRIVACY_EXTENSION: ["resident_2"]}
    second = copy.deepcopy(first)
    second.update(
        {
            "activityId": "activity_other",
            "actorId": "resident_2",
            "intent": "clean_kitchen",
            "extensions": {},
        }
    )
    payload["days"][0]["activities"] = [first, second]
    payload["commitments"] = []
    # The example's runtime events name activities this fixture replaced.
    payload["runtimeEventCandidates"] = []
    return payload


def test_without_a_privacy_rule_two_residents_may_share_a_room() -> None:
    """The baseline the constraint has to be measured against: co-presence is the normal case."""
    result = compile_payload(_two_resident_payload(private=False))

    assert result.plan is not None
    first, second = sorted(_activities(result.plan), key=lambda item: item.source_activity_id)
    assert first.scheduled_start < second.scheduled_end
    assert second.scheduled_start < first.scheduled_end


def test_a_private_activity_empties_the_room_it_happens_in() -> None:
    """Pairwise non-overlap, not capacity: the rule is about two named people in one room."""
    result = compile_payload(_two_resident_payload(private=True))

    assert result.plan is not None
    ordered = sorted(_activities(result.plan), key=lambda item: item.scheduled_start)
    assert ordered[0].scheduled_end <= ordered[1].scheduled_start


def test_privacy_does_not_reach_a_different_room() -> None:
    """Being private about the kitchen says nothing about what happens in the bedroom."""
    payload = _two_resident_payload(private=True)
    payload["days"][0]["activities"][1]["locationIds"] = ["bedroom"]
    payload["days"][0]["activities"][1]["intent"] = "read_and_rest"

    result = compile_payload(payload)

    assert result.plan is not None
    first, second = sorted(_activities(result.plan), key=lambda item: item.source_activity_id)
    assert first.scheduled_start < second.scheduled_end
    assert second.scheduled_start < first.scheduled_end


def test_a_shared_use_is_one_activity_and_passes() -> None:
    """Two participants on one interval is one use, and the rule is about who is *not* in it."""
    payload = _two_resident_payload(private=True)
    payload["days"][0]["activities"] = [payload["days"][0]["activities"][0]]
    payload["days"][0]["activities"][0]["participantIds"] = ["resident_2"]

    result = compile_payload(payload)

    assert result.plan is not None
    assert len(_activities(result.plan)) == 1


def _branching_payload(*, room_for_the_shared_arm: bool) -> dict[str, Any]:
    """The couple's dinner written twice: one sitting, or two.

    With room, the shared arm fits and is worth more than both halves of the separate one. Without
    it — a commitment parked over the shared arm's only window — the compiler has to fall to the
    separate arm rather than squeeze the meal, which is the decision §6.3.2 says belongs to it.
    """
    payload = _payload()
    payload["residents"].append({"residentId": "resident_2", "displayName": "Resident Two"})
    payload["initialState"]["residents"].append(
        {"residentId": "resident_2", "locationId": "bedroom", "facts": {"awake": False}}
    )
    payload["runtimeEventCandidates"] = []
    payload["commitments"] = []
    template = copy.deepcopy(payload["days"][0]["activities"][0])
    template.update({"intent": "eat_dinner", "requiredResources": [], "commitmentId": None})

    def arm(
        activity_id: str, actor: str, branch: str, priority: int, **extra: Any
    ) -> dict[str, Any]:
        item = copy.deepcopy(template)
        item.update(
            {
                "activityId": activity_id,
                "actorId": actor,
                "mandatory": False,
                "priority": priority,
                "extensions": {BRANCH_EXTENSION: {"group": "dinner", "branch": branch}},
                "startWindow": {
                    "earliest": "2026-10-12T19:00:00+02:00",
                    "preferred": "2026-10-12T19:00:00+02:00",
                    "latest": "2026-10-12T19:30:00+02:00",
                },
                **extra,
            }
        )
        return item

    shared = arm("dinner_joint", "resident_1", "joint", 90, participantIds=["resident_2"])
    if not room_for_the_shared_arm:
        # `resident_2` is out until after the shared arm's window closes, so one sitting cannot
        # hold them both and the separate arm is the only one that fits.
        payload["commitments"] = [
            {
                "commitmentId": "late_shift",
                "intent": "work_shift",
                "locationId": "kitchen",
                "start": "2026-10-12T17:00:00+02:00",
                "end": "2026-10-12T21:00:00+02:00",
                "participantIds": ["resident_2"],
            }
        ]
    payload["days"][0]["activities"] = [
        shared,
        # The separate arms reach further into the evening, which is the point of them: eating
        # apart is what makes a late shift survivable without shortening anybody's dinner.
        arm("dinner_alone_1", "resident_1", "separate", 40, **_late_window()),
        arm("dinner_alone_2", "resident_2", "separate", 40, **_late_window()),
    ]
    return payload


def _late_window() -> dict[str, Any]:
    return {
        "startWindow": {
            "earliest": "2026-10-12T19:00:00+02:00",
            "preferred": "2026-10-12T19:00:00+02:00",
            "latest": "2026-10-12T22:00:00+02:00",
        }
    }


def test_the_compiler_takes_the_shared_sitting_when_it_fits() -> None:
    """Preference through `priority`, which the objective's first stage already maximises."""
    result = compile_payload(_branching_payload(room_for_the_shared_arm=True))

    assert result.plan is not None
    assert [item.source_activity_id for item in _activities(result.plan)] == ["dinner_joint"]


def test_the_compiler_falls_to_two_sittings_rather_than_squeeze_one() -> None:
    """Eating a forty-minute dinner in fifteen would be a worse lie than eating it alone."""
    result = compile_payload(_branching_payload(room_for_the_shared_arm=False))

    assert result.plan is not None
    scheduled = sorted(item.source_activity_id for item in _activities(result.plan))
    assert scheduled == ["dinner_alone_1", "dinner_alone_2"]


def test_exactly_one_arm_of_a_group_is_ever_scheduled() -> None:
    """Alternatives, not options: a plan holding both would have the household eating twice."""
    for room in (True, False):
        result = compile_payload(_branching_payload(room_for_the_shared_arm=room))
        assert result.plan is not None
        chosen = {item.source_activity_id for item in _activities(result.plan)}
        assert ("dinner_joint" in chosen) != bool({"dinner_alone_1", "dinner_alone_2"} & chosen)


def test_a_choice_is_canonicalised_once_per_group_not_once_per_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The losing arm is not a preference to try and reject: exactly one arm ever exists.

    Locked activity by activity, every day with a degradable dinner produced a guaranteed rejection
    found by bisection, and on a couple's week that was a third of all rejections. The choice is
    one lock on the most valuable arm, and the arm's activities are never locked on their own.
    """
    from smart_home_sim.compiler import solver as solver_module

    names: list[str] = []
    original = solver_module.ScheduleSolver._lock_requests

    def spy(self: Any, requests: list[Any]) -> Any:
        names.extend(item.name for item in requests)
        return original(self, requests)

    monkeypatch.setattr(solver_module.ScheduleSolver, "_lock_requests", spy)
    for room in (True, False):
        names.clear()
        result = compile_payload(_branching_payload(room_for_the_shared_arm=room))

        assert result.plan is not None
        assert [name for name in names if name.startswith("canonical_branch__")] == [
            "canonical_branch__dinner__joint"
        ]
        assert not [name for name in names if name.startswith("canonical_optional__dinner")]


def test_a_household_is_split_into_windows_by_how_many_live_in_it() -> None:
    """The threshold was measured on one resident, and a household is not a longer day."""
    scenario = Scenario.model_validate_json(
        (EXAMPLES / "valid/mario_week.json").read_text(encoding="utf-8")
    )
    resident = scenario.residents[0]
    couple = scenario.model_copy(
        update={"residents": [resident, resident.model_copy(update={"resident_id": "second"})]}
    )

    assert compiler_service._resident_days(scenario) == len(scenario.days)
    assert compiler_service._resident_days(couple) == 2 * len(scenario.days)
