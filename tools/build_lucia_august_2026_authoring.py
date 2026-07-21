"""Build the prompt-1.2.1 authoring bundle for Lucia Rossi, August 2026."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY_CATALOG = ROOT / "src/smart_home_sim/catalogs/activity-catalog-1.0.0.json"
CASE_TEMPLATE = ROOT / "prompts/cases/lucia-rossi-august-2026.md"
RESIDENT_ID = "resident_lucia_rossi"
SCENARIO_ID = "lucia_rossi_august_2026"
OFFSET = "+02:00"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "generated/lucia_rossi_august_2026",
    )
    return parser.parse_args()


def iso_at(day: date, clock: str) -> str:
    return f"{day.isoformat()}T{clock}:00{OFFSET}"


def shifted_clock(clock: str, minutes: int) -> str:
    hour, minute = (int(part) for part in clock.split(":"))
    shifted = hour * 60 + minute + minutes
    return f"{shifted // 60:02d}:{shifted % 60:02d}"


def value(value: Any) -> dict[str, Any]:
    return {"source": "literal", "value": value}


def activity(
    day: date,
    sequence: int,
    intent: str,
    location_ids: list[str],
    preferred_start: str,
    preferred_minutes: int,
    *,
    minimum_minutes: int | None = None,
    maximum_minutes: int | None = None,
    resources: list[str] | None = None,
    boundary_truncation: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "activityId": f"act_{day:%Y%m%d}_{sequence:02d}_{intent}",
        "actorId": RESIDENT_ID,
        "intent": intent,
        "locationIds": location_ids,
        "startWindow": {
            "earliest": iso_at(day, preferred_start),
            "preferred": iso_at(day, preferred_start),
            "latest": iso_at(day, preferred_start),
        },
        "duration": {
            "minimumMinutes": preferred_minutes,
            "preferredMinutes": preferred_minutes,
            "maximumMinutes": preferred_minutes,
        },
        "priority": 80 if intent in {"sleep", "wake_up_without_alarm", "work_shift"} else 60,
        "mandatory": True,
        "activation": {"mode": "always"},
    }
    if resources:
        result["requiredResources"] = [
            {"resourceId": resource_id, "units": 1} for resource_id in resources
        ]
    if boundary_truncation:
        result["allowBoundaryTruncation"] = True
    return result


def add_activity(
    activities: list[dict[str, Any]],
    day: date,
    intent: str,
    location_ids: list[str],
    preferred_start: str,
    preferred_minutes: int,
    **kwargs: Any,
) -> None:
    activities.append(
        activity(
            day,
            len(activities) + 1,
            intent,
            location_ids,
            preferred_start,
            preferred_minutes,
            **kwargs,
        )
    )


def add_morning(activities: list[dict[str, Any]], day: date, *, weekend: bool) -> None:
    wake = "07:30" if weekend else "06:45"
    hygiene = "07:45" if weekend else "07:00"
    breakfast = "08:15" if weekend else "07:30"
    dishes = "08:55" if weekend else "08:10"
    add_activity(
        activities,
        day,
        "wake_up_without_alarm",
        ["bedroom"],
        wake,
        8,
        minimum_minutes=5,
        maximum_minutes=10,
        resources=["bed_01"],
    )
    add_activity(
        activities,
        day,
        "morning_toilet_and_shower",
        ["bathroom"],
        hygiene,
        25,
        resources=["toilet_01", "shower_01"],
    )
    add_activity(
        activities,
        day,
        "prepare_and_eat_breakfast",
        ["kitchen"],
        breakfast,
        35,
        resources=["fridge_01", "stove_01"],
    )
    add_activity(
        activities,
        day,
        "wash_breakfast_dishes",
        ["kitchen"],
        dishes,
        10,
        minimum_minutes=8,
        maximum_minutes=12,
        resources=["kitchen_sink_01"],
    )


def add_lunch(activities: list[dict[str, Any]], day: date, clock: str, location: str) -> None:
    add_activity(activities, day, "eat_lunch", [location], clock, 35)


def add_evening(
    activities: list[dict[str, Any]],
    day: date,
    *,
    weekend: bool,
    leisure_intent: str,
    extra: tuple[str, str, list[str], int] | None = None,
    late_sleep: bool | None = None,
) -> None:
    if extra:
        intent, clock, locations, duration = extra
        add_activity(activities, day, intent, locations, clock, duration)
    dinner_prep = "19:30" if weekend else "19:20"
    dinner = "20:10" if weekend else "20:00"
    leisure = "20:55" if weekend else "20:45"
    late_sleep = weekend if late_sleep is None else late_sleep
    hygiene = "22:40" if late_sleep else "22:10"
    sleep = "23:15" if late_sleep else "22:45"
    add_activity(
        activities,
        day,
        "prepare_light_dinner",
        ["kitchen"],
        dinner_prep,
        30,
        resources=["fridge_01", "stove_01"],
    )
    add_activity(activities, day, "eat_dinner", ["kitchen"], dinner, 30)
    leisure_location = "living_room" if leisure_intent.startswith("watch") else "bedroom"
    leisure_resources = ["television_01"] if leisure_intent.startswith("watch") else None
    add_activity(
        activities,
        day,
        leisure_intent,
        [leisure_location],
        leisure,
        55 if weekend else 45,
        resources=leisure_resources,
    )
    add_activity(activities, day, "evening_hygiene", ["bathroom"], hygiene, 15)
    add_activity(
        activities,
        day,
        "sleep",
        ["bedroom"],
        sleep,
        480 if late_sleep else 465,
        minimum_minutes=450,
        maximum_minutes=495,
        resources=["bed_01"],
        boundary_truncation=day == date(2026, 8, 31),
    )


def add_office_day(activities: list[dict[str, Any]], day: date) -> None:
    add_morning(activities, day, weekend=False)
    add_activity(activities, day, "commute_to_work", ["workplace"], "08:25", 30)
    add_activity(activities, day, "work_shift", ["workplace"], "09:00", 215)
    add_lunch(activities, day, "12:45", "workplace")
    add_activity(activities, day, "work_shift", ["workplace"], "13:30", 225)
    add_activity(activities, day, "commute_home", ["home"], "17:25", 35)
    extras = [
        ("short_evening_walk", "18:20", ["outside"], 30),
        ("call_mother", "18:25", ["living_room"], 25),
        ("read", "18:25", ["bedroom"], 35),
    ]
    leisure = ["watch_late_news", "read_in_bed", "watch_television"][day.day % 3]
    add_evening(activities, day, weekend=False, leisure_intent=leisure, extra=extras[day.day % 3])


def add_remote_day(activities: list[dict[str, Any]], day: date) -> None:
    add_morning(activities, day, weekend=False)
    add_activity(activities, day, "work_shift", ["living_room"], "08:35", 230)
    add_lunch(activities, day, "12:40", "kitchen")
    add_activity(activities, day, "work_shift", ["living_room"], "13:25", 235)
    extras = [
        ("indoor_light_exercise", "18:05", ["living_room"], 30),
        ("tidy_living_room_and_hallway", "18:05", ["living_room", "hallway"], 30),
        ("call_sister_lucia", "18:10", ["living_room"], 25),
    ]
    leisure = ["read", "watch_documentary", "read_and_rest"][day.day % 3]
    add_evening(activities, day, weekend=False, leisure_intent=leisure, extra=extras[day.day % 3])


def add_grocery_trip(activities: list[dict[str, Any]], day: date) -> None:
    add_activity(activities, day, "travel_to_supermarket", ["supermarket"], "09:35", 25)
    add_activity(activities, day, "buy_groceries", ["supermarket"], "10:05", 45)
    add_activity(
        activities,
        day,
        "return_home_and_store_purchases",
        ["home"],
        "11:00",
        40,
        resources=["fridge_01"],
    )


def add_saturday(activities: list[dict[str, Any]], day: date) -> None:
    add_morning(activities, day, weekend=True)
    if day.day in {1, 29}:
        add_grocery_trip(activities, day)
    elif day.day == 8:
        add_activity(activities, day, "clean_bathroom", ["bathroom"], "10:00", 45)
        add_activity(activities, day, "call_mother", ["living_room"], "11:00", 25)
    elif day.day == 15:
        add_activity(activities, day, "read_and_rest", ["bedroom"], "10:15", 75)
        add_activity(activities, day, "prepare_simple_lunch", ["kitchen"], "11:45", 40)
    elif day.day == 22:
        add_activity(
            activities,
            day,
            "start_laundry",
            ["bathroom"],
            "09:45",
            20,
            resources=["washing_machine_01"],
        )
        add_activity(activities, day, "hang_laundry", ["balcony"], "11:30", 30)
    add_lunch(activities, day, "13:00", "kitchen")
    extra = (
        "evening_walk",
        "18:15",
        ["outside"],
        45 if day.day == 15 else 35,
    )
    leisure = ["watch_documentary", "read_in_bed", "watch_television"][day.day % 3]
    add_evening(activities, day, weekend=True, leisure_intent=leisure, extra=extra)


def add_sunday(activities: list[dict[str, Any]], day: date) -> None:
    add_morning(activities, day, weekend=True)
    add_activity(activities, day, "long_sunday_walk", ["outside"], "10:00", 80)
    add_lunch(activities, day, "13:00", "kitchen")
    add_activity(
        activities,
        day,
        "weekly_meal_preparation",
        ["kitchen"],
        "16:00",
        90,
        resources=["fridge_01", "stove_01"],
    )
    extras = [
        ("call_mother", "18:00", ["living_room"], 25),
        ("rest", "18:00", ["bedroom"], 35),
        ("tidy_living_room_and_hallway", "18:00", ["living_room", "hallway"], 30),
    ]
    leisure = ["watch_sunday_program", "read", "watch_documentary"][day.day % 3]
    add_evening(
        activities,
        day,
        weekend=True,
        leisure_intent=leisure,
        extra=extras[day.day % 3],
        late_sleep=False,
    )


VACATION_EVENTS: dict[int, list[tuple[str, str, list[str], int]]] = {
    10: [("clean_kitchen", "10:00", ["kitchen"], 45), ("read", "16:00", ["bedroom"], 50)],
    11: [("start_laundry", "09:45", ["bathroom"], 20), ("hang_laundry", "11:30", ["balcony"], 30)],
    12: [
        ("travel_to_supermarket", "09:35", ["supermarket"], 25),
        ("buy_groceries", "10:05", ["supermarket"], 45),
        ("return_home_and_store_purchases", "11:00", ["home"], 40),
    ],
    13: [("indoor_light_exercise", "10:00", ["living_room"], 35), ("clean_bathroom", "11:00", ["bathroom"], 40)],
    14: [("tidy_living_room_and_hallway", "10:00", ["living_room", "hallway"], 40), ("call_mother", "16:30", ["living_room"], 25)],
    17: [("short_evening_walk", "10:00", ["outside"], 40), ("read_and_rest", "16:00", ["bedroom"], 55)],
    18: [("start_laundry", "09:45", ["bathroom"], 20), ("hang_laundry", "11:30", ["balcony"], 30)],
    19: [
        ("travel_to_supermarket", "09:35", ["supermarket"], 25),
        ("buy_groceries", "10:05", ["supermarket"], 45),
        ("return_home_and_store_purchases", "11:00", ["home"], 40),
    ],
    20: [("clean_kitchen", "10:00", ["kitchen"], 45), ("read", "16:00", ["bedroom"], 50)],
    21: [("take_recycling_out", "10:00", ["home", "outside"], 30), ("call_friend_paolo", "16:30", ["living_room"], 25)],
}


def add_vacation_day(activities: list[dict[str, Any]], day: date) -> None:
    add_morning(activities, day, weekend=False)
    for intent, clock, locations, duration in VACATION_EVENTS[day.day]:
        resources = None
        if intent == "start_laundry":
            resources = ["washing_machine_01"]
        elif intent == "return_home_and_store_purchases":
            resources = ["fridge_01"]
        add_activity(
            activities,
            day,
            intent,
            locations,
            clock,
            duration,
            resources=resources,
        )
    add_lunch(activities, day, "13:00", "kitchen")
    leisure = ["read_in_bed", "watch_documentary", "read_and_rest"][day.day % 3]
    add_evening(activities, day, weekend=False, leisure_intent=leisure)


def build_days() -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    current = date(2026, 8, 1)
    while current <= date(2026, 8, 31):
        activities: list[dict[str, Any]] = []
        if current.weekday() == 5:
            add_saturday(activities, current)
        elif current.weekday() == 6:
            add_sunday(activities, current)
        elif 10 <= current.day <= 21:
            add_vacation_day(activities, current)
        elif current.weekday() in {0, 2, 4}:
            add_office_day(activities, current)
        else:
            add_remote_day(activities, current)
        days.append(
            {
                "date": current.isoformat(),
                "context": {
                    "dayType": "weekend" if current.weekday() >= 5 else "weekday",
                    "facts": {
                        "publicHoliday": current == date(2026, 8, 15),
                        "onAnnualLeave": date(2026, 8, 10) <= current <= date(2026, 8, 21),
                    },
                },
                "activities": activities,
            }
        )
        current += timedelta(days=1)
    return days


def action_arguments(action_type: str, component: str, intent: str, occurrence: int) -> dict[str, Any]:
    if action_type in {"move_to", "travel_to"}:
        return {"destination": {"source": "activity_location", "index": 0}}
    if action_type in {"leave_home", "enter_home"}:
        return {}
    if action_type == "change_posture":
        if component == "sleep":
            posture = "lying"
        elif component == "wake_up":
            posture = "standing"
        elif component in {"rest", "nap"}:
            posture = "lying"
        elif occurrence % 2:
            posture = "sitting"
        else:
            posture = "standing"
        return {"posture": value(posture)}
    if action_type in {"open", "close"}:
        return {"target": value("fridge_01")}
    if action_type in {"activate", "deactivate"}:
        if component == "shower":
            target = "shower_01"
        elif component in {"wash_face", "wash_dishes"}:
            target = "kitchen_sink_01"
        elif component == "watch_media":
            target = "television_01"
        elif component == "prepare_drink":
            target = "kettle_01"
        else:
            target = "stove_01"
        return {"target": value(target)}
    if action_type in {"take_item", "put_item"}:
        if component == "change_clothes":
            role = "clothing_storage"
        elif component in {"collect_medication", "take_medication"}:
            role = "medication_storage"
        elif component in {"prepare_food", "carry_purchases"}:
            role = "food_storage"
        else:
            role = "utensils"
        return {"itemRole": value(role)}
    if action_type == "inspect":
        return {"targetRole": value("calendar" if component == "check_calendar" else "supplies")}
    if action_type == "consume":
        kind = "drink" if component == "consume_drink" else "snack" if component == "consume_snack" else "meal"
        return {"itemRole": value(kind)}
    if action_type == "personal_care":
        procedure = "toilet" if component == "use_toilet" else "shower" if component == "shower" else "hygiene"
        return {"procedure": value(procedure)}
    if action_type == "clean":
        if component == "wash_dishes":
            target = "dishes"
        elif "kitchen" in intent:
            target = "countertop"
        else:
            target = "floor"
        return {"targetRole": value(target)}
    if action_type == "laundry_step":
        operation = {
            "collect_laundry": "collect",
            "load_laundry": "load",
            "start_laundry": "start",
            "hang_laundry": "hang",
            "iron_laundry": "iron",
        }[component]
        return {"operation": value(operation)}
    if action_type == "organize":
        target = "documents" if component == "organize_documents" else "clothes" if component in {"organize_clothes", "portion_food"} else "bag"
        return {"targetRole": value(target)}
    if action_type == "dress":
        return {"purpose": value("work_wear" if "work" in intent else "daily_clothing")}
    if action_type == "manage_medication":
        return {"operation": value("refill" if component == "collect_medication" else "take_dose")}
    if action_type == "wait":
        purpose = "sleeping" if component == "sleep" else "napping" if component == "nap" else "resting"
        return {"purpose": value(purpose)}
    if action_type == "shop":
        return {"purpose": value("supplies" if "supplies" in intent else "groceries")}
    if action_type == "communicate":
        return {"channel": value("in_person" if component == "socialize_in_person" else "phone")}
    if action_type == "perform_work":
        return {"mode": value("desk_work")}
    if action_type == "exercise":
        return {"kind": value("walking" if component == "walk" else "light_stretching")}
    if action_type == "leisure":
        kind = "watching_tv" if component == "watch_media" else "radio" if component == "listen_radio" else "reading"
        return {"kind": value(kind)}
    if action_type == "prepare_food":
        meal = "breakfast" if "breakfast" in intent else "lunch" if "lunch" in intent else "dinner"
        return {"mealKind": value(meal)}
    if action_type == "put_item":
        return {"itemRole": value("utensils")}
    raise ValueError(f"No argument mapping for action type {action_type!r}")


def action_flow(
    intent: str,
    components: list[str],
    component_actions: dict[str, list[str]],
) -> list[tuple[str, dict[str, Any]]]:
    expanded: list[tuple[str, str]] = []
    for component in components:
        expanded.extend((component, action_type) for action_type in component_actions[component])
    if not expanded or expanded[0][1] not in {"move_to", "move_to_capability", "travel_to"}:
        expanded.insert(0, ("movement", "move_to"))
    occurrences: dict[tuple[str, str], int] = {}
    flow: list[tuple[str, dict[str, Any]]] = []
    for component, action_type in expanded:
        key = (component, action_type)
        occurrences[key] = occurrences.get(key, 0) + 1
        flow.append(
            (
                action_type,
                action_arguments(action_type, component, intent, occurrences[key]),
            )
        )
    return flow


def build_process_package(days: list[dict[str, Any]], provenance: dict[str, Any]) -> dict[str, Any]:
    catalog = json.loads(ACTIVITY_CATALOG.read_text(encoding="utf-8"))
    intent_components = {
        item["intent"]: item["components"] for item in catalog["activities"]
    }
    component_actions = {
        item["componentId"]: item["requiredActionTypes"] for item in catalog["components"]
    }
    used_intents = sorted(
        {item["intent"] for day in days for item in day["activities"]}
    )
    missing = sorted(set(used_intents) - set(intent_components))
    if missing:
        raise ValueError(f"Unknown intents: {missing}")

    models: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    model_for_signature: dict[str, str] = {}
    for intent in used_intents:
        components = intent_components[intent]
        flow = action_flow(intent, components, component_actions)
        signature = json.dumps([components, flow], ensure_ascii=False, sort_keys=True)
        process_model_id = model_for_signature.get(signature)
        if process_model_id is None:
            process_model_id = f"pm_lucia_{len(models) + 1:02d}"
            model_for_signature[signature] = process_model_id
            nodes: list[dict[str, Any]] = [{"nodeId": "start", "kind": "start"}]
            for index, (action_type, arguments) in enumerate(flow, start=1):
                nodes.append(
                    {
                        "nodeId": f"action_{index:02d}",
                        "kind": "action",
                        "actionType": action_type,
                        "arguments": arguments,
                        "durationWeight": 1,
                    }
                )
            nodes.append({"nodeId": "end", "kind": "end"})
            edges = [
                {"sourceNodeId": nodes[index]["nodeId"], "targetNodeId": nodes[index + 1]["nodeId"]}
                for index in range(len(nodes) - 1)
            ]
            models.append(
                {
                    "processModelId": process_model_id,
                    "processModelVersion": "1.0.0",
                    "residentId": RESIDENT_ID,
                    "title": f"Lucia process model {len(models) + 1}",
                    "description": f"Primitive action flow first introduced for intent {intent}.",
                    "implementedComponents": components,
                    "nodes": nodes,
                    "edges": edges,
                }
            )
        bindings.append(
            {
                "bindingId": f"bind_lucia_{intent}",
                "residentId": RESIDENT_ID,
                "intent": intent,
                "processModelId": process_model_id,
            }
        )
    return {
        "schemaVersion": "1.0.0",
        "documentType": "personal_process_package",
        "packageId": "lucia_rossi_august_2026_processes",
        "packageVersion": "1.0.0",
        "sourceScenarioId": SCENARIO_ID,
        "sourceScenarioVersion": "1.0.0",
        "language": "it",
        "provenance": provenance,
        "catalogs": {
            "activityCatalog": {"catalogId": "smart_home_activity_catalog", "version": "1.0.0"},
            "variableCatalog": {"catalogId": "smart_home_variable_catalog", "version": "1.0.0"},
            "actionCatalog": {"catalogId": "smart_home_action_catalog", "version": "1.0.0"},
        },
        "processModels": models,
        "bindings": bindings,
    }


def build_bundle(generated_at: str) -> dict[str, Any]:
    provenance = {
        "authorType": "external_llm",
        "generatorName": "smart-home-simulator-external-llm-authoring",
        "generatorVersion": "1.2.0",
        "promptTemplateVersion": "generate-simulation-inputs-1.2.1-simplified",
        "humanReviewed": False,
        "modelName": "gpt-5-codex",
        "generatedAt": generated_at,
    }
    days = build_days()
    locations = [
        {"locationId": "bedroom", "kind": "room"},
        {"locationId": "bathroom", "kind": "room"},
        {"locationId": "hallway", "kind": "room"},
        {"locationId": "entrance", "kind": "room"},
        {"locationId": "kitchen", "kind": "room"},
        {"locationId": "living_room", "kind": "room"},
        {"locationId": "balcony", "kind": "room"},
        {
            "locationId": "home",
            "kind": "composite",
            "memberLocationIds": [
                "entrance",
                "hallway",
                "bedroom",
                "bathroom",
                "kitchen",
                "living_room",
                "balcony",
            ],
        },
        {"locationId": "outside", "kind": "external"},
        {"locationId": "supermarket", "kind": "external"},
        {"locationId": "workplace", "kind": "external"},
    ]
    resources = [
        {"resourceId": "bed_01", "resourceType": "bed", "locationId": "bedroom", "capacity": 1},
        {"resourceId": "shower_01", "resourceType": "shower", "locationId": "bathroom", "capacity": 1},
        {"resourceId": "toilet_01", "resourceType": "toilet", "locationId": "bathroom", "capacity": 1},
        {"resourceId": "washing_machine_01", "resourceType": "washing_machine", "locationId": "bathroom", "capacity": 1},
        {"resourceId": "kitchen_sink_01", "resourceType": "sink", "locationId": "kitchen", "capacity": 1},
        {"resourceId": "fridge_01", "resourceType": "refrigerator", "locationId": "kitchen", "capacity": 1},
        {"resourceId": "kettle_01", "resourceType": "kettle", "locationId": "kitchen", "capacity": 1},
        {"resourceId": "stove_01", "resourceType": "stove", "locationId": "kitchen", "capacity": 1},
        {"resourceId": "television_01", "resourceType": "television", "locationId": "living_room", "capacity": 1},
    ]
    scenario = {
        "schemaVersion": "1.0.0",
        "documentType": "life_scenario",
        "scenarioId": SCENARIO_ID,
        "title": "Agosto 2026 di Lucia Rossi nella casa di Mario a Monteverde",
        "language": "it",
        "timeZone": "Europe/Rome",
        "simulationWindow": {
            "start": f"2026-08-01T00:00:00{OFFSET}",
            "end": f"2026-08-31T23:59:59{OFFSET}",
        },
        "seed": 20260831,
        "provenance": provenance,
        "modelReferences": {
            "activityCatalog": {"referenceId": "smart_home_activity_catalog", "version": "1.0.0"},
            "homeModel": {
                "referenceId": "home_mario_monteverde",
                "version": "mario-apartment-0.1-example",
            },
        },
        "residents": [
            {
                "residentId": RESIDENT_ID,
                "displayName": "Lucia Rossi",
                "profile": {
                    "age": 45,
                    "gender": "female",
                    "occupation": "hybrid administrative employee",
                    "healthConditions": [],
                    "medication": [],
                    "chronotype": "intermediate",
                    "stressLevel": 0.35,
                    "relationshipToMario": "daughter",
                    "household": "lives_with_father_mario_in_monteverde",
                    "annualLeave": "2026-08-10/2026-08-21",
                },
            }
        ],
        "locations": locations,
        "resources": resources,
        "initialState": {
            "at": f"2026-08-01T00:00:00{OFFSET}",
            "residents": [
                {
                    "residentId": RESIDENT_ID,
                    "locationId": "bedroom",
                    "facts": {"awake": False, "posture": "lying", "atHome": True},
                }
            ],
        },
        "days": days,
    }
    return {
        "schemaVersion": "1.0.0",
        "documentType": "simulation_authoring_bundle",
        "scenario": scenario,
        "personalProcessPackage": build_process_package(days, provenance),
    }


def main() -> int:
    args = parse_args()
    generated_at = datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="seconds")
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_bundle(generated_at)
    (output_dir / "authoring-bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    case = CASE_TEMPLATE.read_text(encoding="utf-8").replace(
        "[GENERATION_TIMESTAMP]", generated_at
    )
    (output_dir / "case-description.md").write_text(case, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_dir / "authoring-bundle.json"),
                "generatedAt": generated_at,
                "days": len(bundle["scenario"]["days"]),
                "activities": sum(
                    len(day["activities"]) for day in bundle["scenario"]["days"]
                ),
                "processModels": len(bundle["personalProcessPackage"]["processModels"]),
                "bindings": len(bundle["personalProcessPackage"]["bindings"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
