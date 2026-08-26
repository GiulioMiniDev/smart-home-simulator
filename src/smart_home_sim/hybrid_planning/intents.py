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

REFERENCE_FILE = "reference-process-models-1.4.0.json"


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
    # Paid work performed *inside* the dwelling. It is a category of its own rather than a reuse of
    # `leisure` because its duration behaves differently from anything else here — a block runs for
    # hours, not for the forty minutes a leisure activity lasts — and because the distinction is
    # what a habit-mining evaluation is asked to recover in the middle of a working day.
    home_work = "home_work"


@dataclass(frozen=True)
class IntentSpec:
    intent_id: str
    label: str
    category: IntentCategory
    default_location: str
    # Where the activity leaves the resident, when that is not where it happens. Only a nocturnal
    # trip needs it so far: a process ends where its last action left the body, and for everything
    # else that is the room the activity ran in. The process model reaches it as
    # `activity_location[1]`, so an intent that declares one must have a model that walks there.
    return_location: str | None = None


# ~25 sensor-distinct ADL intents. Each intent_id is an EXACT activity-catalog 1.4.0 intent (so
# bindings validate) that also has a reference process model; default_location must be a standard
# PlanningWorld location. Catalog 1.2.0 made the vocabulary neutral, so an id no longer names a
# private individual: who is on the other end of a call is scenario data, not a ground-truth label.
# Catalog 1.3.0 added `work_from_home`, which is the first intent here that is *work*: see the note
# below `AWAY_CATEGORIES` for why work could not previously happen indoors at all.
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
    IntentSpec("work_from_home", "Work from home", IntentCategory.home_work, "living_room"),
    # The two breaks a day at home is made of. They are here for the same reason `work_from_home`
    # is: without them the hours between the blocks are unaccounted, and the resident who is
    # supposedly at home all day never crosses a doorway. `use_toilet` also removes a standing
    # label lie — the only toilet intent was `morning_toilet_and_wash`, and an intent id *is* the
    # ground-truth label a dataset publishes, so an afternoon trip was recorded as a morning
    # routine.
    IntentSpec("use_toilet", "Use the toilet", IntentCategory.hygiene, "bathroom"),
    # The same trip made in the middle of the night, and a separate intent because it ends
    # differently: the resident goes back to bed. Sharing `use_toilet` left her standing at the
    # washbasin until the next thing in the plan came for her, and `wake_up` then began by walking
    # her to the bedroom she had never left in the first place. Catalog 1.4.0 carries it, and with
    # it the `Bed_to_Toilet` mapping onto CASAS Aruba, which is this trip and not an afternoon one.
    IntentSpec(
        "night_toilet_visit",
        "Night toilet visit",
        IntentCategory.hygiene,
        "bathroom",
        return_location="bedroom",
    ),
    IntentSpec(
        "prepare_and_drink_hot_drink", "Make a hot drink", IntentCategory.cooking, "kitchen"
    ),
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
#
# `work` sits here because a shift is normally an absence, and for a decade of ADL datasets that
# was the whole story. It is not the story for someone who works from home, and reading the
# category as "away" made that person unrepresentable: her hours could only be declared as
# `work_shift`, which is placed `outdoors` and which `validate_away_round_trips` then requires to
# leave the flat and come back. Authors correctly refused to write that, and left the working day
# out of the outline altogether — one authored horizon carries the admission in its own notes
# ("freelance work itself is not declared because no canonical home-work intent exists") and with
# it an empty 09:30-17:30 band on 260 weekdays, which is not a quiet approximation but the largest
# waking stretch of the dataset containing nothing.
#
# So home work is its own category, and it is in `INTENT_CATALOG` with a room and a reference
# model like any other indoor activity.
AWAY_CATEGORIES: frozenset[str] = frozenset({"travel", "work", "social_visit"})
AWAY_LOCATION = "outdoors"
ACTIVITY_CATALOG_FILE = "activity-catalog-1.4.0.json"


@lru_cache(maxsize=1)
def away_intent_specs() -> tuple[IntentSpec, ...]:
    """The catalog's away intents, minus anything the home vocabulary already claims.

    The two lists are rendered side by side in the authoring prompt as "inside the home" and "away
    from home", and an intent printed in both would be an instruction to guess. Excluding the home
    ids here makes them disjoint by construction rather than by the discipline of choosing catalog
    categories carefully: `intent_spec` already resolves `INTENT_CATALOG` first, so a duplicate
    would not change where an activity happens — it would only mislead whoever is reading.
    """
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
        if activity["category"] in AWAY_CATEGORIES and activity["intent"] not in _BY_ID
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
