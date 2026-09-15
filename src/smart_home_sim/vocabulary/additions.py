"""What a workspace's vocabulary adds to the one the simulator ships with, written for a prompt.

The outline prompt is built once, from the bundled catalogs, so the furniture and activities a
researcher adds in the editor were absent from the one document an external author reads: the
model was told a yoga mat did not exist in a workspace that had defined one, and proposed it again.
The prompt keeps one placeholder for this, `{{WORKSPACE_VOCABULARY}}`, filled when it is copied.

Additions only, measured against the built-in pack by identifier — the same rule the catalog
overlay uses, so what the prompt says is available is exactly what the import will accept.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from smart_home_sim.domain.vocabulary import (
    VocabularyAction,
    VocabularyAwayIntent,
    VocabularyEntityType,
    VocabularyIntent,
    VocabularyPack,
)
from smart_home_sim.vocabulary.catalogs import validation_components

NOTHING_ADDED = "This workspace adds nothing: the lists above are the whole vocabulary."


@dataclass(frozen=True)
class WorkspaceAdditions:
    entity_types: list[VocabularyEntityType] = field(default_factory=list)
    intents: list[VocabularyIntent] = field(default_factory=list)
    away_intents: list[VocabularyAwayIntent] = field(default_factory=list)
    actions: list[VocabularyAction] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.entity_types or self.intents or self.away_intents or self.actions)


def workspace_additions(pack: VocabularyPack) -> WorkspaceAdditions:
    from smart_home_sim.vocabulary.defaults import builtin_pack

    builtin = builtin_pack()
    shipped_types = {item.entity_type for item in builtin.entity_types}
    shipped_intents = {item.intent_id for item in builtin.intents} | {
        item.intent_id for item in builtin.away_intents
    }
    shipped_actions = {item.action_type for item in builtin.actions}
    return WorkspaceAdditions(
        entity_types=[item for item in pack.entity_types if item.entity_type not in shipped_types],
        intents=[item for item in pack.intents if item.intent_id not in shipped_intents],
        away_intents=[item for item in pack.away_intents if item.intent_id not in shipped_intents],
        actions=[item for item in pack.actions if item.action_type not in shipped_actions],
    )


def _catalog_components() -> set[str]:
    from smart_home_sim.behavior.service import default_activity_catalog_path

    payload = json.loads(default_activity_catalog_path("1.4.0").read_text(encoding="utf-8"))
    return {item["componentId"] for item in payload["components"]}


def render_additions(pack: VocabularyPack) -> str:
    """The additions as the prompt section's body, or one sentence saying there are none."""
    additions = workspace_additions(pack)
    if additions.empty:
        return NOTHING_ADDED
    lines: list[str] = []
    if additions.entity_types:
        lines.append("Furniture types, usable as `resourceType` like any listed above:")
        lines.append("")
        for item in additions.entity_types:
            offers = ", ".join(f"`{value}`" for value in item.capabilities) or "nothing specific"
            sensor = "; fitted with a contact sensor" if item.contact_instrumented else ""
            lines.append(f"- `{item.entity_type}` ({item.display_name}) — {offers}{sensor}")
        lines.append("")
    if additions.intents:
        known = _catalog_components()
        lines.append(
            "Activities inside the dwelling, usable as `intent` like any listed above. A process "
            "model for one declares exactly the `implementedComponents` given here:"
        )
        lines.append("")
        for intent in additions.intents:
            components = ", ".join(f'"{value}"' for value in validation_components(intent, known))
            lines.append(
                f"- `{intent.intent_id}` — {intent.label} ({intent.category}, in "
                f"`{intent.default_location}`); `implementedComponents`: [{components}]"
            )
        lines.append("")
    if additions.away_intents:
        lines.append("Activities away from home, usable for absences like the away intents above:")
        lines.append("")
        for away in additions.away_intents:
            lines.append(f"- `{away.intent_id}` — {away.label}")
        lines.append("")
    if additions.actions:
        lines.append("Actions, usable in process models like any in the action catalog below:")
        lines.append("")
        for action in additions.actions:
            needs = ", ".join(
                f"`{item.capability}`" for item in action.definition.required_capabilities
            )
            requirement = f"; needs {needs}" if needs else ""
            lines.append(f"- `{action.action_type}` — {action.definition.description}{requirement}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
