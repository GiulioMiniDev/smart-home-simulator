"""The bundled catalogs, extended with what the active vocabulary adds to them.

The vocabulary editor lets a researcher add an activity or an action as data, and the planner, the
expander and the preflight already read the pack. The behaviour validator, the materializer and
the simulator did not: they loaded the action and activity catalogs from the files a package names,
so an activity added in the editor expanded into days and was then refused as `UNKNOWN_INTENT`, and
an added action could not have been executed had it got that far. This is the one place the two
meet.

**Additions only, and only the workspace's.** An entry the file already defines is left exactly as
the file defines it. A package declares the catalog version it was written against, and reading its
`open` through a definition the pack has since edited would ask it to satisfy preconditions no
reader of its own catalog expected — the reason `_declared_action_catalog` exists. For the same
reason an entry the *built-in* vocabulary already has is not added either: the built-in pack is
derived from the newest catalogs, so without that rule a package declaring activity catalog 1.0.0
would quietly gain `phone_call`, which its own catalog does not define. What a workspace adds is new
by construction, so it cannot change the meaning of a package written before it existed.
"""

from __future__ import annotations

from typing import Any

from smart_home_sim.domain.vocabulary import VocabularyAwayIntent, VocabularyIntent, VocabularyPack

# Every activity definition names at least one variable it depends on. The day's type is the one
# every activity in the bundled catalog can honestly be said to depend on.
_WORKSPACE_VARIABLES = ["day.type"]
AUTHORED_COMPONENT_PREFIX = "authored__"


def _builtin_identifiers() -> tuple[frozenset[str], frozenset[str]]:
    """Action types and intent ids the simulator ships with, which no overlay ever adds."""
    from smart_home_sim.vocabulary.defaults import builtin_pack

    builtin = builtin_pack()
    return (
        frozenset(item.action_type for item in builtin.actions),
        frozenset(
            [item.intent_id for item in builtin.intents]
            + [item.intent_id for item in builtin.away_intents]
        ),
    )


def with_vocabulary_actions(payload: dict[str, Any], pack: VocabularyPack) -> dict[str, Any]:
    """An action catalog payload with every action the workspace adds appended."""
    defined = {item.get("actionType") for item in payload.get("actions", [])}
    shipped, _ = _builtin_identifiers()
    added = [
        action.definition.model_dump(mode="json", by_alias=True)
        for action in pack.actions
        if action.action_type not in defined and action.action_type not in shipped
    ]
    if not added:
        return payload
    return {**payload, "actions": [*payload.get("actions", []), *added]}


def validation_components(
    intent: VocabularyIntent | VocabularyAwayIntent, known_components: set[str]
) -> list[str]:
    """The components a process model for this workspace activity must declare it implements.

    An activity whose components are all catalog components keeps them, so a model written for it
    is checked exactly like one written for a bundled activity. One that names none — every
    activity created in the editor starts that way — or names a component the catalog lacks gets a
    component of its own, `authored__<intent>`, because a catalog entry must name at least one and
    must not name one nobody defines.
    """
    components = list(getattr(intent, "components", []))
    if components and all(item in known_components for item in components):
        return components
    return [f"{AUTHORED_COMPONENT_PREFIX}{intent.intent_id}"]


def _first_action(intent: VocabularyIntent | VocabularyAwayIntent) -> str:
    if isinstance(intent, VocabularyIntent):
        for node in intent.process_model.nodes:
            if node.action_type:
                return node.action_type
        return "move_to"
    # An away activity has no model in the pack; every one of them begins at the front door.
    return "leave_home"


def with_vocabulary_intents(payload: dict[str, Any], pack: VocabularyPack) -> dict[str, Any]:
    """An activity catalog payload with every activity the workspace adds appended."""
    _, shipped = _builtin_identifiers()
    defined = {item.get("intent") for item in payload.get("activities", [])} | shipped
    known_components = {item.get("componentId") for item in payload.get("components", [])}
    components = list(payload.get("components", []))
    activities = list(payload.get("activities", []))
    workspace: list[tuple[VocabularyIntent | VocabularyAwayIntent, str]] = [
        *((item, item.category) for item in pack.intents),
        *((item, "away") for item in pack.away_intents),
    ]
    for intent, category in workspace:
        if intent.intent_id in defined:
            continue
        declared = validation_components(intent, known_components)  # type: ignore[arg-type]
        for component in declared:
            if component in known_components:
                continue
            components.append(
                {
                    "componentId": component,
                    "description": (
                        f"The decomposition of '{intent.intent_id}' authored in this workspace's "
                        "vocabulary."
                    ),
                    "requiredActionTypes": [_first_action(intent)],
                }
            )
            known_components.add(component)
        activities.append(
            {
                "intent": intent.intent_id,
                "displayName": intent.label,
                "description": intent.description
                or f"Activity '{intent.intent_id}' added in this workspace's vocabulary.",
                "category": category,
                "components": declared,
                "relevantVariableIds": list(_WORKSPACE_VARIABLES),
                "externalMappings": dict(intent.external_mappings),
            }
        )
    if len(activities) == len(payload.get("activities", [])):
        return payload
    return {**payload, "components": components, "activities": activities}
