from __future__ import annotations

import json

import pytest

from smart_home_sim.behavior.service import default_action_catalog_path
from smart_home_sim.domain.behavior import ProcessNodeKind
from smart_home_sim.hybrid_planning.intents import (
    INTENT_CATALOG,
    away_intent_specs,
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


def test_home_work_is_an_in_home_intent_with_a_room() -> None:
    """`work_from_home` is the intent that made a home-based occupation expressible at all.

    Before it the only work intent was `work_shift`, which the away list places `outdoors`, so a
    freelancer's working day could be declared either as an eight-hour absence she never took or
    not at all.
    """
    spec = intent_spec("work_from_home")

    assert spec.default_location == "living_room"
    assert spec.intent_id in intent_ids()


def test_a_night_toilet_visit_declares_two_rooms_and_ends_in_bed() -> None:
    """The nocturnal trip is its own intent because it ends differently from a daytime one.

    While it borrowed `morning_toilet_and_wash` it inherited a daytime process, which ends wherever
    the last action left the resident — standing at the washbasin. A day is compiled as its own
    bundle, so no `sleep` is in progress to resume: nothing put her back to bed, and `wake_up`
    began by walking her to a bedroom she had never left, on every night the drive layer gave her a
    visit. The return has to be part of the visit, and `return_location` is what carries the room
    it walks to.
    """
    spec = intent_spec("night_toilet_visit")
    assert spec.default_location == "bathroom"
    assert spec.return_location == "bedroom"
    # No other intent needs one: everything else ends in the room it ran in.
    assert [item.intent_id for item in INTENT_CATALOG if item.return_location] == [
        "night_toilet_visit"
    ]

    model = reference_model("night_toilet_visit")
    actions = [node for node in model.nodes if node.kind is ProcessNodeKind.action]
    assert actions[-1].action_type == "change_posture"
    assert actions[-1].arguments["posture"].value == "lying"
    # The room it walks back to is the *second* the activity declares; reading index 0 for both
    # would walk her to the toilet to go to sleep.
    assert actions[-2].action_type == "move_to"
    assert actions[-2].arguments["destination"].index == 1


def test_a_resting_process_gets_the_resident_back_on_her_feet() -> None:
    """Only the two processes that end in bed leave the body down.

    `rest_or_nap`, `read_and_rest` and `watch_television` sat or laid the resident down and then
    said nothing more about her, so the posture stayed whatever they left. Nothing inside those
    activities was wrong; the damage landed on the next one, which walked her across the flat still
    recorded as sitting — every `eat_dinner` after an afternoon nap, 8.8 metres from the bedroom to
    the kitchen, seated.
    """
    down: dict[str, set[str]] = {}
    for intent, model in load_reference_models().items():
        nodes = {node.node_id: node for node in model.nodes}
        outgoing: dict[str, list[str]] = {}
        for edge in model.edges:
            outgoing.setdefault(edge.source_node_id, []).append(edge.target_node_id)
        final: set[str] = set()
        seen: set[tuple[str, str | None]] = set()
        stack = [(node.node_id, None) for node in model.nodes if node.kind is ProcessNodeKind.start]
        while stack:
            node_id, posture = stack.pop()
            node = nodes[node_id]
            if node.kind is ProcessNodeKind.action and node.action_type == "change_posture":
                posture = str(node.arguments["posture"].value)
            if node.kind is ProcessNodeKind.end:
                if posture is not None:
                    final.add(posture)
                continue
            for target in outgoing.get(node_id, []):
                if (target, posture) not in seen:
                    seen.add((target, posture))
                    stack.append((target, posture))
        if final - {"standing"}:
            down[intent] = final

    # Both of these are right: the resident is in bed, and `wake_up` is what stands her up.
    assert set(down) == {"sleep", "night_toilet_visit"}


def test_the_home_and_away_vocabularies_do_not_overlap() -> None:
    """They are printed side by side in the authoring prompt; an intent in both is an instruction
    to guess where the resident is."""
    away = {spec.intent_id for spec in away_intent_specs()}

    assert away.isdisjoint(set(intent_ids()))
    assert "work_shift" in away
    assert "work_from_home" not in away
