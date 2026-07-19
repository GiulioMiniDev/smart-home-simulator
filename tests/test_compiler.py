from __future__ import annotations

import copy
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.compiler import compile_file, compile_payload
from smart_home_sim.compiler import service as compiler_service
from smart_home_sim.compiler.issues import compilation_issue
from smart_home_sim.compiler.service import canonical_sha256
from smart_home_sim.compiler.solver import SolveOutcome
from smart_home_sim.domain.compilation import COMPILATION_ISSUE_CODES
from smart_home_sim.domain.models import Scenario

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
