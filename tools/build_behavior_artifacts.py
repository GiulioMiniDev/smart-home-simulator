from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
CATALOG_DIR = ROOT / "src/smart_home_sim/catalogs"
BEHAVIOR_EXAMPLE_DIR = ROOT / "examples/behavior"
BASE_SCENARIO_PATHS = (
    ROOT / "examples/valid/mario_week.json",
    ROOT / "examples/valid/minimal.json",
)

CATEGORY_DESCRIPTIONS = {
    "communication": "Communicate or maintain a social relationship.",
    "dressing": "Dress, change clothes, or prepare clothing and personal belongings.",
    "eating": "Consume a meal, snack, or drink.",
    "errand": "Acquire goods, medication, or household supplies outside the home.",
    "exercise": "Perform intentional physical exercise or walking.",
    "housekeeping": "Clean, tidy, maintain, or organize the home.",
    "hygiene": "Perform personal hygiene or bathroom care.",
    "laundry": "Wash, dry, hang, or iron clothing and household textiles.",
    "leisure": "Rest, read, watch media, or perform another leisure activity.",
    "meal_preparation": "Prepare, cook, reheat, portion, or store food and drinks.",
    "medication": "Take, collect, or manage medication.",
    "sleep": "Enter, leave, or maintain a sleeping state.",
    "social_visit": "Travel for or participate in an in-person social visit.",
    "travel": "Enter, leave, or travel between declared locations.",
    "work": "Perform paid work or prepare directly for a work commitment.",
}

# This table is deliberately explicit. The scenario intent remains the stable project
# label, while components make compound intents executable instead of treating their
# prose-like name as one opaque action.
INTENT_COMPONENTS: dict[str, list[str]] = {
    "aperitivo_with_paolo": ["socialize_in_person", "consume_drink"],
    "buy_fresh_food_and_household_supplies": ["shop", "carry_purchases"],
    "buy_groceries": ["shop", "carry_purchases"],
    "call_friend_paolo": ["phone_call"],
    "call_mother": ["phone_call"],
    "call_sister_lucia": ["phone_call"],
    "change_clothes": ["change_clothes"],
    "change_clothes_and_eat_snack": ["change_clothes", "consume_snack"],
    "change_clothes_and_have_coffee": ["change_clothes", "consume_drink"],
    "change_clothes_and_have_snack": ["change_clothes", "consume_snack"],
    "check_calendar_and_household_supplies": ["check_calendar", "inspect_supplies"],
    "clean_bathroom": ["clean_surface"],
    "clean_kitchen": ["clean_surface"],
    "collect_belongings_and_leave_home": ["collect_belongings", "leave_home"],
    "collect_medication_refill": ["collect_medication"],
    "commute_home": ["travel", "enter_home"],
    "commute_to_work": ["travel"],
    "complete_pending_dishwashing": ["wash_dishes"],
    "cook_chicken_and_vegetables": ["prepare_food"],
    "cook_dinner": ["prepare_food"],
    "dress_for_work": ["change_clothes"],
    "eat_afternoon_snack": ["consume_snack"],
    "eat_breakfast": ["consume_meal"],
    "eat_breakfast_and_listen_to_radio": ["consume_meal", "listen_radio"],
    "eat_breakfast_and_read_news": ["consume_meal", "read_news"],
    "eat_breakfast_with_radio_news": ["consume_meal", "listen_radio"],
    "eat_dinner": ["consume_meal"],
    "eat_light_dinner": ["consume_meal"],
    "eat_lunch": ["consume_meal"],
    "evening_hygiene": ["personal_hygiene"],
    "evening_walk": ["walk"],
    "go_to_neighborhood_market": ["travel"],
    "hang_bed_linen": ["hang_laundry"],
    "hang_laundry": ["hang_laundry"],
    "indoor_light_exercise": ["exercise"],
    "iron_work_shirts": ["iron_laundry"],
    "leave_home": ["leave_home"],
    "long_sunday_walk": ["walk"],
    "morning_toilet_and_shower": ["use_toilet", "shower"],
    "morning_toilet_and_wash": ["use_toilet", "wash_face"],
    "portion_and_store_prepared_food": ["portion_food", "store_food"],
    "post_walk_shower": ["shower"],
    "prepare_and_eat_breakfast": ["prepare_food", "consume_meal"],
    "prepare_breakfast": ["prepare_food"],
    "prepare_coffee_and_drink_on_balcony": ["prepare_drink", "consume_drink"],
    "prepare_friday_clothes_and_bag": ["organize_clothes", "organize_bag"],
    "prepare_light_dinner": ["prepare_food"],
    "prepare_monday_clothes_bag_and_documents": [
        "organize_clothes",
        "organize_bag",
        "organize_documents",
    ],
    "prepare_next_workday": ["organize_clothes", "organize_bag"],
    "prepare_next_workday_clothes_and_bag": ["organize_clothes", "organize_bag"],
    "prepare_quick_pasta_and_salad": ["prepare_food", "prepare_salad"],
    "prepare_rice_and_vegetables": ["prepare_food"],
    "prepare_simple_lunch": ["prepare_food"],
    "prepare_sunday_lunch": ["prepare_food"],
    "prepare_to_visit_mother": ["change_clothes", "collect_belongings"],
    "prepare_weekend_breakfast": ["prepare_food"],
    "put_groceries_away": ["store_purchases"],
    "read": ["read"],
    "read_and_rest": ["read", "rest"],
    "read_in_bed": ["read_in_bed"],
    "reheat_leftover_dinner_and_prepare_salad": ["reheat_food", "prepare_salad"],
    "rest": ["rest"],
    "rest_and_read": ["rest", "read"],
    "rest_or_nap": ["rest", "nap"],
    "return_home_and_store_purchases": ["travel", "enter_home", "store_purchases"],
    "short_evening_walk": ["walk"],
    "shower_and_get_ready_to_go_out": ["shower", "change_clothes"],
    "sleep": ["sleep"],
    "start_bed_linen_laundry": ["collect_laundry", "load_laundry", "start_laundry"],
    "start_laundry": ["collect_laundry", "load_laundry", "start_laundry"],
    "take_morning_medication": ["take_medication"],
    "take_recycling_out": ["carry_recycling", "leave_home", "discard_recycling"],
    "tidy_living_room_and_hallway": ["tidy_area"],
    "travel_home": ["travel", "enter_home"],
    "travel_to_mothers_home": ["travel"],
    "travel_to_neighborhood_bar": ["travel"],
    "travel_to_pharmacy": ["travel"],
    "travel_to_supermarket": ["travel"],
    "vacuum_and_dust_apartment": ["vacuum", "dust"],
    "visit_mother_and_have_dinner": ["socialize_in_person", "consume_meal"],
    "wake_up": ["wake_up"],
    "wake_up_without_alarm": ["wake_up"],
    "wash_breakfast_dishes": ["wash_dishes"],
    "wash_face_and_change_shirt": ["wash_face", "change_clothes"],
    "watch_documentary": ["watch_media"],
    "watch_evening_television": ["watch_media"],
    "watch_football_highlights": ["watch_media"],
    "watch_late_news": ["watch_media"],
    "watch_sunday_program": ["watch_media"],
    "watch_television": ["watch_media"],
    "weekly_meal_preparation": ["prepare_food", "portion_food", "store_food"],
    "work_shift": ["work"],
}

