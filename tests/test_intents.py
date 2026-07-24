from __future__ import annotations

import json

import pytest

from smart_home_sim.behavior.service import default_action_catalog_path
from smart_home_sim.domain.behavior import ProcessNodeKind
from smart_home_sim.hybrid_planning.intents import (
    INTENT_CATALOG,
    intent_ids,
    intent_spec,
    load_reference_models,
    reference_model,
)
from smart_home_sim.hybrid_planning.world import STANDARD_EXTERNAL, STANDARD_ROOMS


def _action_vocabulary() -> set[str]:
    catalog = json.loads(default_action_catalog_path("1.1.0").read_text(encoding="utf-8"))
    return {action["actionType"] for action in catalog["actions"]}


def test_catalog_ids_are_unique() -> None:
    ids = intent_ids()
    assert len(ids) == len(set(ids)) == len(INTENT_CATALOG)


def test_default_locations_are_standard_world_locations() -> None:
    valid = set(STANDARD_ROOMS) | set(STANDARD_EXTERNAL)
    assert all(spec.default_location in valid for spec in INTENT_CATALOG)


def test_every_intent_has_a_reference_model() -> None:
    models = load_reference_models()
    assert set(models) == set(intent_ids())
    assert all(model.resident_id == "reference_resident" for model in models.values())


def test_reference_models_use_only_catalogued_actions() -> None:
    vocabulary = _action_vocabulary()
    for model in load_reference_models().values():
        for node in model.nodes:
            if node.kind is ProcessNodeKind.action:
                assert node.action_type in vocabulary


def test_reference_model_lookup() -> None:
    model = reference_model("take_morning_medication")
    assert model.process_model_id == "reference__take_morning_medication"
    assert len(model.nodes) >= 2


def test_reference_model_unknown_raises() -> None:
    with pytest.raises(KeyError):
        reference_model("teleport")


def test_intent_spec_lookup_and_error() -> None:
    assert intent_spec("sleep").default_location == "bedroom"
    with pytest.raises(KeyError):
        intent_spec("nope")
