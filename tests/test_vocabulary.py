"""The built-in pack must *be* today's behaviour, not merely resemble it.

The pack exists so a researcher can change the vocabulary. The risk that buys is that it changes
the vocabulary on its own — a default that drifts from the tables it replaced would silently alter
every dataset generated after the refactor, and nothing downstream would report it. So the round
trip is pinned here: the tables rebuilt from the default pack equal the constants it was built
from, key for key.
"""

from __future__ import annotations

import json

import pytest

from smart_home_sim.domain.environment import ENTITY_TYPE_CAPABILITIES
from smart_home_sim.domain.models import RESOURCE_ROLE_ALIASES, resource_types_for_role
from smart_home_sim.domain.sensors import CONTACT_INSTRUMENTED_TYPES
from smart_home_sim.domain.vocabulary import VocabularyEntityType, VocabularyPack
from smart_home_sim.hybrid_planning.intents import (
    INTENT_CATALOG,
    away_intent_specs,
    load_reference_models,
)
from smart_home_sim.sensors.service import PIR_ACTIVITY_ACTION_TYPES
from smart_home_sim.simulation.service import PUNCTUAL_ACTION_SECONDS
from smart_home_sim.vocabulary import views
from smart_home_sim.vocabulary.active import use_pack
from smart_home_sim.vocabulary.defaults import builtin_pack


@pytest.fixture(scope="module")
def pack() -> VocabularyPack:
    return builtin_pack()


def test_gesture_table_round_trips(pack: VocabularyPack) -> None:
    assert views.gesture_seconds_table(pack) == PUNCTUAL_ACTION_SECONDS


def test_motion_action_types_round_trip(pack: VocabularyPack) -> None:
    assert views.motion_action_types(pack) == PIR_ACTIVITY_ACTION_TYPES


def test_entity_capabilities_round_trip(pack: VocabularyPack) -> None:
    assert views.entity_type_capabilities(pack) == ENTITY_TYPE_CAPABILITIES


def test_role_aliases_round_trip(pack: VocabularyPack) -> None:
    assert views.resource_role_aliases(pack) == RESOURCE_ROLE_ALIASES


def test_contact_types_round_trip(pack: VocabularyPack) -> None:
    assert views.contact_instrumented_types(pack) == CONTACT_INSTRUMENTED_TYPES


def test_intent_catalog_round_trips(pack: VocabularyPack) -> None:
    assert views.intent_specs(pack) == INTENT_CATALOG


def test_away_intents_round_trip(pack: VocabularyPack) -> None:
    assert views.away_intent_specs(pack) == away_intent_specs()


def test_reference_models_round_trip(pack: VocabularyPack) -> None:
    assert views.reference_models(pack) == load_reference_models()


def test_role_resolution_matches_the_table(pack: VocabularyPack) -> None:
    """Every role any process model names must resolve to the same furniture as before."""
    roles = {
        argument.value
        for intent in pack.intents
        for node in intent.process_model.nodes
        for argument in node.arguments.values()
        if isinstance(argument.value, str)
    }
    assert roles, "the reference models should name roles"
    for role in roles:
        assert views.resource_types_for_role(pack, role) == resource_types_for_role(role), role


def test_pack_survives_a_json_round_trip(pack: VocabularyPack) -> None:
    """An edited pack reaches the engine through a file, so the digest must survive the trip."""
    encoded = pack.model_dump_json(by_alias=True)
    restored = VocabularyPack.model_validate_json(encoded)
    assert restored.digest == pack.digest
    assert restored.label_space_digest == pack.label_space_digest


def test_label_space_digest_ignores_everything_but_the_labels(pack: VocabularyPack) -> None:
    """Changing how an activity is performed must not read as a change to the ground truth.

    This is the distinction the whole extension story rests on: adding an action or retiming a
    gesture refines the performance and leaves two datasets comparable; renaming or adding an
    intent does not.
    """
    retimed = pack.model_copy(deep=True)
    retimed.actions[0].gesture_seconds = (retimed.actions[0].gesture_seconds or 1.0) + 5.0
    assert retimed.digest != pack.digest
    assert retimed.label_space_digest == pack.label_space_digest

    relabelled = pack.model_copy(deep=True)
    relabelled.intents[0].label = "Something else entirely"
    assert relabelled.label_space_digest != pack.label_space_digest


def test_a_process_model_cannot_call_an_action_the_pack_lacks(pack: VocabularyPack) -> None:
    """Deleting an action must fail loudly at edit time, not hours later inside a run."""
    broken = pack.model_dump(mode="json", by_alias=True)
    still_used = broken["intents"][0]["processModel"]["nodes"][1]["actionType"]
    broken["actions"] = [
        item for item in broken["actions"] if item["definition"]["actionType"] != still_used
    ]
    # `ContractModel` is strict, so a document round-trips through JSON rather than through a
    # dict: a bare "string" is not a `ValueType` until the JSON parser has produced it.
    with pytest.raises(ValueError, match="actions this pack does not declare"):
        VocabularyPack.model_validate_json(json.dumps(broken))


def test_a_travel_action_cannot_also_claim_a_gesture_length(pack: VocabularyPack) -> None:
    payload = pack.model_dump(mode="json", by_alias=True)
    for action in payload["actions"]:
        if action["isTravel"]:
            action["gestureSeconds"] = 4.0
            break
    with pytest.raises(ValueError, match="as long as the walk"):
        VocabularyPack.model_validate_json(json.dumps(payload))