COMPONENT_CATEGORIES = {
    "phone_call": "communication",
    "socialize_in_person": "social_visit",
    "change_clothes": "dressing",
    "organize_clothes": "dressing",
    "consume_meal": "eating",
    "consume_snack": "eating",
    "consume_drink": "eating",
    "shop": "errand",
    "collect_medication": "medication",
    "walk": "exercise",
    "exercise": "exercise",
    "clean_surface": "housekeeping",
    "wash_dishes": "housekeeping",
    "tidy_area": "housekeeping",
    "vacuum": "housekeeping",
    "use_toilet": "hygiene",
    "shower": "hygiene",
    "wash_face": "hygiene",
    "personal_hygiene": "hygiene",
    "collect_laundry": "laundry",
    "hang_laundry": "laundry",
    "iron_laundry": "laundry",
    "read": "leisure",
    "read_in_bed": "sleep",
    "rest": "leisure",
    "nap": "sleep",
    "watch_media": "leisure",
    "prepare_food": "meal_preparation",
    "prepare_drink": "meal_preparation",
    "reheat_food": "meal_preparation",
    "take_medication": "medication",
    "sleep": "sleep",
    "wake_up": "sleep",
    "travel": "travel",
    "leave_home": "travel",
    "work": "work",
}


def category_for(intent: str) -> str:
    components = INTENT_COMPONENTS.get(intent)
    if components:
        for component in components:
            if component in COMPONENT_CATEGORIES:
                return COMPONENT_CATEGORIES[component]
    if any(token in intent for token in ("sleep", "wake_up", "nap", "read_in_bed")):
        return "sleep"
    if any(token in intent for token in ("shower", "toilet", "hygiene", "wash_face", "get_ready")):
        return "hygiene"
    if "medication" in intent:
        return "medication"
    if any(token in intent for token in ("laundry", "linen", "iron_work")):
        return "laundry"
    if any(
        token in intent
        for token in (
            "prepare_breakfast",
            "prepare_weekend_breakfast",
            "prepare_and_eat_breakfast",
            "prepare_coffee",
            "prepare_light_dinner",
            "prepare_quick_pasta",
            "prepare_rice",
            "prepare_simple_lunch",
            "prepare_sunday_lunch",
            "cook_",
            "reheat_",
            "weekly_meal_preparation",
            "portion_and_store",
        )
    ):
        return "meal_preparation"
    if any(
        token in intent
        for token in (
            "eat_",
            "have_coffee",
            "have_snack",
            "aperitivo",
            "eat_breakfast",
        )
    ):
        return "eating"
    if any(token in intent for token in ("work_shift", "dress_for_work")):
        return "work"
    if any(token in intent for token in ("visit_mother", "travel_to_mothers")):
        return "social_visit"
    if any(token in intent for token in ("call_", "travel_to_neighborhood_bar")):
        return "communication"
    if any(
        token in intent
        for token in (
            "commute_",
            "travel_",
            "leave_home",
            "return_home",
            "collect_belongings_and_leave",
        )
    ):
        return "travel"
    if any(
        token in intent
        for token in (
            "buy_",
            "market",
            "supermarket",
            "pharmacy",
            "groceries",
            "purchases",
        )
    ):
        return "errand"
    if any(token in intent for token in ("walk", "exercise")):
        return "exercise"
    if any(
        token in intent
        for token in (
            "clean_",
            "tidy_",
            "vacuum_",
            "wash_breakfast_dishes",
            "dishwashing",
            "recycling",
            "put_groceries_away",
        )
    ):
        return "housekeeping"
    if any(
        token in intent
        for token in (
            "change_clothes",
            "prepare_friday_clothes",
            "prepare_monday_clothes",
            "prepare_next_workday",
        )
    ):
        return "dressing"
    return "leisure"


