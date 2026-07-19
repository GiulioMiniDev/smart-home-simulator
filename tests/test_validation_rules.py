from __future__ import annotations

import copy
from typing import Any

import pytest

from smart_home_sim.validation.codes import STABLE_ISSUE_CODES, WARNING_ISSUE_CODES
from smart_home_sim.validation.issues import issue
from smart_home_sim.validation.service import validate_payload

NON_RULE_CODES = {
    "DUPLICATE_JSON_KEY",
    "FILE_ENCODING_ERROR",
    "FILE_NOT_FOUND",
    "FILE_READ_ERROR",
    "FILE_TOO_LARGE",
    "JSON_SYNTAX",
    "JSON_NESTING_TOO_DEEP",
    "STRUCTURE_INVALID",
    "UNSUPPORTED_SCHEMA_VERSION",
}

RULE_CODES = STABLE_ISSUE_CODES - NON_RULE_CODES


def fixed_window(value: str) -> dict[str, str]:
    return {"earliest": value, "preferred": value, "latest": value}


def add_second_resident(payload: dict[str, Any]) -> None:
    payload["residents"].append({"residentId": "resident_2"})
    payload["initialState"]["residents"].append(
        {"residentId": "resident_2", "locationId": "bedroom"}
    )


def add_second_day(payload: dict[str, Any], activity: dict[str, Any]) -> None:
    payload["simulationWindow"]["end"] = "2026-10-14T00:00:00+02:00"
    payload["days"].append(
        {
            "date": "2026-10-13",
            "context": {"dayType": "working_day"},
            "activities": [activity],
        }
    )


