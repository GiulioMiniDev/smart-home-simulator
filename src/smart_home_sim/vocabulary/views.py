"""Read a vocabulary pack the way each part of the engine used to read its own table.

The engine asks narrow questions — how long is this gesture, does a detector see this action, what
roles does this furniture answer to — and each used to have its own module-level constant. These
functions answer the same questions from a pack, so the call sites change shape as little as
possible and the pack becomes the single place the answers live.

Every function here is the inverse of something in `defaults`, and `test_vocabulary` pins that:
applied to the built-in pack, each returns exactly the constant it replaces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smart_home_sim.domain.behavior import ProcessModel
from smart_home_sim.domain.vocabulary import VocabularyPack

if TYPE_CHECKING:
    from smart_home_sim.hybrid_planning.intents import IntentSpec


def gesture_seconds_table(pack: VocabularyPack) -> dict[str, float]:
    """`PUNCTUAL_ACTION_SECONDS`: the actions with a length of their own.

    An action with no length is simply absent, which is what the table always meant: it is elastic
    and shares the activity's budget by weight. A zero is not the same thing — `move_to` is entered
    at zero because the engine replaces it with the length of the planned walk.
    """
    return {
        action.action_type: action.gesture_seconds
        for action in pack.actions
        if action.gesture_seconds is not None
    }


def motion_action_types(pack: VocabularyPack) -> frozenset[str]:
    """`PIR_ACTIVITY_ACTION_TYPES`: working at an object stirs the detector watching it."""
    return frozenset(
        action.action_type for action in pack.actions if action.observability.motion_at_object
    )


def travel_action_types(pack: VocabularyPack) -> frozenset[str]:
    """The actions whose evidence is the path they walk rather than the action itself."""
    return frozenset(action.action_type for action in pack.actions if action.is_travel)


def entity_type_capabilities(pack: VocabularyPack) -> dict[str, frozenset[str]]:
    """`ENTITY_TYPE_CAPABILITIES`: what each kind of furniture is actually for.

    A type that declares none is omitted rather than recorded as empty, because the two mean
    opposite things downstream: an absent type keeps every capability, and an empty one would keep
    none. Preserving that distinction is what stops an author's new sofa from binding to nothing.
    """
    return {
        item.entity_type: frozenset(item.capabilities)
        for item in pack.entity_types
        if item.capabilities
    }


def resource_role_aliases(pack: VocabularyPack) -> dict[str, frozenset[str]]:
    """`RESOURCE_ROLE_ALIASES`: every role a declared resource of this type answers to."""
    return {
        item.entity_type: frozenset(item.role_aliases)
        for item in pack.entity_types
        if item.role_aliases
    }


def contact_instrumented_types(pack: VocabularyPack) -> frozenset[str]:
    """`CONTACT_INSTRUMENTED_TYPES`: the furniture a deployment fits with a reed switch."""
    return frozenset(item.entity_type for item in pack.entity_types if item.contact_instrumented)


def intent_specs(pack: VocabularyPack) -> tuple[IntentSpec, ...]:
    """`INTENT_CATALOG`: the in-home activity alphabet, in the pack's own order.

    `IntentSpec` is imported inside the call: `hybrid_planning`'s package init reaches
    materialization and from there the sensor projector, which imports this module — so a
    module-scope import would close a cycle through half the engine.
    """
    from smart_home_sim.hybrid_planning.intents import IntentCategory, IntentSpec

    return tuple(
        IntentSpec(
            intent.intent_id,
            intent.label,
            IntentCategory(intent.category),
            intent.default_location,
            intent.return_location,
        )
        for intent in pack.intents
    )


def away_intent_specs(pack: VocabularyPack) -> tuple[IntentSpec, ...]:
    """The away alphabet, every member placed outdoors because that is all a home sensor knows."""
    from smart_home_sim.hybrid_planning.intents import AWAY_LOCATION, IntentCategory, IntentSpec

    return tuple(
        IntentSpec(item.intent_id, item.label, IntentCategory.outdoor, AWAY_LOCATION)
        for item in pack.away_intents
    )


def reference_models(pack: VocabularyPack) -> dict[str, ProcessModel]:
    """The process model behind each in-home intent, keyed by intent id."""
    return {intent.intent_id: intent.process_model for intent in pack.intents}


def resource_types_for_role(pack: VocabularyPack, role: str) -> frozenset[str]:
    """Which furniture types can answer this role — the inverse of `resource_role_aliases`.

    A type names itself, matching how materialization builds an entity's roles: an author who
    writes `refrigerator` where the reference models write `food_storage` still binds. That applies
    only to a type that declares aliases at all — a type with none is not in the role table, and
    admitting it here would make every furniture name a role, which is wider than the table this
    replaces and would change which object a process binds to.
    """
    aliases = resource_role_aliases(pack)
    matches = {entity_type for entity_type, roles in aliases.items() if role in roles}
    if role in aliases:
        matches.add(role)
    return frozenset(matches)


# Derived tables, kept by pack digest. A pydantic model is not hashable, so `lru_cache` cannot key
# on the pack itself; the digest is the content, which is the key that actually matters — a pack
# reloaded from disk with identical bytes reuses the work, and an edited copy never collides with
# the pack it came from.
_TABLE_CACHE: dict[str, dict[str, object]] = {}
_TABLE_CACHE_LIMIT = 8


def tables(pack: VocabularyPack) -> dict[str, object]:
    """All derived tables for a pack, computed once per distinct content."""
    digest = pack.digest
    cached = _TABLE_CACHE.get(digest)
    if cached is not None:
        return cached
    built: dict[str, object] = {
        "gesture_seconds": gesture_seconds_table(pack),
        "motion_actions": motion_action_types(pack),
        "travel_actions": travel_action_types(pack),
        "entity_capabilities": entity_type_capabilities(pack),
        "role_aliases": resource_role_aliases(pack),
        "contact_types": contact_instrumented_types(pack),
        "intents": intent_specs(pack),
        "away_intents": away_intent_specs(pack),
        "models": reference_models(pack),
    }
    if len(_TABLE_CACHE) >= _TABLE_CACHE_LIMIT:
        # An editor rewrites the pack on every keystroke-ish save, so the cache would otherwise grow
        # without bound over a long session. Oldest out; insertion order is the eviction order.
        del _TABLE_CACHE[next(iter(_TABLE_CACHE))]
    _TABLE_CACHE[digest] = built
    return built
