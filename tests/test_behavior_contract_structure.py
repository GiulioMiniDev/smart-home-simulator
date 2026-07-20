from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from smart_home_sim.domain.behavior import (
    ActionDefinition,
    PersonalProcessPackage,
    ProcessEdge,
    ProcessNode,
    ValueExpression,
    VariableCondition,
    VariableDefinition,
)


def test_personal_package_requires_complete_authoring_provenance() -> None:
    from pathlib import Path

    root = Path(__file__).parents[1]
    payload = json.loads(
        (root / "examples/behavior/minimal_valid_scenario.behavior.json").read_text()
    )
    payload["provenance"].pop("generatedAt")

    with pytest.raises(ValidationError):
        PersonalProcessPackage.model_validate_json(json.dumps(payload))


def test_action_definition_rejects_unknown_template_parameter() -> None:
    with pytest.raises(ValidationError):
        ActionDefinition.model_validate_json(
            json.dumps(
                {
                    "actionType": "broken",
                    "description": "Broken action",
                    "effects": [
                        {
                            "factTemplate": "entity.{missing}.active",
                            "operation": "set",
                            "value": True,
                        }
                    ],
                }
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "variableId": "v",
            "displayName": "V",
            "description": "Variable",
            "valueType": "string",
            "scope": "derived_calendar",
            "sourcePath": "invalid",
        },
        {
            "variableId": "v",
            "displayName": "V",
            "description": "Variable",
            "valueType": "string",
            "scope": "resident",
        },
    ],
)
def test_variable_definition_rejects_invalid_source(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VariableDefinition.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "payload",
    [
        {"source": "literal"},
        {"source": "literal", "value": "x", "index": 0},
        {"source": "variable"},
        {"source": "variable", "variableId": "v", "value": "x"},
        {"source": "activity_location"},
        {"source": "activity_resource", "index": 0, "value": "x"},
        {"source": "actor", "value": "x"},
    ],
)
def test_value_expression_rejects_inconsistent_source_fields(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ValueExpression.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "payload",
    [
        {"nodeId": "n", "kind": "action", "durationWeight": 1},
        {
            "nodeId": "n",
            "kind": "action",
            "actionType": "wait",
            "durationWeight": 1,
            "maxIterations": 2,
        },
        {"nodeId": "n", "kind": "start", "actionType": "wait"},
        {"nodeId": "n", "kind": "loop"},
        {"nodeId": "n", "kind": "choice", "maxIterations": 2},
    ],
)
def test_process_node_rejects_fields_for_wrong_kind(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ProcessNode.model_validate_json(json.dumps(payload))


def test_default_edge_cannot_have_condition() -> None:
    with pytest.raises(ValidationError):
        ProcessEdge.model_validate_json(
            json.dumps(
                {
                    "sourceNodeId": "a",
                    "targetNodeId": "b",
                    "isDefault": True,
                    "condition": {"variableId": "day.type", "operator": "eq", "value": "x"},
                }
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"variableId": "v", "operator": "truthy", "value": True},
        {"variableId": "v", "operator": "eq"},
        {"variableId": "v", "operator": "gt", "value": "high"},
        {"variableId": "v", "operator": "in", "value": "x"},
    ],
)
def test_variable_condition_rejects_invalid_operator_values(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VariableCondition.model_validate_json(json.dumps(payload))


def test_valid_contract_variants_round_trip() -> None:
    expressions = [
        {"source": "literal", "value": "x"},
        {"source": "variable", "variableId": "day.type"},
        {"source": "activity_location", "index": 0},
        {"source": "activity_resource", "index": 0},
        {"source": "activity_intent"},
        {"source": "actor"},
    ]
    for payload in expressions:
        expression = ValueExpression.model_validate_json(json.dumps(payload))
        assert expression.source.value == payload["source"]

    action = ProcessNode.model_validate_json(
        json.dumps(
            {
                "nodeId": "a",
                "kind": "action",
                "actionType": "leave_home",
                "durationWeight": 1,
            }
        )
    )
    loop = ProcessNode.model_validate_json(
        json.dumps({"nodeId": "l", "kind": "loop", "maxIterations": 2})
    )
    assert action.action_type == "leave_home"
    assert loop.max_iterations == 2
