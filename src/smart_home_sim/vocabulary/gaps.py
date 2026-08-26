"""What is missing, unreachable or dead in a vocabulary — the things that fail silently.

None of these stop a run. That is exactly why they are worth reporting: every one of them has, at
some point in this project's history, produced a worse dataset with no error anywhere. A role no
furniture answers sent the resident to the room's service point instead of to an object. A type
with no declared capabilities kept *every* capability and won bindings alphabetically, which is how
a storage cabinet came to be where nine hours of work a day happened. A container with no contact
sensor is a door that opens in the simulation and never in the log.

An author extending the vocabulary will hit all of these, so the editor shows them as findings with
a severity and a plain sentence, rather than leaving them to be discovered in a month of generated
data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.vocabulary import VocabularyPack
from smart_home_sim.vocabulary import views

# What a body can always do to anything, so an entity offering only these offers nothing specific.
UNIVERSAL_CAPABILITIES = frozenset({"interaction_point", "reachable", "transport_reachable"})

# Capabilities the resident carries or the floor provides, never a piece of furniture. Reported as
# unmet they would be pure noise: `change_posture` needs `posture_control`, which is not something
# a cupboard could ever offer.
SELF_CAPABILITIES = frozenset({"reachable", "transport_reachable", "posture_control"})

Severity = Literal["blocking", "warning", "note"]


class VocabularyGap(ContractModel):
    code: str = Field(min_length=1)
    severity: Severity
    subject: str = Field(min_length=1)
    # What is wrong, in one sentence, written for the person who can fix it.
    message: str = Field(min_length=1)
    # What it costs if left alone. Separated from the message because a finding nobody understands
    # the consequence of reads as pedantry and gets dismissed.
    consequence: str = ""
    details: dict[str, list[str]] = Field(default_factory=dict)


class VocabularyGapsReport(ContractModel):
    pack_id: str = Field(min_length=1)
    digest: str = Field(min_length=1)
    gaps: list[VocabularyGap] = Field(default_factory=list)

    @property
    def blocking(self) -> list[VocabularyGap]:
        return [item for item in self.gaps if item.severity == "blocking"]


def _roles_named_by_models(pack: VocabularyPack) -> dict[str, set[str]]:
    """Every role literal a process model names, and which intents name it.

    Only parameters that actually point at something in the flat count. A `procedure` or an
    `operation` — `wash_face`, `load` — is part of the sentence and binds to no furniture, and
    reading one as a role reports the posture `sitting` as an unfurnished room.
    """
    binding_kinds = {"capability", "environment_entity"}
    kinds: dict[str, dict[str, str]] = {
        action.action_type: {
            parameter.parameter_name: str(parameter.reference_kind)
            for parameter in action.definition.parameters
        }
        for action in pack.actions
    }
    roles: dict[str, set[str]] = {}
    for intent in pack.intents:
        for node in intent.process_model.nodes:
            if node.action_type is None:
                continue
            parameters = kinds.get(node.action_type, {})
            for name, argument in node.arguments.items():
                if parameters.get(name) not in binding_kinds:
                    continue
                if isinstance(argument.value, str):
                    roles.setdefault(argument.value, set()).add(intent.intent_id)
    return roles


def gaps_report(
    pack: VocabularyPack, *, drawable_types: frozenset[str] = frozenset()
) -> VocabularyGapsReport:
    """Everything about this vocabulary that will disappoint quietly.

    `drawable_types` is the set of entity types the viewer already has a glyph for. It is passed in
    rather than looked up because the glyphs live in the frontend, and a second copy of that list
    here could only drift from the one that draws.
    """
    gaps: list[VocabularyGap] = []
    aliases = views.resource_role_aliases(pack)
    capabilities = views.entity_type_capabilities(pack)
    contact_types = views.contact_instrumented_types(pack)
    named_roles = _roles_named_by_models(pack)

    # 1. A role nothing answers. The binder falls back to the region's service point, so the action
    #    happens in the middle of the room rather than at an object — and no contact sensor fires.
    for role, intents in sorted(named_roles.items()):
        if views.resource_types_for_role(pack, role):
            continue
        gaps.append(
            VocabularyGap(
                code="ROLE_WITHOUT_FURNITURE",
                severity="warning",
                subject=role,
                message=f"No furniture answers to '{role}'.",
                consequence=(
                    "The step binds to the room's service point instead of an object, so it "
                    "happens in the middle of the floor and no sensor on a real fixture sees it."
                ),
                details={"usedBy": sorted(intents)},
            )
        )

    # 2. A type that declares no capabilities keeps every one of them, which is the opposite of
    #    what an author adding it expects.
    for item in pack.entity_types:
        if item.capabilities:
            continue
        gaps.append(
            VocabularyGap(
                code="ENTITY_TYPE_WITHOUT_CAPABILITIES",
                severity="warning",
                subject=item.entity_type,
                message=f"'{item.display_name}' says nothing about what it is for.",
                consequence=(
                    "A type with no capabilities keeps all of them, so it becomes a candidate for "
                    "every activity and can win a binding it has no business winning."
                ),
            )
        )

    # 3. A capability no furniture offers. Not fatal — every region carries a service point that
    #    answers anything, which is what keeps a scenario naming an unusual capability simulable —
    #    but it means the action happens in the middle of the room rather than at an object, and it
    #    is the first thing to check when a newly authored action does not touch what it should.
    offered = {
        value for values in capabilities.values() for value in values
    } | UNIVERSAL_CAPABILITIES
    for action in pack.actions:
        unmet = sorted(
            {
                requirement.capability
                for requirement in action.definition.required_capabilities
                if requirement.capability not in offered
                and requirement.capability not in SELF_CAPABILITIES
            }
        )
        if unmet:
            gaps.append(
                VocabularyGap(
                    code="CAPABILITY_NO_FURNITURE_OFFERS",
                    severity="warning",
                    subject=action.action_type,
                    message=(
                        f"No furniture offers {', '.join(unmet)}, which '{action.action_type}' "
                        "asks for."
                    ),
                    consequence=(
                        "The action still runs — the room's service point answers anything — but "
                        "it happens on open floor rather than at an object, so no fixture sensor "
                        "records it."
                    ),
                    details={"capabilities": unmet},
                )
            )

    # 4. An action nothing calls. Harmless, but it is usually a half-finished edit.
    used = {
        node.action_type
        for intent in pack.intents
        for node in intent.process_model.nodes
        if node.action_type is not None
    }
    for action in sorted(pack.actions, key=lambda item: item.action_type):
        if action.action_type not in used:
            gaps.append(
                VocabularyGap(
                    code="ACTION_UNUSED",
                    severity="note",
                    subject=action.action_type,
                    message=f"No activity uses '{action.action_type}'.",
                    consequence=(
                        "It costs nothing, but nothing in a generated dataset will show it."
                    ),
                )
            )

    # 5. Furniture that opens but carries no contact sensor. The door swings in the simulation and
    #    the log never mentions it.
    openable = {
        item.entity_type
        for item in pack.entity_types
        if "openable" in item.capabilities and item.entity_type not in contact_types
    }
    for entity_type in sorted(openable):
        gaps.append(
            VocabularyGap(
                code="OPENABLE_WITHOUT_CONTACT_SENSOR",
                severity="note",
                subject=entity_type,
                message=f"'{entity_type}' can be opened but has no contact sensor.",
                consequence=(
                    "Opening it produces motion but no door event, so the log cannot tell it "
                    "apart from standing next to it."
                ),
            )
        )

    # 6. No glyph: the plan and the replay draw it as an anonymous box.
    if drawable_types:
        for item in pack.entity_types:
            if item.symbol_body or item.symbol_id or item.entity_type in drawable_types:
                continue
            gaps.append(
                VocabularyGap(
                    code="ENTITY_TYPE_WITHOUT_SYMBOL",
                    severity="note",
                    subject=item.entity_type,
                    message=f"'{item.display_name}' has no drawing.",
                    consequence=(
                        "It appears on the plan and in the replay as a plain rectangle, so a "
                        "reader cannot tell it from any other object."
                    ),
                )
            )

    # 7. An intent whose role literals name furniture the pack does not have at all. Distinct from
    #    (1): there the role is unanswered, here the author has named a type that does not exist.
    known_types = {item.entity_type for item in pack.entity_types}
    for role, intents in sorted(named_roles.items()):
        if role in aliases or role in known_types:
            continue
        if views.resource_types_for_role(pack, role):
            continue
        # Already reported by (1); recorded here only when it looks like a typo for a real type.
        near = sorted(item for item in known_types if role in item or item in role)
        if near:
            gaps.append(
                VocabularyGap(
                    code="ROLE_LOOKS_LIKE_A_TYPO",
                    severity="warning",
                    subject=role,
                    message=f"'{role}' answers to nothing, but {', '.join(near)} looks close.",
                    consequence=(
                        "Probably a misspelling, in which case the step binds to the wrong place."
                    ),
                    details={"didYouMean": near, "usedBy": sorted(intents)},
                )
            )

    order = {"blocking": 0, "warning": 1, "note": 2}
    gaps.sort(key=lambda item: (order[item.severity], item.code, item.subject))
    return VocabularyGapsReport(pack_id=pack.pack_id, digest=pack.digest, gaps=gaps)
