"""Reproducibly migrate the research week example to scenario contract 1.0.0."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    PROJECT_ROOT.parents[1]
    / "04_research_notes/proposals/02_example_mario_rossi_one_week_llm_input.json"
)
TARGET = PROJECT_ROOT / "examples/valid/mario_week.json"
ZONE = ZoneInfo("Europe/Rome")
RESIDENT_ID = "resident_mario_rossi"


def local_datetime(day: str | date, clock: str) -> datetime:
    parsed_day = date.fromisoformat(day) if isinstance(day, str) else day
    return datetime.combine(parsed_day, time.fromisoformat(clock), ZONE)


def window(earliest: datetime, preferred: datetime, latest: datetime) -> dict[str, str]:
    return {
        "earliest": earliest.isoformat(),
        "preferred": preferred.isoformat(),
        "latest": latest.isoformat(),
    }


def source_start_window(activity: dict[str, Any], day: date) -> dict[str, str] | None:
    if "startWindow" in activity:
        earliest = local_datetime(day, activity["startWindow"]["earliest"])
        latest = local_datetime(day, activity["startWindow"]["latest"])
        preferred = earliest + (latest - earliest) / 2
        return window(earliest, preferred, latest)
    if "approximateStart" in activity:
        preferred = local_datetime(day, activity["approximateStart"])
        return window(
            preferred - timedelta(minutes=5),
            preferred,
            preferred + timedelta(minutes=10),
        )
    return None


def duration_range(source: dict[str, Any]) -> dict[str, float]:
    return {
        "minimumMinutes": float(source["min"]),
        "preferredMinutes": float(source["preferred"]),
        "maximumMinutes": float(source["max"]),
    }


def condition(fact: str) -> dict[str, str]:
    return {"fact": fact, "operator": "truthy"}


def activation(activity: dict[str, Any]) -> dict[str, str]:
    expression = activity.get("activatedWhen")
    if expression is None:
        return {"mode": "always"}
    suffixes = {
        "_precondition_failed": "precondition_failed",
        "_cancelled": "activity_cancelled",
        "_replaced": "activity_replaced",
    }
    for suffix, trigger in suffixes.items():
        if expression.endswith(suffix):
            return {
                "mode": "fallback",
                "fallbackForActivityId": expression.removesuffix(suffix),
                "fallbackTrigger": trigger,
            }
    raise ValueError(f"Unsupported legacy activation expression: {expression}")


def dependency_groups(activity: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if activity.get("after"):
        result.append({"mode": "all", "activityIds": activity["after"]})
    if activity.get("afterAny"):
        result.append({"mode": "any", "activityIds": activity["afterAny"]})
    return result


def sleep_duration(
    start: dict[str, str],
    next_wake: dict[str, str],
) -> dict[str, float]:
    starts = {name: datetime.fromisoformat(value) for name, value in start.items()}
    wakes = {name: datetime.fromisoformat(value) for name, value in next_wake.items()}
    return {
        "minimumMinutes": (wakes["earliest"] - starts["latest"]).total_seconds() / 60,
        "preferredMinutes": (wakes["preferred"] - starts["preferred"]).total_seconds() / 60,
        "maximumMinutes": (wakes["latest"] - starts["earliest"]).total_seconds() / 60,
    }


def migrate_activity(
    source: dict[str, Any],
    day: date,
    next_wake: dict[str, str] | None,
    commitment_ids: dict[tuple[str, str], str],
) -> dict[str, Any]:
    start = source_start_window(source, day)
    result: dict[str, Any] = {
        "activityId": source["id"],
        "actorId": RESIDENT_ID,
        "intent": source["intent"],
        "locationIds": [source["destination"]],
        "mandatory": source["mandatory"],
        "priority": 80 if source["mandatory"] else 40,
        "dependencyGroups": dependency_groups(source),
        "participantIds": source.get("participants", []),
        "requiredResources": [
            {"resourceId": resource_id, "units": 1}
            for resource_id in source.get("requiredResources", [])
        ],
        "preconditions": [condition(item) for item in source.get("preconditions", [])],
        "activation": activation(source),
    }
    if start is not None:
        result["startWindow"] = start
    if "durationMinutes" in source:
        result["duration"] = duration_range(source["durationMinutes"])
    elif source["intent"] == "sleep" and start is not None and next_wake is not None:
        result["duration"] = sleep_duration(start, next_wake)
        if day == date(2026, 10, 18):
            result["allowBoundaryTruncation"] = True
    elif "expectedEnd" in source and start is not None:
        end = local_datetime(day, source["expectedEnd"])
        result["endWindow"] = window(end, end, end)
    else:
        raise ValueError(f"Cannot derive timing for {source['id']}")
    if legacy_commitment := source.get("commitmentRef"):
        result["commitmentId"] = commitment_ids[(legacy_commitment, day.isoformat())]
    if alternatives := source.get("alternativeActivityIds"):
        result["extensions"] = {"x-legacyAlternativeActivityIds": alternatives}
    return result


def migrate_commitments(
    source: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str]]:
    commitments: list[dict[str, Any]] = []
    ids: dict[tuple[str, str], str] = {}
    for item in source["fixedCommitments"]:
        for day_text in item["dates"]:
            start_text = item["start"]
            # The compiler proved 08:00 infeasible after the minimum morning chain and commute.
            # 08:15 is already inside every linked work activity's declared start window.
            if item["commitmentId"] == "work_weekdays" and start_text == "08:00":
                start_text = "08:15"
            commitment_id = f"{item['commitmentId']}__{day_text}"
            ids[(item["commitmentId"], day_text)] = commitment_id
            participants = [RESIDENT_ID, *item.get("participants", [])]
            attributes = {
                key: value
                for key, value in item.items()
                if key not in {"commitmentId", "dates", "start", "end", "location", "participants"}
            }
            commitments.append(
                {
                    "commitmentId": commitment_id,
                    "intent": item["commitmentId"],
                    "participantIds": participants,
                    "locationId": item["location"],
                    "start": local_datetime(day_text, start_text).isoformat(),
                    "end": local_datetime(day_text, item["end"]).isoformat(),
                    "mandatory": True,
                    "attributes": attributes,
                }
            )
    return commitments, ids


def migrate_runtime_event(item: dict[str, Any]) -> dict[str, Any]:
    day = date.fromisoformat(item["eligibleDate"])
    if trigger_window := item.get("triggerWindow"):
        earliest = local_datetime(day, trigger_window["earliest"])
        latest = local_datetime(day, trigger_window["latest"])
    else:
        earliest = local_datetime(day, "00:00")
        latest = local_datetime(day, "23:59:59")
    effect = item["effect"]
    effect_type = effect["type"]
    if effect_type == "delay_activity_start":
        migrated_effect = {
            "operation": effect_type,
            "targetId": effect["activityId"],
            "minimumAmount": float(effect["minutesRange"][0]),
            "maximumAmount": float(effect["minutesRange"][1]),
        }
    elif effect_type == "extend_activity_duration":
        migrated_effect = {
            "operation": effect_type,
            "targetId": item["triggerActivityId"],
            "minimumAmount": float(effect["minutesRange"][0]),
            "maximumAmount": float(effect["minutesRange"][1]),
        }
    elif effect_type == "interrupt_current_activity":
        migrated_effect = {
            "operation": "interrupt_actor",
            "targetId": RESIDENT_ID,
            "minimumAmount": float(effect["durationMinutesRange"][0]),
            "maximumAmount": float(effect["durationMinutesRange"][1]),
        }
    elif effect_type == "invalidate_precondition":
        migrated_effect = {
            "operation": "invalidate_fact",
            "targetId": effect["precondition"],
        }
    else:
        raise ValueError(f"Unsupported runtime event effect: {effect_type}")
    attributes = {
        key: value
        for key, value in {"note": item.get("note"), "intent": effect.get("intent")}.items()
        if value is not None
    }
    result: dict[str, Any] = {
        "eventId": item["eventId"],
        "eligibleWindow": window(earliest, earliest + (latest - earliest) / 2, latest),
        "occurrenceProbability": item["occurrenceProbability"],
        "preconditions": [condition(value) for value in item.get("preconditions", [])],
        "effects": [migrated_effect],
        "attributes": attributes,
    }
    if trigger := item.get("triggerActivityId"):
        result["triggerActivityId"] = trigger
    return result


def build_scenario(source: dict[str, Any]) -> dict[str, Any]:
    commitments, commitment_ids = migrate_commitments(source)
    rooms = source["environment"]["rooms"]
    composites = {
        "home": rooms,
        "bathroom_and_bedroom": ["bathroom", "bedroom"],
        "bedroom_and_kitchen": ["bedroom", "kitchen"],
        "bedroom_hallway_living_room": ["bedroom", "hallway", "living_room"],
        "home_and_kitchen": ["home", "kitchen"],
        "kitchen_and_balcony": ["kitchen", "balcony"],
        "living_room_and_hallway": ["living_room", "hallway"],
    }
    external_locations = [
        "market",
        "mothers_home",
        "neighborhood_bar",
        "outside",
        "pharmacy",
        "supermarket",
        "workplace",
    ]
    context_by_date = {item["date"]: item for item in source["externalContext"]}
    source_days = source["days"]
    days: list[dict[str, Any]] = []
    for day_index, item in enumerate(source_days):
        parsed_day = date.fromisoformat(item["date"])
        if day_index + 1 < len(source_days):
            next_day = source_days[day_index + 1]
            next_date = date.fromisoformat(next_day["date"])
            next_wake = source_start_window(next_day["activities"][0], next_date)
        else:
            next_preferred = local_datetime(parsed_day + timedelta(days=1), "06:25")
            next_wake = window(
                next_preferred - timedelta(minutes=5),
                next_preferred,
                next_preferred + timedelta(minutes=10),
            )
        facts = {
            key: value
            for key, value in context_by_date[item["date"]].items()
            if key not in {"date", "dayType"}
        }
        facts["sourceDayId"] = item["dayId"]
        days.append(
            {
                "date": item["date"],
                "context": {
                    "dayType": item["dayType"],
                    "narrativeIntent": item["narrativeIntent"],
                    "facts": facts,
                },
                "activities": [
                    migrate_activity(activity, parsed_day, next_wake, commitment_ids)
                    for activity in item["activities"]
                ],
            }
        )

    resident_source = source["resident"]
    initial = source["initialState"]
    profile = {
        key: value
        for key, value in resident_source.items()
        if key not in {"residentId", "name", "socialRelations"}
    }
    initial_facts = {
        key: value
        for key, value in initial.items()
        if key not in {"timestamp", "residentId", "location"}
    }
    initial_facts["sourceObservedAt"] = initial["timestamp"]

    return {
        "schemaVersion": "1.0.0",
        "documentType": "life_scenario",
        "scenarioId": source["scenarioId"],
        "title": source["title"],
        "language": source["language"],
        "timeZone": source["timeZone"],
        "simulationWindow": source["simulationWindow"],
        "seed": source.get("seed", 20261012),
        "provenance": {
            "authorType": source["provenance"]["authorType"],
            "modelName": source["provenance"]["model"],
            "promptTemplateVersion": source["provenance"]["promptTemplateVersion"],
            "generatedAt": source["provenance"]["generatedAt"],
            "humanReviewed": source["provenance"]["humanReviewed"],
            "parameters": {"sourceNote": source["provenance"]["note"]},
        },
        "modelReferences": {
            "activityCatalog": {
                "referenceId": "activity_catalog",
                "version": source["catalogRefs"]["activityCatalogVersion"],
            },
            "homeModel": {
                "referenceId": source["environment"]["homeId"],
                "version": source["catalogRefs"]["homeModelVersion"],
            },
            "sensorModel": {
                "referenceId": "ambient_sensor_model",
                "version": source["catalogRefs"]["sensorModelVersion"],
            },
        },
        "materializationPolicy": {
            "authoritativeStateSource": "scenario_initial_then_previous_execution",
            "revalidateBeforeEachDay": source["materializationPolicy"]["revalidateBeforeEachDay"],
            "requireEveryDate": True,
            "allowLocalRepair": source["materializationPolicy"]["allowLocalRepair"],
            "repairOrder": [
                "shift_within_window",
                "shorten_within_range",
                "apply_declared_fallback",
                "drop_optional_activity",
                "reject_day_plan",
            ],
        },
        "residents": [
            {
                "residentId": resident_source["residentId"],
                "displayName": resident_source["name"],
                "profile": profile,
            }
        ],
        "externalPeople": [
            {
                "externalPersonId": relation["relationId"],
                "relationshipToResidents": {RESIDENT_ID: relation["relationId"]},
                "attributes": {
                    "usualContactFrequencyPerWeek": relation["usualContactFrequencyPerWeek"]
                },
            }
            for relation in resident_source["socialRelations"]
        ],
        "locations": [
            *[{"locationId": room, "kind": "room"} for room in rooms],
            *[
                {
                    "locationId": location_id,
                    "kind": "composite",
                    "memberLocationIds": members,
                }
                for location_id, members in composites.items()
            ],
            *[
                {"locationId": location_id, "kind": "external"}
                for location_id in external_locations
            ],
        ],
        "resources": [
            {
                "resourceId": item["resourceId"],
                "resourceType": item["type"],
                "locationId": item["room"],
                "capacity": item["capacity"],
            }
            for item in source["environment"]["resources"]
        ],
        "initialState": {
            "at": source["simulationWindow"]["start"],
            "residents": [
                {
                    "residentId": initial["residentId"],
                    "locationId": initial["location"],
                    "facts": initial_facts,
                }
            ],
        },
        "commitments": commitments,
        "days": days,
        "runtimeEventCandidates": [
            migrate_runtime_event(item) for item in source["runtimeEventCandidates"]
        ],
        "declaredConstraints": source["globalConstraints"],
        "requestedOutputs": {
            "observableSensorLog": source["requestedOutputs"]["observableSensorLog"],
            "oracleGroundTruth": source["requestedOutputs"]["oracleGroundTruth"],
            "executedActivityTrace": source["requestedOutputs"]["executedActivityTrace"],
            "planExecutionDiff": source["requestedOutputs"]["planExecutionDiff"],
            "finalDailyDiaries": source["requestedOutputs"]["finalDailyDiaries"],
            "finalScenarioState": source["requestedOutputs"]["finalWeeklyState"],
            "formats": source["requestedOutputs"]["formats"],
        },
        "extensions": {
            "x-sourceSchemaVersion": source["schemaVersion"],
            "x-homeConnections": source["environment"]["connections"],
            "x-sensorInventoryDeferredToSensorMilestone": source["environment"]["sensors"],
        },
    }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    scenario = build_scenario(source)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
    print(f"Migrated {len(scenario['days'])} days to {TARGET}")


if __name__ == "__main__":
    main()
