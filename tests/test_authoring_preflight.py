from __future__ import annotations

import json
from pathlib import Path

from smart_home_sim.authoring.preflight import (
    _ABSENT,
    _UNKNOWN,
    _actual_detail,
    _apply_effect,
    _is_definitely_false,
    _join,
    _resolve_arguments,
)
from smart_home_sim.compiler.service import compile_payload
from smart_home_sim.domain.behavior import EffectOperation, ProcessNode
from smart_home_sim.domain.models import Scenario

ROOT = Path(__file__).parents[1]


def test_abstract_state_join_effects_and_precondition_operators() -> None:
    joined = _join(
        {"resident.at_home": True, "resident.location": "home"},
        {"resident.at_home": False, "resident.location": "home"},
    )
    assert joined["resident.at_home"] is _UNKNOWN
    assert joined["resident.location"] == "home"

    state = _apply_effect({"count": 2}, "count", EffectOperation.increment, 3)
    assert state["count"] == 5
    state = _apply_effect(state, "count", EffectOperation.decrement, 1)
    assert state["count"] == 4
    state = _apply_effect({"items": ["a"]}, "items", EffectOperation.append, "b")
    assert state["items"] == ["a", "b"]
    state = _apply_effect(state, "items", EffectOperation.remove, "a")
    assert state["items"] == ["b"]

    assert _is_definitely_false(_ABSENT, "exists", None)
    assert _is_definitely_false(True, "not_exists", None)
    assert _is_definitely_false("same", "ne", "same")
    assert not _is_definitely_false("same", "unsupported", "same")
    assert _actual_detail(_UNKNOWN) == "unknown"


def test_activity_location_argument_is_resolved_from_canonical_activity() -> None:
    payload = json.loads(
        (ROOT / "examples/authoring/minimal.authoring-bundle.json").read_text(
            encoding="utf-8"
        )
    )
    scenario = Scenario.model_validate_json(json.dumps(payload["scenario"]))
    compilation = compile_payload(payload["scenario"])
    assert compilation.plan is not None
    activity = compilation.plan.days[0].activities[0]
    node = ProcessNode.model_validate_json(
        json.dumps(
            {
                "nodeId": "move",
                "kind": "action",
                "actionType": "move_to",
                "arguments": {
                    "destination": {"source": "activity_location", "index": 0}
                },
                "durationWeight": 1,
            }
        )
    )

    resolved = _resolve_arguments(node, activity, scenario, scenario.days[0], {})

    assert resolved is not None
    assert activity.location_ids[0] in resolved.values()
