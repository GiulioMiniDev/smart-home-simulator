from __future__ import annotations

from typing import Any

import pytest

from smart_home_sim.validation.service import validate_payload

STRUCTURAL_CASES = (
    "simulation_window_order",
    "unknown_time_zone",
    "naive_timestamp",
    "composite_without_members",
    "room_with_members",
    "window_order",
    "duration_order",
    "duration_and_end",
    "negative_duration",
    "dependency_lag_order",
    "conditional_without_condition",
    "always_with_fallback",
    "fallback_without_trigger",
    "activity_without_anchor",
    "activity_without_end",
    "end_without_start",
    "end_before_start",
    "commitment_order",
    "amount_event_without_range",
    "amount_event_with_value",
    "set_fact_without_value",
    "invalidate_fact_with_value",
    "comparison_condition_without_number",
    "membership_condition_without_array",
    "numeric_effect_without_number",
    "preferred_end_before_start",
    "non_composite_cycle_shape",
)


def mutate(payload: dict[str, Any], case: str) -> None:
    activity = payload["days"][0]["activities"][1]
    if case == "simulation_window_order":
        payload["simulationWindow"]["end"] = payload["simulationWindow"]["start"]
    elif case == "unknown_time_zone":
        payload["timeZone"] = "Mars/Olympus_Mons"
    elif case == "naive_timestamp":
        payload["initialState"]["at"] = "2026-10-12T00:00:00"
    elif case == "composite_without_members":
        payload["locations"][2]["memberLocationIds"] = []
    elif case == "room_with_members":
        payload["locations"][0]["memberLocationIds"] = ["kitchen"]
    elif case == "window_order":
        activity["startWindow"]["preferred"] = "2026-10-12T09:00:00+02:00"
    elif case == "duration_order":
        activity["duration"]["minimumMinutes"] = 20.0
    elif case == "duration_and_end":
        activity["endWindow"] = {
            "earliest": "2026-10-12T09:00:00+02:00",
            "preferred": "2026-10-12T09:00:00+02:00",
            "latest": "2026-10-12T09:00:00+02:00",
        }
    elif case == "negative_duration":
        activity["duration"]["minimumMinutes"] = -1.0
    elif case == "dependency_lag_order":
        group = activity["dependencyGroups"][0]
        group["minimumLagMinutes"] = 10.0
        group["maximumLagMinutes"] = 5.0
    elif case == "conditional_without_condition":
        activity["activation"] = {"mode": "conditional"}
    elif case == "always_with_fallback":
        activity["activation"] = {
            "mode": "always",
            "fallbackForActivityId": "activity_1",
        }
    elif case == "fallback_without_trigger":
        activity["activation"] = {
            "mode": "fallback",
            "fallbackForActivityId": "activity_1",
        }
    elif case == "activity_without_anchor":
        activity.pop("startWindow")
        activity["dependencyGroups"] = []
    elif case == "activity_without_end":
        activity.pop("duration")
    elif case == "end_without_start":
        activity.pop("startWindow")
        activity.pop("duration")
        activity["endWindow"] = {
            "earliest": "2026-10-12T09:00:00+02:00",
            "preferred": "2026-10-12T09:00:00+02:00",
            "latest": "2026-10-12T09:00:00+02:00",
        }
    elif case == "end_before_start":
        activity.pop("duration")
        activity["endWindow"] = {
            "earliest": "2026-10-12T07:00:00+02:00",
            "preferred": "2026-10-12T07:00:00+02:00",
            "latest": "2026-10-12T07:00:00+02:00",
        }
    elif case == "commitment_order":
        payload["commitments"][0]["end"] = payload["commitments"][0]["start"]
    elif case == "amount_event_without_range":
        effect = payload["runtimeEventCandidates"][0]["effects"][0]
        effect.pop("minimumAmount")
    elif case == "amount_event_with_value":
        payload["runtimeEventCandidates"][0]["effects"][0]["value"] = True
    elif case == "set_fact_without_value":
        payload["runtimeEventCandidates"][0]["effects"][0] = {
            "operation": "set_fact",
            "targetId": "awake",
        }
    elif case == "invalidate_fact_with_value":
        payload["runtimeEventCandidates"][0]["effects"][0] = {
            "operation": "invalidate_fact",
            "targetId": "awake",
            "value": False,
        }
    elif case == "comparison_condition_without_number":
        activity["preconditions"] = [{"fact": "fatigue", "operator": "gt", "value": "high"}]
    elif case == "membership_condition_without_array":
        activity["preconditions"] = [{"fact": "weather", "operator": "in", "value": "dry"}]
    elif case == "numeric_effect_without_number":
        activity["effects"] = [{"fact": "fatigue", "operation": "increment", "value": "much"}]
    elif case == "preferred_end_before_start":
        activity.pop("duration")
        activity["endWindow"] = {
            "earliest": "2026-10-12T07:00:00+02:00",
            "preferred": "2026-10-12T08:00:00+02:00",
            "latest": "2026-10-12T09:00:00+02:00",
        }
    elif case == "non_composite_cycle_shape":
        payload["locations"][0]["memberLocationIds"] = ["bedroom"]
    else:  # pragma: no cover - protects the test table itself
        raise AssertionError(case)


@pytest.mark.parametrize("case", STRUCTURAL_CASES)
def test_model_invariants_are_structural_errors(
    valid_payload: dict[str, Any],
    case: str,
) -> None:
    mutate(valid_payload, case)

    report = validate_payload(valid_payload)

    assert not report.valid
    assert {item.code for item in report.issues} == {"STRUCTURE_INVALID"}