def external_mapping(category: str, intent: str) -> dict[str, str]:
    mappings = {
        "meal_preparation": "Meal_Preparation",
        "eating": "Eating",
        "leisure": "Relax",
        "work": "Work",
        "sleep": "Sleeping",
        "housekeeping": "Housekeeping",
    }
    if intent == "leave_home" or "leave_home" in intent:
        return {"casas_aruba": "Leave_Home"}
    if intent.startswith("return_home"):
        return {"casas_aruba": "Enter_Home"}
    if "dish" in intent:
        return {"casas_aruba": "Wash_Dishes"}
    return {"casas_aruba": mappings[category]} if category in mappings else {}


def relevant_variables(category: str, components: list[str]) -> list[str]:
    values = {
        "resident.age",
        "resident.mobility_profile",
        "day.type",
        "calendar.season",
    }
    category_variables = {
        "communication": {"resident.social_need", "resident.stress"},
        "dressing": {"resident.health_conditions"},
        "eating": {"resident.hunger", "resident.food_inventory"},
        "errand": {"day.weather", "resident.food_inventory"},
        "exercise": {"resident.fatigue", "day.weather"},
        "housekeeping": {"resident.fatigue"},
        "hygiene": {"resident.health_conditions"},
        "laundry": {"day.weather"},
        "leisure": {"resident.fatigue", "resident.stress"},
        "meal_preparation": {"resident.hunger", "resident.food_inventory"},
        "medication": {
            "resident.health_conditions",
            "resident.medication_available_doses",
        },
        "sleep": {"resident.fatigue", "resident.chronotype"},
        "social_visit": {"resident.social_need", "day.weather"},
        "travel": {"resident.walking_speed", "day.weather"},
        "work": {"resident.stress", "resident.fatigue"},
    }
    values.update(category_variables[category])
    if "prepare_drink" in components:
        values.add("resident.preferred_breakfast_drink")
    return sorted(values)


def load_scenarios() -> list[dict[str, Any]]:
    # M3's frozen catalogs and packages derive only from its accepted base corpus.
    # Later milestone scenarios are explicit migrations and must not silently expand
    # or duplicate this generator's output set.
    return [json.loads(path.read_text(encoding="utf-8")) for path in BASE_SCENARIO_PATHS]