def mutate(payload: dict[str, Any], code: str) -> None:  # noqa: C901, PLR0912, PLR0915
    resident = payload["residents"][0]
    external = payload["externalPeople"][0]
    resource = payload["resources"][0]
    initial = payload["initialState"]
    commitment = payload["commitments"][0]
    day = payload["days"][0]
    first, second = day["activities"]
    event = payload["runtimeEventCandidates"][0]

    if code == "DUPLICATE_RESIDENT_ID":
        payload["residents"].append(copy.deepcopy(resident))
    elif code == "DUPLICATE_EXTERNAL_PERSON_ID":
        payload["externalPeople"].append(copy.deepcopy(external))
    elif code == "DUPLICATE_LOCATION_ID":
        payload["locations"].append(copy.deepcopy(payload["locations"][0]))
    elif code == "DUPLICATE_RESOURCE_ID":
        payload["resources"].append(copy.deepcopy(resource))
    elif code == "DUPLICATE_INITIAL_STATE":
        initial["residents"].append(copy.deepcopy(initial["residents"][0]))
    elif code == "DUPLICATE_COMMITMENT_ID":
        payload["commitments"].append(copy.deepcopy(commitment))
    elif code == "DUPLICATE_DAY":
        payload["days"].append(copy.deepcopy(day))
    elif code == "DUPLICATE_ACTIVITY_ID":
        second["activityId"] = first["activityId"]
    elif code == "DUPLICATE_RUNTIME_EVENT_ID":
        payload["runtimeEventCandidates"].append(copy.deepcopy(event))
    elif code == "PERSON_ID_COLLISION":
        external["externalPersonId"] = resident["residentId"]
    elif code == "UNKNOWN_RELATIONSHIP_RESIDENT":
        external["relationshipToResidents"] = {"missing": "friend"}
    elif code == "MISSING_RESIDENT_INITIAL_STATE":
        payload["residents"].append({"residentId": "resident_2"})
    elif code == "UNKNOWN_INITIAL_STATE_RESIDENT":
        initial["residents"][0]["residentId"] = "missing"
    elif code == "UNKNOWN_INITIAL_LOCATION":
        initial["residents"][0]["locationId"] = "missing"
    elif code == "UNKNOWN_COMPOSITE_MEMBER":
        payload["locations"][2]["memberLocationIds"].append("missing")
    elif code == "COMPOSITE_LOCATION_SELF_REFERENCE":
        payload["locations"][2]["memberLocationIds"].append("home")
    elif code == "COMPOSITE_LOCATION_CYCLE":
        payload["locations"][2]["memberLocationIds"].append("loop")
        payload["locations"].append(
            {"locationId": "loop", "kind": "composite", "memberLocationIds": ["home"]}
        )
    elif code == "UNKNOWN_RESOURCE_LOCATION":
        resource["locationId"] = "missing"
    elif code == "UNKNOWN_RESOURCE_STATE":
        initial["resourceFacts"]["missing"] = {}
    elif code == "UNKNOWN_COMMITMENT_PARTICIPANT":
        commitment["participantIds"] = ["missing"]
    elif code == "UNKNOWN_COMMITMENT_LOCATION":
        commitment["locationId"] = "missing"
    elif code == "UNKNOWN_ACTOR":
        second["actorId"] = "missing"
    elif code == "UNKNOWN_PARTICIPANT":
        second["participantIds"] = ["missing"]
    elif code == "UNKNOWN_ACTIVITY_LOCATION":
        second["locationIds"] = ["missing"]
    elif code == "UNKNOWN_REQUIRED_RESOURCE":
        second["requiredResources"] = [{"resourceId": "missing", "units": 1}]
    elif code == "UNKNOWN_DEPENDENCY":
        second["dependencyGroups"][0]["activityIds"] = ["missing"]
    elif code == "SELF_DEPENDENCY":
        second["dependencyGroups"][0]["activityIds"] = [second["activityId"]]
    elif code == "UNKNOWN_COMMITMENT":
        second["commitmentId"] = "missing"
    elif code == "UNKNOWN_FALLBACK_TARGET":
        second["activation"] = {
            "mode": "fallback",
            "fallbackForActivityId": "missing",
            "fallbackTrigger": "activity_cancelled",
        }
    elif code == "UNKNOWN_EVENT_TRIGGER_ACTIVITY":
        event["triggerActivityId"] = "missing"
    elif code == "UNKNOWN_EVENT_TARGET_ACTIVITY":
        event["effects"][0]["targetId"] = "missing"
    elif code == "UNKNOWN_EVENT_TARGET_RESIDENT":
        event["effects"][0] = {
            "operation": "interrupt_actor",
            "targetId": "missing",
            "minimumAmount": 1.0,
            "maximumAmount": 2.0,
        }
    elif code in {"EVENT_TRIGGER_DAY_MISMATCH", "EVENT_TARGET_DAY_MISMATCH"}:
        payload["simulationWindow"]["end"] = "2026-10-14T00:00:00+02:00"
        payload["days"].append(
            {
                "date": "2026-10-13",
                "context": {"dayType": "working_day"},
                "activities": [],
            }
        )
        event["eligibleWindow"] = fixed_window("2026-10-13T08:35:00+02:00")
        if code == "EVENT_TRIGGER_DAY_MISMATCH":
            event["effects"] = [{"operation": "invalidate_fact", "targetId": "weather_is_dry"}]
        else:
            event.pop("triggerActivityId")
    elif code == "DUPLICATE_COMMITMENT_PARTICIPANT":
        commitment["participantIds"].append("resident_1")
    elif code == "DUPLICATE_ACTIVITY_LOCATION":
        second["locationIds"].append("kitchen")
    elif code == "DUPLICATE_PARTICIPANT":
        second["participantIds"] = ["friend_1", "friend_1"]
    elif code == "DUPLICATE_RESOURCE_REQUIREMENT":
        first["requiredResources"].append(copy.deepcopy(first["requiredResources"][0]))
    elif code == "DUPLICATE_ACTIVITY_LABEL":
        second["labels"] = ["housework", "housework"]
    elif code == "DUPLICATE_DEPENDENCY":
        second["dependencyGroups"][0]["activityIds"].append("activity_1")
    elif code == "ACTOR_REPEATED_AS_PARTICIPANT":
        second["participantIds"] = ["resident_1"]
    elif code == "DUPLICATE_REPAIR_STEP":
        payload["materializationPolicy"] = {
            "repairOrder": [
                "drop_optional_activity",
                "drop_optional_activity",
                "reject_day_plan",
            ]
        }
    elif code == "INVALID_REPAIR_ORDER":
        payload["materializationPolicy"] = {"repairOrder": ["drop_optional_activity"]}
    elif code == "REPAIR_DISABLED_WITH_LOCAL_STEPS":
        payload["materializationPolicy"] = {"allowLocalRepair": False}
    elif code == "DUPLICATE_OUTPUT_FORMAT":
        payload["requestedOutputs"] = {"formats": ["jsonl", "jsonl"]}
    elif code == "DUPLICATE_DECLARED_CONSTRAINT":
        payload["declaredConstraints"] = ["unique_location", "unique_location"]
    elif code == "TIMEZONE_OFFSET_MISMATCH":
        second["startWindow"] = fixed_window("2026-10-12T08:35:00+01:00")
    elif code == "INITIAL_STATE_TIME_MISMATCH":
        initial["at"] = "2026-10-12T00:01:00+02:00"
    elif code == "DAY_OUTSIDE_SIMULATION":
        day["date"] = "2026-10-13"
    elif code == "MISSING_REQUIRED_DAY":
        payload["simulationWindow"]["end"] = "2026-10-14T00:00:00+02:00"
    elif code == "ACTIVITY_WINDOW_OUTSIDE_SIMULATION":
        second["duration"] = {
            "minimumMinutes": 1000.0,
            "preferredMinutes": 1000.0,
            "maximumMinutes": 1000.0,
        }
    elif code == "ACTIVITY_ASSIGNED_TO_WRONG_DAY":
        second["startWindow"] = fixed_window("2026-10-13T00:00:00+02:00")
    elif code == "COMMITMENT_OUTSIDE_SIMULATION":
        commitment["end"] = "2026-10-13T01:00:00+02:00"
    elif code == "RUNTIME_EVENT_OUTSIDE_SIMULATION":
        event["eligibleWindow"] = fixed_window("2026-10-13T01:00:00+02:00")
    elif code in {"IMPOSSIBLE_PRECEDENCE", "IMPOSSIBLE_ANY_DEPENDENCY"}:
        second["startWindow"] = fixed_window("2026-10-12T07:00:00+02:00")
        second["dependencyGroups"][0]["mode"] = (
            "any" if code == "IMPOSSIBLE_ANY_DEPENDENCY" else "all"
        )
    elif code == "DEPENDENCY_CYCLE":
        first["dependencyGroups"] = [{"mode": "all", "activityIds": ["activity_2"]}]
    elif code == "FUTURE_DEPENDENCY":
        future = copy.deepcopy(second)
        future["activityId"] = "future_activity"
        future["startWindow"] = fixed_window("2026-10-13T08:35:00+02:00")
        future["dependencyGroups"] = []
        second["dependencyGroups"] = [{"mode": "all", "activityIds": ["future_activity"]}]
        add_second_day(payload, future)
    elif code == "FALLBACK_TARGET_IS_FALLBACK":
        third = copy.deepcopy(second)
        third["activityId"] = "activity_3"
        third["activation"] = {
            "mode": "fallback",
            "fallbackForActivityId": "activity_1",
            "fallbackTrigger": "activity_cancelled",
        }
        day["activities"].append(third)
        second["activation"] = {
            "mode": "fallback",
            "fallbackForActivityId": "activity_3",
            "fallbackTrigger": "activity_cancelled",
        }
    elif code == "FALLBACK_ACTOR_MISMATCH":
        add_second_resident(payload)
        second["actorId"] = "resident_2"
        second["activation"] = {
            "mode": "fallback",
            "fallbackForActivityId": "activity_1",
            "fallbackTrigger": "activity_cancelled",
        }
    elif code == "FALLBACK_DAY_MISMATCH":
        day["activities"].remove(second)
        second["startWindow"] = fixed_window("2026-10-13T08:35:00+02:00")
        second["activation"] = {
            "mode": "fallback",
            "fallbackForActivityId": "activity_1",
            "fallbackTrigger": "activity_cancelled",
        }
        add_second_day(payload, second)
    elif code == "FALLBACK_CYCLE":
        first["activation"] = {
            "mode": "fallback",
            "fallbackForActivityId": "activity_2",
            "fallbackTrigger": "activity_cancelled",
        }
        second["activation"] = {
            "mode": "fallback",
            "fallbackForActivityId": "activity_1",
            "fallbackTrigger": "activity_cancelled",
        }
    elif code == "FIXED_ACTIVITY_OVERLAP":
        second["mandatory"] = True
        second["startWindow"] = fixed_window("2026-10-12T08:15:00+02:00")
        second["duration"] = {
            "minimumMinutes": 30.0,
            "preferredMinutes": 30.0,
            "maximumMinutes": 30.0,
        }
        second["dependencyGroups"] = []
    elif code == "COMMITMENT_OVERLAP":
        other = copy.deepcopy(commitment)
        other["commitmentId"] = "other_commitment"
        payload["commitments"].append(other)
    elif code == "ACTIVITY_COMMITMENT_PARTICIPANT_MISMATCH":
        first["participantIds"] = ["friend_1"]
    elif code == "ACTIVITY_COMMITMENT_LOCATION_MISMATCH":
        first["locationIds"] = ["bedroom"]
    elif code == "ACTIVITY_COMMITMENT_TIME_MISMATCH":
        first["startWindow"] = fixed_window("2026-10-12T07:00:00+02:00")
    elif code == "ACTIVITY_COMMITMENT_END_MISMATCH":
        commitment["end"] = "2026-10-12T08:40:00+02:00"
    elif code == "MANDATORY_COMMITMENT_OPTIONAL_ACTIVITY":
        first["mandatory"] = False
    elif code == "FIXED_ACTIVITY_COMMITMENT_OVERLAP":
        second["mandatory"] = True
        second["startWindow"] = fixed_window("2026-10-12T10:00:00+02:00")
        second["duration"] = {
            "minimumMinutes": 30.0,
            "preferredMinutes": 30.0,
            "maximumMinutes": 30.0,
        }
        second["dependencyGroups"] = []
        other = copy.deepcopy(commitment)
        other["commitmentId"] = "overlapping_commitment"
        other["start"] = "2026-10-12T10:15:00+02:00"
        other["end"] = "2026-10-12T10:45:00+02:00"
        payload["commitments"].append(other)
    elif code == "UNUSED_COMMITMENT":
        other = copy.deepcopy(commitment)
        other["commitmentId"] = "unused_commitment"
        other["start"] = "2026-10-12T10:00:00+02:00"
        other["end"] = "2026-10-12T10:30:00+02:00"
        payload["commitments"].append(other)
    elif code == "RESOURCE_REQUIREMENT_EXCEEDS_CAPACITY":
        first["requiredResources"][0]["units"] = 2
    elif code == "RESOURCE_LOCATION_MISMATCH":
        second["locationIds"] = ["bedroom"]
        second["requiredResources"] = [{"resourceId": "kettle_1", "units": 1}]
    elif code == "FIXED_RESOURCE_CAPACITY_EXCEEDED":
        second["mandatory"] = True
        second["canOverlapForActor"] = True
        second["startWindow"] = fixed_window("2026-10-12T08:15:00+02:00")
        second["duration"] = {
            "minimumMinutes": 30.0,
            "preferredMinutes": 30.0,
            "maximumMinutes": 30.0,
        }
        second["dependencyGroups"] = []
        second["requiredResources"] = [{"resourceId": "kettle_1", "units": 1}]
    else:  # pragma: no cover - protects the issue registry/test matrix
        raise AssertionError(f"No mutation for {code}")


