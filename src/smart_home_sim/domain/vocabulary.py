"""The vocabulary pack: everything a researcher may change about *what the resident can do*.

Until now that knowledge was split across four bundled catalogs and five Python tables, and the
Python half was the half that decided whether a change was possible at all. Adding an action meant
editing `PUNCTUAL_ACTION_SECONDS` so it had a length and `PIR_ACTIVITY_ACTION_TYPES` so a detector
could see it; adding a piece of furniture meant editing `ENTITY_TYPE_CAPABILITIES` so it was not
silently permissive and `RESOURCE_ROLE_ALIASES` so a process model could name it; adding an
activity meant editing a frozen tuple. None of that is knowledge about *the engine*. It is
knowledge about the world being simulated, which is the researcher's to state.

So it moves here, into one document that the engine reads and an editor writes. Three rules hold
the design together:

- **The default pack is today's behaviour, exactly.** `vocabulary.defaults` derives it from the
  bundled catalogs and the tables that used to be authoritative, and a test asserts the derived
  tables equal those constants. Opening the door to change must not change anything by itself.
- **A pack is identified, not just edited.** Every pack carries a `pack_id` and a digest, and a run
  records which one produced it. Two datasets built on different vocabularies are not comparable,
  and the only way to know is for each to say what it used.
- **The label space is versioned separately from the rest.** Adding an action or a piece of
  furniture refines how an activity is performed and leaves the ground-truth labels untouched.
  Adding or removing an *intent* changes what the dataset claims happened. `label_space_digest`
  covers only the intents, so a consumer can tell the two apart.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.behavior import (
    ActionDefinition,
    ProcessModel,
)

BUILTIN_PACK_ID = "builtin"

# The pack is the union of what these four artifacts used to say separately. Their versions are
# recorded so a pack can state what it was derived from even after it has been edited away from it.
SOURCE_ACTION_CATALOG = "action-catalog-1.1.0"
SOURCE_ACTIVITY_CATALOG = "activity-catalog-1.4.0"
SOURCE_REFERENCE_MODELS = "reference-process-models-1.4.0"


class ActionObservability(ContractModel):
    """What a sensor log gains when this action runs.

    Replaces membership of `PIR_ACTIVITY_ACTION_TYPES`, and adds the distinction that set could not
    express. Travel produced no entry there and looked unobserved, when in fact a walk is the
    richest evidence in the log — `sensors.service` reads the movement rather than the action, and
    a reader of the table had no way to know. Saying it here means an author adding a new travelling
    action gets the same treatment without touching the sensor projector.
    """

    # A body working at an object: pulses the detector watching that object's interaction point.
    motion_at_object: bool = False
    # A body crossing the flat: pulses every detector along the planned path.
    motion_along_path: bool = False

    @property
    def is_observable(self) -> bool:
        return self.motion_at_object or self.motion_along_path


class VocabularyAction(ContractModel):
    """One atomic action, with the engine facts that used to live in Python tables."""

    definition: ActionDefinition
    # `None` means elastic: the action is what an activity is *made* of, and it absorbs whatever
    # time the day allots, shared out by `durationWeight`. A number means a gesture with a length of
    # its own, which an activity's budget does not stretch. This is `PUNCTUAL_ACTION_SECONDS`.
    gesture_seconds: float | None = Field(default=None, ge=0)
    observability: ActionObservability = Field(default_factory=ActionObservability)
    # Travel actions sit at zero seconds in the old table because `_execute_action` floors them to
    # the planned path once the walk is known. The flag says so, rather than leaving a reader to
    # infer it from a suspicious zero.
    is_travel: bool = False

    @property
    def action_type(self) -> str:
        return self.definition.action_type

    @model_validator(mode="after")
    def check_travel_timing(self) -> VocabularyAction:
        if self.is_travel and self.gesture_seconds not in (None, 0.0):
            raise ValueError(
                "a travel action takes as long as the walk it plans, so it cannot also declare a "
                "gesture length"
            )
        return self


class VocabularyEntityType(ContractModel):
    """A kind of furniture, what it is for, and how it is drawn.

    `capabilities` is `ENTITY_TYPE_CAPABILITIES`; `role_aliases` is one row of
    `RESOURCE_ROLE_ALIASES`; `contact_instrumented` is membership of `CONTACT_INSTRUMENTED_TYPES`.
    Keeping them on one record is the point: they are three answers to the same question — what is
    this object for — and holding them in three tables is what let a sofa declare
    `food_preparation` while the washing machine, which a deployment actually fits with a reed
    switch, was never described to an author as a container at all.
    """

    entity_type: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    role_aliases: list[str] = Field(default_factory=list)
    contact_instrumented: bool = False
    # The glyph the plan canvas and the replay scene draw for this type. `symbol_body` carries the
    # SVG for a type the bundled set does not cover, so adding furniture does not require a
    # frontend release.
    symbol_id: str | None = None
    symbol_body: str | None = None

    @model_validator(mode="after")
    def check_unique_values(self) -> VocabularyEntityType:
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities must not repeat")
        if len(self.role_aliases) != len(set(self.role_aliases)):
            raise ValueError("roleAliases must not repeat")
        return self


class VocabularyIntent(ContractModel):
    """One activity: its label, where it happens, and the actions it decomposes into.

    This is `IntentSpec`, the activity catalog's entry and the reference process model, joined.
    They were three records about one thing, kept in a Python tuple and two JSON files that had to
    be edited in step; the tuple is the one that made an activity unaddable without a code change.
    """

    intent_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    category: str = Field(min_length=1)
    default_location: str = Field(min_length=1)
    # Where the activity leaves the resident, when that is not where it happened. Only a nocturnal
    # trip needs it: everything else ends in the room it ran in.
    return_location: str | None = None
    description: str = ""
    components: list[str] = Field(default_factory=list)
    # Labels in other people's datasets that this intent stands for. Absent is a real answer and
    # not a gap: an activity may have no equivalent in a benchmark recorded fifteen years ago, and
    # inventing one would be worse than saying so.
    external_mappings: dict[str, str] = Field(default_factory=dict)
    process_model: ProcessModel

    @model_validator(mode="after")
    def check_model_is_walkable(self) -> VocabularyIntent:
        node_ids = {node.node_id for node in self.process_model.nodes}
        dangling = {
            edge.source_node_id
            for edge in self.process_model.edges
            if edge.source_node_id not in node_ids
        } | {
            edge.target_node_id
            for edge in self.process_model.edges
            if edge.target_node_id not in node_ids
        }
        if dangling:
            raise ValueError(f"edges reference nodes that do not exist: {sorted(dangling)}")
        if self.return_location is not None and self.return_location == self.default_location:
            raise ValueError(
                "returnLocation is only for an activity that ends somewhere else; leave it unset "
                "when the resident stays where the activity happened"
            )
        return self


class VocabularyAwayIntent(ContractModel):
    """An activity that happens outside the dwelling.

    It carries no process model and needs none: nothing it does is observable by a home sensor, so
    the only fact the simulation takes from it is that the resident is out. Keeping these in the
    pack rather than reading them back out of the activity catalog by category means an author can
    add "walks the dog" without the in-home vocabulary growing an intent that a fixed sensor layout
    could not distinguish anyway.
    """

    intent_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = ""
    external_mappings: dict[str, str] = Field(default_factory=dict)


class VocabularyPack(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:vocabulary-pack:1.0.0",
            "title": "Smart Home Vocabulary Pack 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["vocabulary_pack"] = "vocabulary_pack"
    pack_id: str = Field(min_length=1)
    # What this pack was derived from, so an edited pack can still say where it started.
    base_pack_id: str = Field(default=BUILTIN_PACK_ID, min_length=1)
    source_catalogs: dict[str, str] = Field(default_factory=dict)
    actions: list[VocabularyAction] = Field(min_length=1)
    entity_types: list[VocabularyEntityType] = Field(default_factory=list)
    intents: list[VocabularyIntent] = Field(min_length=1)
    away_intents: list[VocabularyAwayIntent] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_internal_consistency(self) -> VocabularyPack:
        action_types = [item.action_type for item in self.actions]
        if len(action_types) != len(set(action_types)):
            raise ValueError("two actions share an actionType")
        intent_ids = [item.intent_id for item in self.intents]
        intent_ids.extend(item.intent_id for item in self.away_intents)
        if len(intent_ids) != len(set(intent_ids)):
            # The two lists are rendered side by side in an authoring prompt as "inside the
            # home" and "away from home", and an id printed in both is an instruction to guess.
            raise ValueError("two intents share an intentId")
        entity_types = [item.entity_type for item in self.entity_types]
        if len(entity_types) != len(set(entity_types)):
            raise ValueError("two entity types share an entityType")

        # A process model may only call actions this pack declares. Catching it here means an
        # author who deletes an action learns immediately which activity still needs it, instead of
        # a run failing hours later on a node nothing can execute.
        known = set(action_types)
        missing: dict[str, set[str]] = {}
        for intent in self.intents:
            for node in intent.process_model.nodes:
                if node.action_type is not None and node.action_type not in known:
                    missing.setdefault(intent.intent_id, set()).add(node.action_type)
        if missing:
            detail = "; ".join(
                f"{intent} calls {sorted(actions)}" for intent, actions in sorted(missing.items())
            )
            raise ValueError(f"process models call actions this pack does not declare: {detail}")

        # A role two furniture types both answer to is not an error — `washing_area` is genuinely
        # both the kitchen sink and the washbasin, and the binder prefers by room. A role no type
        # answers is not an error either; it falls back to the room's service point. Neither is
        # reported here. `gaps_report` says both out loud, where an author can act on them.
        return self

    @property
    def digest(self) -> str:
        """Content digest of the whole pack, for a run to record what produced it."""
        return self._digest_of(self.model_dump(mode="json", by_alias=True))

    @property
    def label_space_digest(self) -> str:
        """Digest of the intent vocabulary alone — the part that is ground truth.

        Two datasets whose `label_space_digest` matches can be compared directly even if their
        packs differ elsewhere: they name the same activities, and only the way those activities
        are carried out has moved. When it differs, they are answering different questions, and no
        score computed across both means anything.
        """
        return self._digest_of(
            sorted(
                (
                    {
                        "intentId": intent.intent_id,
                        "label": intent.label,
                        "category": intent.category,
                        "defaultLocation": intent.default_location,
                        "returnLocation": intent.return_location,
                    }
                    for intent in self.intents
                ),
                key=lambda item: item["intentId"],
            )
        )

    @staticmethod
    def _digest_of(payload: object) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def action(self, action_type: str) -> VocabularyAction:
        for item in self.actions:
            if item.action_type == action_type:
                return item
        raise KeyError(f"unknown action: {action_type!r}")

    def intent(self, intent_id: str) -> VocabularyIntent:
        for item in self.intents:
            if item.intent_id == intent_id:
                return item
        raise KeyError(f"unknown intent: {intent_id!r}")

    def entity_type(self, entity_type: str) -> VocabularyEntityType | None:
        for item in self.entity_types:
            if item.entity_type == entity_type:
                return item
        return None