def activity_catalog(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    intents = sorted(
        {
            activity["intent"]
            for scenario in scenarios
            for day in scenario["days"]
            for activity in day["activities"]
        }
    )
    missing_decompositions = set(intents) - set(INTENT_COMPONENTS)
    stale_decompositions = set(INTENT_COMPONENTS) - set(intents)
    if missing_decompositions or stale_decompositions:
        raise ValueError(
            "Activity decomposition table is not synchronized with valid scenarios: "
            f"missing={sorted(missing_decompositions)}, stale={sorted(stale_decompositions)}"
        )
    activities = []
    for intent in intents:
        category = category_for(intent)
        activities.append(
            {
                "intent": intent,
                "displayName": intent.replace("_", " ").title(),
                "description": (
                    f"Project-specific activity intent '{intent}'. "
                    f"{CATEGORY_DESCRIPTIONS[category]}"
                ),
                "category": category,
                "components": INTENT_COMPONENTS[intent],
                "relevantVariableIds": relevant_variables(
                    category,
                    INTENT_COMPONENTS[intent],
                ),
                "externalMappings": external_mapping(category, intent),
            }
        )
    return {
        "schemaVersion": "1.0.0",
        "documentType": "activity_catalog",
        "catalogId": "smart_home_activity_catalog",
        "catalogVersion": "1.0.0",
        "components": [
            {
                "componentId": component,
                "description": (
                    f"Semantic component '{component}' implemented at the project trace "
                    "granularity by its ordered required actions."
                ),
                "requiredActionTypes": [
                    action_type
                    for action_type, _ in component_steps(component)
                    if action_type not in {"move_to", "move_to_capability"}
                ],
            }
            for component in sorted(
                {item for values in INTENT_COMPONENTS.values() for item in values}
            )
        ],
        "activities": activities,
    }


def variable_catalog() -> dict[str, Any]:
    variables = [
        ("resident.age", "Age", "integer", "resident", "age", False, []),
        (
            "resident.household",
            "Household composition",
            "string",
            "resident",
            "household",
            False,
            [],
        ),
        (
            "resident.health_conditions",
            "Health conditions",
            "array",
            "resident",
            "health.conditions",
            False,
            [],
        ),
        (
            "resident.mobility_profile",
            "Mobility profile",
            "string",
            "resident",
            "mobility.profile",
            False,
            [],
        ),
        (
            "resident.walking_speed",
            "Walking speed",
            "number",
            "resident",
            "mobility.walkingSpeedMetersPerSecond",
            False,
            [],
        ),
        (
            "resident.chronotype",
            "Chronotype",
            "string",
            "resident",
            "preferences.chronotype",
            False,
            [],
        ),
        (
            "resident.preferred_breakfast_drink",
            "Preferred breakfast drink",
            "string",
            "resident",
            "preferences.breakfastDrink",
            False,
            ["coffee", "tea", "cold_drink"],
        ),
        ("resident.fatigue", "Fatigue", "number", "initial_state", "fatigue", False, []),
        ("resident.hunger", "Hunger", "number", "initial_state", "hunger", False, []),
        ("resident.stress", "Stress", "number", "initial_state", "stress", False, []),
        (
            "resident.social_need",
            "Social need",
            "number",
            "initial_state",
            "socialNeed",
            False,
            [],
        ),
        (
            "resident.food_inventory",
            "Food inventory",
            "object",
            "initial_state",
            "foodInventory",
            False,
            [],
        ),
        (
            "resident.medication_available_doses",
            "Medication available doses",
            "integer",
            "initial_state",
            "medicationAvailableDoses",
            False,
            [],
        ),
        ("day.type", "Day type", "string", "day", "dayType", True, []),
        ("day.weather", "Weather", "string", "day", "facts.weather", False, []),
        (
            "day.public_holiday",
            "Public holiday",
            "boolean",
            "day",
            "facts.publicHoliday",
            False,
            [],
        ),
        (
            "calendar.weekday",
            "Weekday",
            "integer",
            "derived_calendar",
            "weekday",
            True,
            list(range(7)),
        ),
        (
            "calendar.season",
            "Season",
            "string",
            "derived_calendar",
            "season",
            True,
            ["winter", "spring", "summer", "autumn"],
        ),
    ]
    return {
        "schemaVersion": "1.0.0",
        "documentType": "variable_catalog",
        "catalogId": "smart_home_variable_catalog",
        "catalogVersion": "1.0.0",
        "variables": [
            {
                "variableId": variable_id,
                "displayName": display_name,
                "description": f"Authoritative behavioral variable: {display_name.lower()}.",
                "valueType": value_type,
                "scope": scope,
                "sourcePath": source_path,
                "required": required,
                "allowedValues": allowed_values,
            }
            for (
                variable_id,
                display_name,
                value_type,
                scope,
                source_path,
                required,
                allowed_values,
            ) in variables
        ],
    }


def parameter(
    name: str,
    value_type: str = "string",
    *,
    reference_kind: str = "none",
    allowed_values: list[Any] | None = None,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "parameterName": name,
        "description": f"Typed parameter '{name}'.",
        "valueType": value_type,
        "required": required,
        "referenceKind": reference_kind,
        "allowedValues": allowed_values or [],
    }


def action_catalog() -> dict[str, Any]:
    definitions = {
        "move_to": [parameter("destination", reference_kind="location")],
        "move_to_capability": [parameter("targetRole", reference_kind="capability")],
        "change_posture": [
            parameter(
                "posture",
                allowed_values=["standing", "walking", "sitting", "lying"],
            )
        ],
        "open": [parameter("target", reference_kind="environment_entity")],
        "close": [parameter("target", reference_kind="environment_entity")],
        "take_item": [parameter("itemRole", reference_kind="capability")],
        "put_item": [parameter("itemRole", reference_kind="capability")],
        "activate": [parameter("target", reference_kind="environment_entity")],
        "deactivate": [parameter("target", reference_kind="environment_entity")],
        "wait": [parameter("purpose")],
        "inspect": [parameter("targetRole", reference_kind="capability")],
        "consume": [parameter("itemRole", reference_kind="capability")],
        "personal_care": [parameter("procedure")],
        "clean": [parameter("targetRole", reference_kind="capability")],
        "laundry_step": [
            parameter(
                "operation",
                allowed_values=["collect", "load", "start", "unload", "hang", "iron"],
            )
        ],
        "organize": [parameter("targetRole", reference_kind="capability")],
        "dress": [parameter("purpose")],
        "manage_medication": [parameter("operation", allowed_values=["take", "refill", "store"])],
        "leave_home": [],
        "enter_home": [],
        "travel_to": [parameter("destination", reference_kind="location")],
        "shop": [parameter("purpose")],
        "communicate": [parameter("channel", allowed_values=["phone", "in_person"])],
        "perform_work": [parameter("mode")],
        "exercise": [parameter("kind")],
        "leisure": [parameter("kind")],
        "prepare_food": [parameter("mealKind")],
    }
    capability_specs: dict[str, list[tuple[str, str, str | None]]] = {
        "move_to": [("destination", "reachable", "destination")],
        "move_to_capability": [("target", "interaction_point", "targetRole")],
        "change_posture": [("resident", "posture_control", None)],
        "open": [("target", "openable", "target")],
        "close": [("target", "openable", "target")],
        "take_item": [("item", "graspable", "itemRole")],
        "put_item": [("item", "storable", "itemRole")],
        "activate": [("target", "switchable", "target")],
        "deactivate": [("target", "switchable", "target")],
        "wait": [],
        "inspect": [("target", "inspectable", "targetRole")],
        "consume": [("item", "consumable", "itemRole")],
        "personal_care": [("fixture", "personal_care_support", None)],
        "clean": [("target", "cleanable", "targetRole")],
        "laundry_step": [("equipment", "laundry_support", None)],
        "organize": [("target", "storage_support", "targetRole")],
        "dress": [("item", "wearable", None)],
        "manage_medication": [("item", "medication_support", None)],
        "leave_home": [("access", "home_egress", None)],
        "enter_home": [("access", "home_ingress", None)],
        "travel_to": [("destination", "transport_reachable", "destination")],
        "shop": [("place", "retail_service", None)],
        "communicate": [("channel", "communication", "channel")],
        "perform_work": [("place", "work_support", None)],
        "exercise": [("place", "exercise_support", None)],
        "leisure": [("medium", "leisure_support", None)],
        "prepare_food": [("equipment", "food_preparation", None)],
    }
    preconditions = {
        "open": [("entity.{target}.open", "eq", False)],
        "close": [("entity.{target}.open", "eq", True)],
        "take_item": [("capability.{itemRole}.available", "eq", True)],
        "put_item": [("resident.carrying.{itemRole}", "eq", True)],
        "activate": [("entity.{target}.active", "eq", False)],
        "deactivate": [("entity.{target}.active", "eq", True)],
        "consume": [("capability.{itemRole}.available", "eq", True)],
        "enter_home": [("resident.at_home", "eq", False)],
        "leave_home": [("resident.at_home", "eq", True)],
    }
    effects = {
        "move_to": [("resident.location", "set", "{destination}")],
        "move_to_capability": [("resident.location", "set", "{targetRole}")],
        "change_posture": [("resident.posture", "set", "{posture}")],
        "open": [("entity.{target}.open", "set", True)],
        "close": [("entity.{target}.open", "set", False)],
        "take_item": [("resident.carrying.{itemRole}", "set", True)],
        "put_item": [("resident.carrying.{itemRole}", "set", False)],
        "activate": [("entity.{target}.active", "set", True)],
        "deactivate": [("entity.{target}.active", "set", False)],
        "consume": [("capability.{itemRole}.consumed", "increment", 1)],
        "leave_home": [("resident.at_home", "set", False)],
        "enter_home": [("resident.at_home", "set", True)],
        "travel_to": [("resident.location", "set", "{destination}")],
    }
    return {
        "schemaVersion": "1.0.0",
        "documentType": "action_catalog",
        "catalogId": "smart_home_action_catalog",
        "catalogVersion": "1.0.0",
        "actions": [
            {
                "actionType": action_type,
                "description": f"Execute the typed atomic action '{action_type}'.",
                "parameters": parameters,
                "requiredCapabilities": [
                    {
                        "role": role,
                        "capability": capability,
                        **({"parameterName": parameter_name} if parameter_name else {}),
                    }
                    for role, capability, parameter_name in capability_specs[action_type]
                ],
                "preconditions": [
                    {"factTemplate": fact, "operator": operator, "value": value}
                    for fact, operator, value in preconditions.get(action_type, [])
                ],
                "effects": [
                    {"factTemplate": fact, "operation": operation, "value": value}
                    for fact, operation, value in effects.get(action_type, [])
                ],
            }
            for action_type, parameters in definitions.items()
        ],
    }


def literal(value: Any) -> dict[str, Any]:
    return {"source": "literal", "value": value}


def activity_location(index: int = 0) -> dict[str, Any]:
    return {"source": "activity_location", "index": index}


def action_node(node_id: str, action_type: str, arguments: dict[str, Any]) -> dict[str, Any]:
    sustained = {
        "clean",
        "communicate",
        "consume",
        "exercise",
        "leisure",
        "perform_work",
        "personal_care",
        "prepare_food",
        "shop",
        "wait",
    }
    return {
        "nodeId": node_id,
        "kind": "action",
        "actionType": action_type,
        "arguments": arguments,
        "durationWeight": 5.0 if action_type in sustained else 1.0,
    }


def component_steps(component: str) -> list[tuple[str, dict[str, Any]]]:
    def posture(value: str) -> tuple[str, dict[str, Any]]:
        return "change_posture", {"posture": literal(value)}

    definitions: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "socialize_in_person": [("communicate", {"channel": literal("in_person")})],
        "consume_drink": [("consume", {"itemRole": literal("drink")})],
        "consume_snack": [("consume", {"itemRole": literal("snack")})],
        "consume_meal": [
            posture("sitting"),
            ("consume", {"itemRole": literal("prepared_meal")}),
            posture("standing"),
        ],
        "shop": [("shop", {"purpose": {"source": "activity_intent"}})],
        "carry_purchases": [("take_item", {"itemRole": literal("purchases")})],
        "phone_call": [
            posture("sitting"),
            ("communicate", {"channel": literal("phone")}),
            posture("standing"),
        ],
        "change_clothes": [
            ("take_item", {"itemRole": literal("clothing")}),
            ("dress", {"purpose": {"source": "activity_intent"}}),
            ("put_item", {"itemRole": literal("used_clothing")}),
        ],
        "check_calendar": [("inspect", {"targetRole": literal("calendar")})],
        "inspect_supplies": [
            ("open", {"target": literal("household_storage")}),
            ("inspect", {"targetRole": literal("household_supplies")}),
            ("close", {"target": literal("household_storage")}),
        ],
        "clean_surface": [
            ("take_item", {"itemRole": literal("cleaning_tool")}),
            ("clean", {"targetRole": {"source": "activity_intent"}}),
            ("put_item", {"itemRole": literal("cleaning_tool")}),
        ],
        "collect_belongings": [("take_item", {"itemRole": literal("personal_belongings")})],
        "leave_home": [("leave_home", {})],
        "collect_medication": [
            ("manage_medication", {"operation": literal("refill")}),
            ("take_item", {"itemRole": literal("medication")}),
        ],
        "travel": [
            ("leave_home", {}),
            ("travel_to", {"destination": activity_location()}),
        ],
        "enter_home": [("enter_home", {})],
        "wash_dishes": [
            ("activate", {"target": literal("sink_faucet")}),
            ("clean", {"targetRole": literal("dishware")}),
            ("deactivate", {"target": literal("sink_faucet")}),
        ],
        "prepare_food": [
            ("open", {"target": literal("food_storage")}),
            ("take_item", {"itemRole": literal("ingredients")}),
            ("close", {"target": literal("food_storage")}),
            ("activate", {"target": literal("cooking_appliance")}),
            ("prepare_food", {"mealKind": {"source": "activity_intent"}}),
            ("deactivate", {"target": literal("cooking_appliance")}),
            ("put_item", {"itemRole": literal("prepared_meal")}),
        ],
        "prepare_salad": [
            ("take_item", {"itemRole": literal("salad_ingredients")}),
            ("prepare_food", {"mealKind": literal("salad")}),
            ("put_item", {"itemRole": literal("prepared_salad")}),
        ],
        "reheat_food": [
            ("take_item", {"itemRole": literal("leftover_food")}),
            ("activate", {"target": literal("reheating_appliance")}),
            ("prepare_food", {"mealKind": literal("reheated_meal")}),
            ("deactivate", {"target": literal("reheating_appliance")}),
        ],
        "prepare_drink": [
            ("take_item", {"itemRole": literal("drink_ingredients")}),
            ("activate", {"target": literal("drink_appliance")}),
            ("prepare_food", {"mealKind": literal("hot_drink")}),
            ("deactivate", {"target": literal("drink_appliance")}),
        ],
        "listen_radio": [("leisure", {"kind": literal("listen_radio_news")})],
        "read_news": [("leisure", {"kind": literal("read_news")})],
        "personal_hygiene": [("personal_care", {"procedure": literal("evening_hygiene")})],
        "walk": [("exercise", {"kind": literal("walking")})],
        "hang_laundry": [("laundry_step", {"operation": literal("hang")})],
        "exercise": [("exercise", {"kind": literal("indoor_light_exercise")})],
        "iron_laundry": [("laundry_step", {"operation": literal("iron")})],
        "use_toilet": [("personal_care", {"procedure": literal("use_toilet")})],
        "shower": [
            ("activate", {"target": literal("shower_water")}),
            ("personal_care", {"procedure": literal("shower")}),
            ("deactivate", {"target": literal("shower_water")}),
        ],
        "wash_face": [
            ("activate", {"target": literal("sink_faucet")}),
            ("personal_care", {"procedure": literal("wash_face")}),
            ("deactivate", {"target": literal("sink_faucet")}),
        ],
        "portion_food": [("organize", {"targetRole": literal("prepared_food_portions")})],
        "store_food": [
            ("open", {"target": literal("food_storage")}),
            ("put_item", {"itemRole": literal("prepared_food_portions")}),
            ("close", {"target": literal("food_storage")}),
        ],
        "organize_clothes": [("organize", {"targetRole": literal("work_clothes")})],
        "organize_bag": [("organize", {"targetRole": literal("work_bag")})],
        "organize_documents": [("organize", {"targetRole": literal("documents")})],
        "store_purchases": [
            ("open", {"target": literal("household_storage")}),
            ("put_item", {"itemRole": literal("purchases")}),
            ("close", {"target": literal("household_storage")}),
        ],
        "read": [posture("sitting"), ("leisure", {"kind": literal("read")})],
        "read_in_bed": [posture("lying"), ("leisure", {"kind": literal("read")})],
        "rest": [posture("sitting"), ("wait", {"purpose": literal("rest")})],
        "nap": [posture("lying"), ("wait", {"purpose": literal("nap")})],
        "sleep": [posture("lying"), ("wait", {"purpose": literal("sleep")})],
        "wake_up": [posture("standing")],
        "collect_laundry": [("laundry_step", {"operation": literal("collect")})],
        "load_laundry": [("laundry_step", {"operation": literal("load")})],
        "start_laundry": [("laundry_step", {"operation": literal("start")})],
        "take_medication": [
            ("take_item", {"itemRole": literal("medication")}),
            ("manage_medication", {"operation": literal("take")}),
            ("put_item", {"itemRole": literal("medication")}),
        ],
        "carry_recycling": [("take_item", {"itemRole": literal("recycling")})],
        "discard_recycling": [("put_item", {"itemRole": literal("recycling_bin")})],
        "tidy_area": [("organize", {"targetRole": {"source": "activity_intent"}})],
        "vacuum": [
            ("take_item", {"itemRole": literal("vacuum_cleaner")}),
            ("activate", {"target": literal("vacuum_cleaner")}),
            ("clean", {"targetRole": literal("floor")}),
            ("deactivate", {"target": literal("vacuum_cleaner")}),
            ("put_item", {"itemRole": literal("vacuum_cleaner")}),
        ],
        "dust": [
            ("take_item", {"itemRole": literal("dusting_tool")}),
            ("clean", {"targetRole": literal("surfaces")}),
            ("put_item", {"itemRole": literal("dusting_tool")}),
        ],
        "watch_media": [
            posture("sitting"),
            ("activate", {"target": literal("television")}),
            ("leisure", {"kind": {"source": "activity_intent"}}),
            ("deactivate", {"target": literal("television")}),
        ],
        "work": [posture("sitting"), ("perform_work", {"mode": literal("work_shift")})],
    }
    target_roles = {
        "socialize_in_person": "social_area",
        "consume_drink": "consumption_area",
        "consume_snack": "consumption_area",
        "consume_meal": "consumption_area",
        "shop": "retail_area",
        "carry_purchases": "purchases",
        "phone_call": "communication_area",
        "change_clothes": "clothing_storage",
        "check_calendar": "calendar",
        "inspect_supplies": "household_storage",
        "clean_surface": "cleaning_target",
        "collect_belongings": "personal_belongings",
        "leave_home": "home_exit",
        "collect_medication": "pharmacy_counter",
        "enter_home": "home_entrance",
        "wash_dishes": "sink",
        "prepare_food": "food_preparation_area",
        "prepare_salad": "food_preparation_area",
        "reheat_food": "reheating_area",
        "prepare_drink": "drink_preparation_area",
        "listen_radio": "radio",
        "read_news": "reading_area",
        "personal_hygiene": "personal_care_fixture",
        "walk": "walking_area",
        "hang_laundry": "drying_area",
        "exercise": "exercise_area",
        "iron_laundry": "ironing_area",
        "use_toilet": "toilet",
        "shower": "shower",
        "wash_face": "sink",
        "portion_food": "food_preparation_area",
        "store_food": "food_storage",
        "organize_clothes": "clothing_storage",
        "organize_bag": "bag_storage",
        "organize_documents": "document_storage",
        "store_purchases": "household_storage",
        "collect_laundry": "laundry_storage",
        "load_laundry": "washing_machine",
        "start_laundry": "washing_machine",
        "take_medication": "medication_storage",
        "carry_recycling": "recycling_storage",
        "discard_recycling": "recycling_bin",
        "tidy_area": "tidying_area",
        "vacuum": "vacuum_cleaner",
        "dust": "dusting_area",
        "watch_media": "television",
    }
    steps = definitions[component]
    if component == "travel":
        return steps
    target_role = target_roles.get(component)
    movement = (
        ("move_to_capability", {"targetRole": literal(target_role)})
        if target_role is not None
        else ("move_to", {"destination": activity_location()})
    )
    return [movement, *steps]


