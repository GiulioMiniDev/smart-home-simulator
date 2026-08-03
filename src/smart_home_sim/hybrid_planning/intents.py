"""The shared intent vocabulary: the common ADL alphabet for recurring activities, days, and process
packages.

Habit mining needs a fixed, comparable label space across residents, so every persona draws from
this same catalog. Per-persona diversity comes from which intents recur, when, and in what
sequences (the recurring activities and days) — not from bespoke activity types, which the fixed
sensor layout
could not distinguish anyway. Each intent carries a default standard-apartment location (for
distinct sensor signatures) and is grounded on a reference process model extracted from a proven
package, on which stage A2b anchors the LLM authoring and its deterministic fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files

from smart_home_sim.domain.behavior import ProcessModel

REFERENCE_FILE = "reference-process-models-1.2.0.json"


class IntentCategory(StrEnum):
    sleep_wake = "sleep_wake"
    hygiene = "hygiene"
    medication = "medication"
    meal = "meal"
    cooking = "cooking"
    chores = "chores"
    laundry = "laundry"
    exercise = "exercise"
    outdoor = "outdoor"
    errand = "errand"
    leisure = "leisure"
    social = "social"


@dataclass(frozen=True)
class IntentSpec:
    intent_id: str
    label: str
    category: IntentCategory
    default_location: str


# ~24 sensor-distinct ADL intents. Each intent_id is an EXACT activity-catalog 1.2.0 intent (so
# bindings validate) that also has a reference process model; default_location must be a standard
# PlanningWorld location. Catalog 1.2.0 made the vocabulary neutral, so an id no longer names a
# private individual: who is on the other end of a call is scenario data, not a ground-truth label.
INTENT_CATALOG: tuple[IntentSpec, ...] = (
    IntentSpec("wake_up", "Wake up", IntentCategory.sleep_wake, "bedroom"),
    IntentSpec("morning_toilet_and_wash", "Morning wash", IntentCategory.hygiene, "bathroom"),
    IntentSpec("morning_toilet_and_shower", "Morning shower", IntentCategory.hygiene, "bathroom"),
    IntentSpec("take_morning_medication", "Take medication", IntentCategory.medication, "kitchen"),
    IntentSpec("eat_breakfast", "Eat breakfast", IntentCategory.meal, "kitchen"),
    IntentSpec("eat_lunch", "Eat lunch", IntentCategory.meal, "kitchen"),
    IntentSpec("eat_dinner", "Eat dinner", IntentCategory.meal, "kitchen"),
    IntentSpec("prepare_simple_lunch", "Prepare lunch", IntentCategory.cooking, "kitchen"),
    IntentSpec("prepare_light_dinner", "Prepare dinner", IntentCategory.cooking, "kitchen"),
    IntentSpec("weekly_meal_preparation", "Batch cook", IntentCategory.cooking, "kitchen"),
    IntentSpec("clean_kitchen", "Clean the kitchen", IntentCategory.chores, "kitchen"),
    IntentSpec(
        "tidy_living_room_and_hallway", "Tidy the living room", IntentCategory.chores, "living_room"
    ),
    IntentSpec("start_laundry", "Start laundry", IntentCategory.laundry, "bathroom"),
    IntentSpec("hang_laundry", "Hang laundry", IntentCategory.laundry, "balcony"),
    IntentSpec("indoor_light_exercise", "Indoor exercise", IntentCategory.exercise, "living_room"),
    IntentSpec("evening_walk", "Walk outdoors", IntentCategory.outdoor, "outdoors"),
    IntentSpec("buy_groceries", "Go shopping", IntentCategory.errand, "outdoors"),
    IntentSpec("put_groceries_away", "Put groceries away", IntentCategory.chores, "kitchen"),
    IntentSpec("watch_television", "Watch television", IntentCategory.leisure, "living_room"),
    IntentSpec("read_and_rest", "Read and rest", IntentCategory.leisure, "living_room"),
    IntentSpec("rest_or_nap", "Nap", IntentCategory.leisure, "bedroom"),
    IntentSpec("phone_call", "Phone a relative or friend", IntentCategory.social, "living_room"),
    IntentSpec("evening_hygiene", "Evening hygiene", IntentCategory.hygiene, "bathroom"),
    IntentSpec("sleep", "Sleep", IntentCategory.sleep_wake, "bedroom"),
)

# Time spent away from the dwelling, taken from the activity catalog rather than enumerated here.
# These are deliberately *not* in `INTENT_CATALOG`: that tuple pairs one-to-one with the bundled
# reference process models, and the local pipeline builds a package by walking it. An away intent
# has no reference model and needs none — nothing it does is observable by a home sensor, so the
# only fact the simulation takes from it is that the resident is out. Admitting them by catalog
# category lets a case say "she is at work" without the vocabulary growing an intent per
# occupation, and without touching a frozen artifact.
AWAY_CATEGORIES: frozenset[str] = frozenset({"travel", "work", "social_visit"})
AWAY_LOCATION = "outdoors"
ACTIVITY_CATALOG_FILE = "activity-catalog-1.2.0.json"


@lru_cache(maxsize=1)
def away_intent_specs() -> tuple[IntentSpec, ...]:
    catalog = json.loads(
        files("smart_home_sim.catalogs").joinpath(ACTIVITY_CATALOG_FILE).read_text(encoding="utf-8")
    )
    return tuple(
        IntentSpec(
            activity["intent"],
            activity.get("displayName") or activity["intent"],
            IntentCategory.outdoor,
            AWAY_LOCATION,
        )
        for activity in sorted(catalog["activities"], key=lambda item: item["intent"])
        if activity["category"] in AWAY_CATEGORIES
    )


_BY_ID: dict[str, IntentSpec] = {spec.intent_id: spec for spec in INTENT_CATALOG}


def intent_ids() -> list[str]:
    return [spec.intent_id for spec in INTENT_CATALOG]


def intent_spec(intent_id: str) -> IntentSpec:
    spec = _BY_ID.get(intent_id)
    if spec is not None:
        return spec
    for away in away_intent_specs():
        if away.intent_id == intent_id:
            return away
    raise KeyError(f"unknown intent: {intent_id!r}")


@lru_cache(maxsize=1)
def load_reference_models() -> dict[str, ProcessModel]:
    """Load and parse the bundled reference process models, keyed by canonical intent id."""
    raw = json.loads(
        files("smart_home_sim.catalogs").joinpath(REFERENCE_FILE).read_text(encoding="utf-8")
    )
    # ContractModel is strict, so string enums parse via JSON rather than model_validate(dict).
    return {
        intent_id: ProcessModel.model_validate_json(json.dumps(model))
        for intent_id, model in raw["models"].items()
    }


def reference_model(intent_id: str) -> ProcessModel:
    models = load_reference_models()
    try:
        return models[intent_id]
    except KeyError as error:
        raise KeyError(f"no reference process model for intent: {intent_id!r}") from error
