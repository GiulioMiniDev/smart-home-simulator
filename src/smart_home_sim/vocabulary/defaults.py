"""Derive the built-in vocabulary pack from the bundled catalogs and the tables that preceded it.

Nothing here is a second copy of anything. Every value is read from the artifact or the constant
that was authoritative before the pack existed, which is what lets `test_vocabulary` assert the
round trip: the tables rebuilt *from* the default pack equal the constants it was built *from*.
Opening a door to change must not, by itself, change anything.

The one judgement this module makes is `display_name`, because no table held one — an entity type
was only ever an identifier, and an editor needs something to put in a list.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from smart_home_sim.domain.behavior import ActionDefinition, ProcessModel
from smart_home_sim.domain.environment import ENTITY_TYPE_CAPABILITIES
from smart_home_sim.domain.models import RESOURCE_ROLE_ALIASES
from smart_home_sim.domain.sensors import CONTACT_INSTRUMENTED_TYPES
from smart_home_sim.domain.vocabulary import (
    BUILTIN_PACK_ID,
    SOURCE_ACTION_CATALOG,
    SOURCE_ACTIVITY_CATALOG,
    SOURCE_REFERENCE_MODELS,
    ActionObservability,
    VocabularyAction,
    VocabularyAwayIntent,
    VocabularyEntityType,
    VocabularyIntent,
    VocabularyPack,
)
from smart_home_sim.hybrid_planning.intents import (
    ACTIVITY_CATALOG_FILE,
    AWAY_CATEGORIES,
    INTENT_CATALOG,
    REFERENCE_FILE,
)
from smart_home_sim.sensors.service import PIR_ACTIVITY_ACTION_TYPES
from smart_home_sim.simulation.service import PUNCTUAL_ACTION_SECONDS

ACTION_CATALOG_FILE = f"{SOURCE_ACTION_CATALOG}.json"

# What `behavior.service` already treats as travel. These are the actions whose sensor evidence is
# the walk they plan rather than anything the action type itself implies, which is why they sit at
# zero in `PUNCTUAL_ACTION_SECONDS` and appear in no PIR table.
TRAVEL_ACTION_TYPES = frozenset({"move_to", "move_to_capability", "travel_to"})


def _catalog(filename: str) -> dict[str, Any]:
    return json.loads(
        files("smart_home_sim.catalogs").joinpath(filename).read_text(encoding="utf-8")
    )


def _display_name(entity_type: str) -> str:
    return entity_type.replace("_", " ").capitalize()


def _build_actions() -> list[VocabularyAction]:
    catalog = _catalog(ACTION_CATALOG_FILE)
    actions: list[VocabularyAction] = []
    for raw in sorted(catalog["actions"], key=lambda item: item["actionType"]):
        action_type = raw["actionType"]
        is_travel = action_type in TRAVEL_ACTION_TYPES
        actions.append(
            VocabularyAction(
                definition=ActionDefinition.model_validate_json(json.dumps(raw)),
                # Taken from the table verbatim, including the zeros. A zero is not "takes no
                # time": `move_to` is floored to the planned path by `_execute_action` once the walk
                # is known. `travel_to` is absent from the table altogether and so is elastic — an
                # errand lasts as long as the day gives it, not as long as the walk to the door —
                # which is why travel cannot be read off `is_travel` alone.
                gesture_seconds=PUNCTUAL_ACTION_SECONDS.get(action_type),
                observability=ActionObservability(
                    motion_at_object=action_type in PIR_ACTIVITY_ACTION_TYPES,
                    motion_along_path=is_travel,
                ),
                is_travel=is_travel,
            )
        )
    return actions


def _build_entity_types() -> list[VocabularyEntityType]:
    known = sorted(set(ENTITY_TYPE_CAPABILITIES) | set(RESOURCE_ROLE_ALIASES))
    return [
        VocabularyEntityType(
            entity_type=entity_type,
            display_name=_display_name(entity_type),
            capabilities=sorted(ENTITY_TYPE_CAPABILITIES.get(entity_type, frozenset())),
            role_aliases=sorted(RESOURCE_ROLE_ALIASES.get(entity_type, frozenset())),
            contact_instrumented=entity_type in CONTACT_INSTRUMENTED_TYPES,
            # The bundled glyphs live in the frontend and are resolved there by entity type, so the
            # built-in pack names none: leaving these unset keeps today's drawing exactly as it is
            # and reserves the fields for types an author adds.
            symbol_id=None,
            symbol_body=None,
        )
        for entity_type in known
    ]


def _build_intents() -> tuple[list[VocabularyIntent], list[VocabularyAwayIntent]]:
    activity_catalog = _catalog(ACTIVITY_CATALOG_FILE)
    activities = {item["intent"]: item for item in activity_catalog["activities"]}
    reference = _catalog(REFERENCE_FILE)["models"]

    intents: list[VocabularyIntent] = []
    for spec in INTENT_CATALOG:
        model = reference.get(spec.intent_id)
        if model is None:
            raise RuntimeError(
                f"intent {spec.intent_id!r} has no reference process model; the built-in pack "
                "cannot be built from a catalog and a tuple that disagree"
            )
        activity = activities.get(spec.intent_id, {})
        intents.append(
            VocabularyIntent(
                intent_id=spec.intent_id,
                label=spec.label,
                category=str(spec.category),
                default_location=spec.default_location,
                return_location=spec.return_location,
                description=activity.get("description", ""),
                components=list(activity.get("components", [])),
                external_mappings=dict(activity.get("externalMappings") or {}),
                process_model=ProcessModel.model_validate_json(json.dumps(model)),
            )
        )

    home_ids = {spec.intent_id for spec in INTENT_CATALOG}
    away = [
        VocabularyAwayIntent(
            intent_id=activity["intent"],
            label=activity.get("displayName") or activity["intent"],
            description=activity.get("description", ""),
            external_mappings=dict(activity.get("externalMappings") or {}),
        )
        for activity in sorted(activity_catalog["activities"], key=lambda item: item["intent"])
        if activity["category"] in AWAY_CATEGORIES and activity["intent"] not in home_ids
    ]
    return intents, away


@lru_cache(maxsize=1)
def builtin_pack() -> VocabularyPack:
    """The vocabulary the simulator has always had, stated as a document.

    Cached because building it parses three catalogs and validates 28 process models, and because
    every caller wants the same immutable object. Callers that edit must copy.
    """
    intents, away = _build_intents()
    return VocabularyPack(
        pack_id=BUILTIN_PACK_ID,
        base_pack_id=BUILTIN_PACK_ID,
        source_catalogs={
            "actionCatalog": SOURCE_ACTION_CATALOG,
            "activityCatalog": SOURCE_ACTIVITY_CATALOG,
            "referenceProcessModels": SOURCE_REFERENCE_MODELS,
        },
        actions=_build_actions(),
        entity_types=_build_entity_types(),
        intents=intents,
        away_intents=away,
    )