# --- the wiring: does an edit actually reach the engine? ------------------------------------


def test_an_edited_gesture_reaches_the_simulator(pack: VocabularyPack) -> None:
    """The point of the whole pack: a length the researcher changes is the length a run uses.

    Read through the simulator's own accessor rather than through `views`, so the test fails if the
    call site stops asking the pack — which is the failure that would otherwise be invisible, a run
    quietly generated on the built-in vocabulary while the editor showed something else.
    """
    from smart_home_sim.simulation.service import _gesture_table

    assert _gesture_table()["open"] == 3.0

    retimed = pack.model_copy(deep=True)
    for action in retimed.actions:
        if action.action_type == "open":
            action.gesture_seconds = 9.0
    with use_pack(retimed):
        assert _gesture_table()["open"] == 9.0
    assert _gesture_table()["open"] == 3.0


def test_a_new_action_is_seen_by_the_motion_detector(pack: VocabularyPack) -> None:
    """An author adding an action declares its observability, and the sensor projector obeys."""
    from smart_home_sim.sensors.service import PIR_ACTIVITY_ACTION_TYPES

    assert "wait" not in PIR_ACTIVITY_ACTION_TYPES
    edited = pack.model_copy(deep=True)
    for action in edited.actions:
        if action.action_type == "wait":
            action.observability.motion_at_object = True
    with use_pack(edited) as active:
        assert "wait" in views.motion_action_types(active)


def test_a_new_intent_is_resolvable_everywhere(pack: VocabularyPack) -> None:
    """Adding an activity used to require editing a frozen tuple. It must now be data alone."""
    from smart_home_sim.hybrid_planning.intents import intent_catalog, intent_spec

    extended = pack.model_copy(deep=True)
    invented = extended.intents[0].model_copy(deep=True)
    invented.intent_id = "water_the_plants"
    invented.label = "Water the plants"
    invented.category = "chores"
    invented.default_location = "balcony"
    invented.return_location = None
    extended.intents.append(invented)

    with use_pack(extended):
        assert len(intent_catalog()) == len(pack.intents) + 1
        spec = intent_spec("water_the_plants")
        assert spec.label == "Water the plants"
        assert spec.default_location == "balcony"

    with pytest.raises(KeyError):
        intent_spec("water_the_plants")


def test_new_furniture_gets_its_capabilities_and_its_door_sensor(pack: VocabularyPack) -> None:
    """A type an author adds must stop being permissive and start being a specific thing."""
    from smart_home_sim.domain.environment import capabilities_for_entity_type
    from smart_home_sim.domain.models import resource_types_for_role
    from smart_home_sim.domain.sensors import contact_instrumented_types

    assert capabilities_for_entity_type("bookcase") is None
    assert "bookcase" not in contact_instrumented_types()

    extended = pack.model_copy(deep=True)
    extended.entity_types.append(
        VocabularyEntityType(
            entity_type="bookcase",
            display_name="Bookcase",
            capabilities=["storage_support", "openable", "storable", "graspable"],
            role_aliases=["book_storage", "books"],
            contact_instrumented=True,
        )
    )
    with use_pack(extended):
        assert capabilities_for_entity_type("bookcase") == frozenset(
            {"storage_support", "openable", "storable", "graspable"}
        )
        assert "bookcase" in contact_instrumented_types()
        assert resource_types_for_role("book_storage") == frozenset({"bookcase"})

    assert capabilities_for_entity_type("bookcase") is None


def test_a_workspace_stores_edits_and_can_forget_them(tmp_path) -> None:
    """Autosave, reload and reset, through the store a worker actually reads."""
    from smart_home_sim.application import vocabulary_store

    assert vocabulary_store.load(tmp_path).customised is False

    edited = builtin_pack().model_copy(deep=True)
    edited.pack_id = "house-with-a-bookcase"
    vocabulary_store.save(tmp_path, edited)

    reloaded = vocabulary_store.load(tmp_path)
    assert reloaded.customised is True
    assert reloaded.pack.pack_id == "house-with-a-bookcase"
    assert reloaded.pack.digest == edited.digest

    try:
        assert vocabulary_store.adopt(tmp_path).pack_id == "house-with-a-bookcase"
        from smart_home_sim.vocabulary.active import active_pack

        assert active_pack().pack_id == "house-with-a-bookcase"
    finally:
        from smart_home_sim.vocabulary.active import set_active_pack

        set_active_pack(None)

    assert vocabulary_store.reset(tmp_path).customised is False
    assert vocabulary_store.load(tmp_path).pack.pack_id == "builtin"
    # Reset is a deletion, not a copy of the defaults: leaving a duplicate behind would let it
    # drift from the bundled catalogs the next time those are revised.
    assert not vocabulary_store.pack_path(tmp_path).exists()


def test_an_unreadable_stored_pack_is_never_silently_ignored(tmp_path) -> None:
    """Falling back to the default would label a dataset with a vocabulary it was not built on."""
    from smart_home_sim.application import vocabulary_store

    path = vocabulary_store.pack_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not a pack", encoding="utf-8")
    with pytest.raises(vocabulary_store.VocabularyStoreError):
        vocabulary_store.load(tmp_path)