def process_model(resident_id: str, intent: str) -> dict[str, Any]:
    components = INTENT_COMPONENTS[intent]
    if intent == "rest_or_nap":
        nodes = [
            {"nodeId": "start", "kind": "start"},
            action_node("move_to_activity", "move_to", {"destination": activity_location()}),
            {"nodeId": "rest_or_nap", "kind": "choice"},
            action_node("rest_posture", "change_posture", {"posture": literal("sitting")}),
            action_node("rest", "wait", {"purpose": literal("rest")}),
            action_node("nap_posture", "change_posture", {"posture": literal("lying")}),
            action_node("nap", "wait", {"purpose": literal("nap")}),
            {"nodeId": "end", "kind": "end"},
        ]
        edges = [
            {"sourceNodeId": "start", "targetNodeId": "move_to_activity"},
            {"sourceNodeId": "move_to_activity", "targetNodeId": "rest_or_nap"},
            {
                "sourceNodeId": "rest_or_nap",
                "targetNodeId": "nap_posture",
                "condition": {
                    "variableId": "resident.fatigue",
                    "operator": "gte",
                    "value": 0.6,
                },
            },
            {"sourceNodeId": "rest_or_nap", "targetNodeId": "rest_posture", "isDefault": True},
            {"sourceNodeId": "rest_posture", "targetNodeId": "rest"},
            {"sourceNodeId": "rest", "targetNodeId": "end"},
            {"sourceNodeId": "nap_posture", "targetNodeId": "nap"},
            {"sourceNodeId": "nap", "targetNodeId": "end"},
        ]
        return process_document(resident_id, intent, components, nodes, edges)

    parallel_media = {
        "eat_breakfast_and_listen_to_radio": "listen_radio_news",
        "eat_breakfast_and_read_news": "read_news",
        "eat_breakfast_with_radio_news": "listen_radio_news",
    }
    if intent in parallel_media:
        nodes = [
            {"nodeId": "start", "kind": "start"},
            action_node("move_to_activity", "move_to", {"destination": activity_location()}),
            action_node("sit", "change_posture", {"posture": literal("sitting")}),
            {"nodeId": "parallel_start", "kind": "parallel_split"},
            action_node("eat", "consume", {"itemRole": literal("prepared_meal")}),
            action_node("media", "leisure", {"kind": literal(parallel_media[intent])}),
            {"nodeId": "parallel_end", "kind": "parallel_join"},
            action_node("stand", "change_posture", {"posture": literal("standing")}),
            {"nodeId": "end", "kind": "end"},
        ]
        edges = [
            {"sourceNodeId": "start", "targetNodeId": "move_to_activity"},
            {"sourceNodeId": "move_to_activity", "targetNodeId": "sit"},
            {"sourceNodeId": "sit", "targetNodeId": "parallel_start"},
            {"sourceNodeId": "parallel_start", "targetNodeId": "eat"},
            {"sourceNodeId": "parallel_start", "targetNodeId": "media"},
            {"sourceNodeId": "eat", "targetNodeId": "parallel_end"},
            {"sourceNodeId": "media", "targetNodeId": "parallel_end"},
            {"sourceNodeId": "parallel_end", "targetNodeId": "stand"},
            {"sourceNodeId": "stand", "targetNodeId": "end"},
        ]
        return process_document(resident_id, intent, components, nodes, edges)

    if intent == "work_shift":
        nodes = [
            {"nodeId": "start", "kind": "start"},
            action_node("move_to_activity", "move_to", {"destination": activity_location()}),
            action_node("sit", "change_posture", {"posture": literal("sitting")}),
            action_node("work_block", "perform_work", {"mode": literal("work_block")}),
            {"nodeId": "continue_work", "kind": "loop", "maxIterations": 4},
            action_node("stand", "change_posture", {"posture": literal("standing")}),
            {"nodeId": "end", "kind": "end"},
        ]
        edges = [
            {"sourceNodeId": "start", "targetNodeId": "move_to_activity"},
            {"sourceNodeId": "move_to_activity", "targetNodeId": "sit"},
            {"sourceNodeId": "sit", "targetNodeId": "work_block"},
            {"sourceNodeId": "work_block", "targetNodeId": "continue_work"},
            {
                "sourceNodeId": "continue_work",
                "targetNodeId": "work_block",
                "condition": {
                    "variableId": "resident.stress",
                    "operator": "lt",
                    "value": 0.9,
                },
            },
            {"sourceNodeId": "continue_work", "targetNodeId": "stand", "isDefault": True},
            {"sourceNodeId": "stand", "targetNodeId": "end"},
        ]
        return process_document(resident_id, intent, components, nodes, edges)

    steps = [step for component in components for step in component_steps(component)]
    nodes = [{"nodeId": "start", "kind": "start"}]
    for index, (action_type, arguments) in enumerate(steps, start=1):
        nodes.append(action_node(f"step_{index}", action_type, arguments))
    nodes.append({"nodeId": "end", "kind": "end"})
    ordered_ids = [node["nodeId"] for node in nodes]
    edges = [
        {"sourceNodeId": source, "targetNodeId": target}
        for source, target in zip(ordered_ids, ordered_ids[1:], strict=False)
    ]
    return process_document(resident_id, intent, components, nodes, edges)