@pytest.mark.parametrize("expected_code", sorted(RULE_CODES))
def test_every_rule_code_is_exercised(
    valid_payload: dict[str, Any],
    expected_code: str,
) -> None:
    mutate(valid_payload, expected_code)

    report = validate_payload(valid_payload)
    by_code = {item.code: item for item in report.issues}

    assert expected_code in by_code, report.model_dump_json(indent=2)
    expected_severity = "warning" if expected_code in WARNING_ISSUE_CODES else "error"
    assert by_code[expected_code].severity == expected_severity
    assert report.valid is (expected_severity == "warning")


def test_registry_has_an_executed_test_category_for_every_code() -> None:
    assert RULE_CODES | NON_RULE_CODES == STABLE_ISSUE_CODES
    assert RULE_CODES.isdisjoint(NON_RULE_CODES)


def test_issue_factory_rejects_unregistered_codes_and_severity_changes() -> None:
    with pytest.raises(ValueError, match="Unregistered"):
        issue("NEW_UNREVIEWED_CODE", "semantic", "$", "not registered")
    with pytest.raises(ValueError, match="frozen severity"):
        issue("UNUSED_COMMITMENT", "semantic", "$", "wrong severity")


def test_boundary_truncation_must_be_explicit(valid_payload: dict[str, Any]) -> None:
    second = valid_payload["days"][0]["activities"][1]
    second["startWindow"] = fixed_window("2026-10-12T23:30:00+02:00")
    second["duration"] = {
        "minimumMinutes": 60.0,
        "preferredMinutes": 60.0,
        "maximumMinutes": 60.0,
    }

    rejected = validate_payload(valid_payload)
    second["allowBoundaryTruncation"] = True
    accepted = validate_payload(valid_payload)

    assert "ACTIVITY_WINDOW_OUTSIDE_SIMULATION" in {item.code for item in rejected.issues}
    assert accepted.valid


def test_external_people_do_not_create_resident_schedule_conflicts(
    valid_payload: dict[str, Any],
) -> None:
    first, second = valid_payload["days"][0]["activities"]
    first["participantIds"] = ["friend_1"]
    valid_payload["commitments"][0]["participantIds"].append("friend_1")
    second["participantIds"] = ["friend_1"]
    second["mandatory"] = True
    second["startWindow"] = fixed_window("2026-10-12T08:15:00+02:00")
    second["duration"] = {
        "minimumMinutes": 30.0,
        "preferredMinutes": 30.0,
        "maximumMinutes": 30.0,
    }
    second["dependencyGroups"] = []
    second["actorId"] = "resident_1"

    report = validate_payload(valid_payload)

    assert "FIXED_ACTIVITY_OVERLAP" in {item.code for item in report.issues}
    assert "friend_1" not in next(
        item.message for item in report.issues if item.code == "FIXED_ACTIVITY_OVERLAP"
    )


def test_adjacent_fixed_resource_usage_does_not_overlap(
    valid_payload: dict[str, Any],
) -> None:
    second = valid_payload["days"][0]["activities"][1]
    second["mandatory"] = True
    second["startWindow"] = fixed_window("2026-10-12T08:30:00+02:00")
    second["duration"] = {
        "minimumMinutes": 30.0,
        "preferredMinutes": 30.0,
        "maximumMinutes": 30.0,
    }
    second["requiredResources"] = [{"resourceId": "kettle_1", "units": 1}]

    report = validate_payload(valid_payload)

    assert report.valid, report.model_dump_json(indent=2)