def process_document(
    resident_id: str,
    intent: str,
    components: list[str],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "processModelId": f"{resident_id}__{intent}",
        "processModelVersion": "1.0.0",
        "residentId": resident_id,
        "title": f"{resident_id} {intent.replace('_', ' ')} process",
        "description": (
            "Resident-specific executable decomposition: " + ", ".join(components) + "."
        ),
        "implementedComponents": components,
        "nodes": nodes,
        "edges": edges,
    }


def behavior_package(scenario: dict[str, Any]) -> dict[str, Any]:
    resident_intents: dict[str, set[str]] = {}
    bindings: list[dict[str, Any]] = []
    seen_bindings: set[tuple[str, str]] = set()
    for day in scenario["days"]:
        for activity in day["activities"]:
            key = (activity["actorId"], activity["intent"])
            if key in seen_bindings:
                continue
            seen_bindings.add(key)
            resident_intents.setdefault(activity["actorId"], set()).add(activity["intent"])
            bindings.append(
                {
                    "bindingId": f"{activity['actorId']}__{activity['intent']}",
                    "residentId": activity["actorId"],
                    "intent": activity["intent"],
                    "processModelId": f"{activity['actorId']}__{activity['intent']}",
                    "fallback": True,
                }
            )
    models = [
        process_model(resident_id, intent)
        for resident_id in sorted(resident_intents)
        for intent in sorted(resident_intents[resident_id])
    ]
    return {
        "schemaVersion": "1.0.0",
        "documentType": "personal_process_package",
        "packageId": f"{scenario['scenarioId']}__behavior",
        "packageVersion": "1.0.0",
        "sourceScenarioId": scenario["scenarioId"],
        "sourceScenarioVersion": scenario["schemaVersion"],
        "language": scenario["language"],
        "provenance": {
            "authorType": "rule_generator",
            "generatorName": "build_behavior_artifacts",
            "generatorVersion": "1.0.0",
            "promptTemplateVersion": "personal-process-models-1.0.0",
            "generatedAt": "2026-07-20T12:00:00+02:00",
            "humanReviewed": False,
            "parameters": {"decompositionTableVersion": "1.0.0"},
        },
        "catalogs": {
            "activityCatalog": {
                "catalogId": "smart_home_activity_catalog",
                "version": "1.0.0",
            },
            "variableCatalog": {
                "catalogId": "smart_home_variable_catalog",
                "version": "1.0.0",
            },
            "actionCatalog": {
                "catalogId": "smart_home_action_catalog",
                "version": "1.0.0",
            },
        },
        "processModels": models,
        "bindings": bindings,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    scenarios = load_scenarios()
    write_json(CATALOG_DIR / "activity-catalog-1.0.0.json", activity_catalog(scenarios))
    write_json(CATALOG_DIR / "variable-catalog-1.0.0.json", variable_catalog())
    write_json(CATALOG_DIR / "action-catalog-1.0.0.json", action_catalog())
    for scenario in scenarios:
        name = scenario["scenarioId"]
        write_json(BEHAVIOR_EXAMPLE_DIR / f"{name}.behavior.json", behavior_package(scenario))


if __name__ == "__main__":
    main()
