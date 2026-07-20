from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from smart_home_sim.behavior import service
from smart_home_sim.behavior.issues import behavior_issue
from smart_home_sim.behavior.service import validate_behavior_files, validate_behavior_payloads
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    ActivityCatalog,
    PersonalProcessPackage,
    VariableCatalog,
    VariableCondition,
)
from smart_home_sim.domain.models import Scenario

ROOT = Path(__file__).parents[1]


@pytest.fixture
def behavior_payloads() -> dict[str, Any]:
    def load(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    return {
        "package": load(ROOT / "examples/behavior/minimal_valid_scenario.behavior.json"),
        "scenario": load(ROOT / "examples/valid/minimal.json"),
        "activities": load(ROOT / "src/smart_home_sim/catalogs/activity-catalog-1.0.0.json"),
        "variables": load(ROOT / "src/smart_home_sim/catalogs/variable-catalog-1.0.0.json"),
        "actions": load(ROOT / "src/smart_home_sim/catalogs/action-catalog-1.0.0.json"),
    }


def validate(values: dict[str, Any]):
    return validate_behavior_payloads(
        values["package"],
        values["scenario"],
        values["activities"],
        values["variables"],
        values["actions"],
    )


def test_complete_examples_cover_every_activity() -> None:
    cases = (
        ("minimal_valid_scenario.behavior.json", "minimal.json", 2),
        ("mario_rossi_week_2026_10_12.behavior.json", "mario_week.json", 173),
    )
    for package_name, scenario_name, expected_count in cases:
        report = validate_behavior_files(
            ROOT / "examples/behavior" / package_name,
            ROOT / "examples/valid" / scenario_name,
        )
        assert report.valid
        assert report.summary.covered_activity_count == expected_count
        assert report.package_sha256 is not None


def test_prompt_conformant_external_llm_package_uses_the_same_validator(
    behavior_payloads: dict[str, Any],
) -> None:
    values = copy.deepcopy(behavior_payloads)
    values["package"]["provenance"] = {
        "authorType": "external_llm",
        "generatorName": "prompt-conformance-fixture",
        "generatorVersion": "1.0.0",
        "modelName": "fixture-model",
        "promptTemplateVersion": "personal-process-models-1.0.0",
        "generatedAt": "2026-07-20T12:00:00+02:00",
        "humanReviewed": False,
        "parameters": {"temperature": 0},
    }

    assert validate(values).valid

    prompt = (ROOT / "prompts/generate-personal-process-models-1.0.0.md").read_text()
    assert "personal-process-package-1.0.0.schema.json" in prompt
    assert "implementedComponents" in prompt
    assert "durationWeight" in prompt


def test_golden_behavior_report_is_stable() -> None:
    report = validate_behavior_files(
        ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior.json",
        ROOT / "examples/valid/mario_week.json",
    )
    golden = json.loads((ROOT / "tests/golden/mario_week.behavior-report.json").read_text())

    assert report.model_dump(mode="json", by_alias=True) == golden


@pytest.mark.parametrize(
    "filename",
    ["unknown_action.json", "missing_binding.json", "unbounded_cycle.json"],
)
def test_invalid_behavior_examples_are_rejected(filename: str) -> None:
    report = validate_behavior_files(
        ROOT / "examples/behavior/invalid" / filename,
        ROOT / "examples/valid/minimal.json",
    )

    assert not report.valid


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("scenario_mismatch", "PACKAGE_SCENARIO_MISMATCH"),
        ("catalog_mismatch", "CATALOG_REFERENCE_MISMATCH"),
        ("duplicate_activity", "DUPLICATE_CATALOG_ENTRY"),
        ("duplicate_component", "DUPLICATE_CATALOG_ENTRY"),
        ("unknown_activity_component", "UNKNOWN_ACTIVITY_COMPONENT"),
        ("unknown_component_action", "UNKNOWN_ACTION_TYPE"),
        ("unknown_activity_variable", "UNKNOWN_VARIABLE"),
        ("duplicate_variable", "DUPLICATE_CATALOG_ENTRY"),
        ("duplicate_action", "DUPLICATE_CATALOG_ENTRY"),
        ("duplicate_parameter", "DUPLICATE_ACTION_PARAMETER"),
        ("duplicate_model", "DUPLICATE_PROCESS_MODEL_ID"),
        ("unknown_model_resident", "UNKNOWN_RESIDENT"),
        ("duplicate_node", "DUPLICATE_NODE_ID"),
        ("duplicate_edge", "DUPLICATE_EDGE"),
        ("unknown_edge_node", "UNKNOWN_EDGE_NODE"),
        ("missing_start", "GRAPH_START_INVALID"),
        ("missing_end", "GRAPH_END_INVALID"),
        ("invalid_degree", "INVALID_GRAPH_DEGREE"),
        ("invalid_choice", "CHOICE_BRANCH_INVALID"),
        ("dead_node", "GRAPH_NODE_DEAD"),
        ("unbounded_cycle", "GRAPH_CYCLE_UNBOUNDED"),
        ("unknown_action", "UNKNOWN_ACTION_TYPE"),
        ("invalid_arguments", "INVALID_ACTION_ARGUMENTS"),
        ("literal_type", "ACTION_ARGUMENT_TYPE_MISMATCH"),
        ("literal_allowed", "ACTION_ARGUMENT_TYPE_MISMATCH"),
        ("literal_reference", "INVALID_LITERAL_REFERENCE"),
        ("unknown_variable", "UNKNOWN_VARIABLE"),
        ("invalid_variable_value", "INVALID_VARIABLE_VALUE"),
        ("required_variable_missing", "REQUIRED_VARIABLE_MISSING"),
        ("variable_source_type", "VARIABLE_SOURCE_TYPE_MISMATCH"),
        ("variable_source_value", "VARIABLE_SOURCE_VALUE_INVALID"),
        ("duplicate_binding", "DUPLICATE_BINDING_ID"),
        ("unknown_binding_resident", "UNKNOWN_RESIDENT"),
        ("unknown_intent", "UNKNOWN_INTENT"),
        ("unknown_model", "UNKNOWN_PROCESS_MODEL"),
        ("resident_mismatch", "PROCESS_MODEL_RESIDENT_MISMATCH"),
        ("component_mismatch", "PROCESS_COMPONENT_MISMATCH"),
        ("component_action_missing", "PROCESS_COMPONENT_MISMATCH"),
        ("movement_missing", "PROCESS_MOVEMENT_MISSING"),
        ("missing_binding", "MISSING_PROCESS_BINDING"),
        ("ambiguous_binding", "AMBIGUOUS_PROCESS_BINDING"),
    ],
)
def test_semantic_failures_are_reported(
    behavior_payloads: dict[str, Any],
    mutation: str,
    expected_code: str,
) -> None:
    values = copy.deepcopy(behavior_payloads)
    package = values["package"]
    model = package["processModels"][0]
    node = model["nodes"][1]
    if mutation == "scenario_mismatch":
        package["sourceScenarioId"] = "different"
    elif mutation == "catalog_mismatch":
        package["catalogs"]["activityCatalog"]["version"] = "wrong"
    elif mutation == "duplicate_activity":
        values["activities"]["activities"].append(values["activities"]["activities"][0])
    elif mutation == "duplicate_component":
        values["activities"]["components"].append(values["activities"]["components"][0])
    elif mutation == "unknown_activity_component":
        values["activities"]["activities"][0]["components"] = ["missing"]
    elif mutation == "unknown_component_action":
        values["activities"]["components"][0]["requiredActionTypes"][0] = "invented"
    elif mutation == "unknown_activity_variable":
        values["activities"]["activities"][0]["relevantVariableIds"][0] = "missing"
    elif mutation == "duplicate_variable":
        values["variables"]["variables"].append(values["variables"]["variables"][0])
    elif mutation == "duplicate_action":
        values["actions"]["actions"].append(values["actions"]["actions"][0])
    elif mutation == "duplicate_parameter":
        values["actions"]["actions"][0]["parameters"].append(
            values["actions"]["actions"][0]["parameters"][0]
        )
    elif mutation == "duplicate_model":
        package["processModels"].append(package["processModels"][0])
    elif mutation == "unknown_model_resident":
        model["residentId"] = "missing"
    elif mutation == "duplicate_node":
        model["nodes"].append(model["nodes"][1])
    elif mutation == "duplicate_edge":
        model["edges"].append(model["edges"][0])
    elif mutation == "unknown_edge_node":
        model["edges"][0]["targetNodeId"] = "missing"
    elif mutation == "missing_start":
        model["nodes"][0]["kind"] = "end"
    elif mutation == "missing_end":
        model["nodes"][-1]["kind"] = "action"
        model["nodes"][-1]["actionType"] = "leave_home"
        model["nodes"][-1]["durationWeight"] = 1
    elif mutation == "invalid_degree":
        model["edges"].append({"sourceNodeId": "start", "targetNodeId": "step_1"})
    elif mutation == "invalid_choice":
        node["kind"] = "choice"
        node.pop("actionType")
        node.pop("arguments")
        node.pop("durationWeight")
    elif mutation == "dead_node":
        model["nodes"].append(
            {
                "nodeId": "dead",
                "kind": "action",
                "actionType": "leave_home",
                "durationWeight": 1,
            }
        )
    elif mutation == "unbounded_cycle":
        model["edges"].append({"sourceNodeId": "step_3", "targetNodeId": "step_1"})
    elif mutation == "unknown_action":
        node["actionType"] = "invented"
    elif mutation == "invalid_arguments":
        node["arguments"] = {"unknown": {"source": "literal", "value": "x"}}
    elif mutation == "literal_type":
        node["arguments"]["targetRole"] = {"source": "literal", "value": 1}
    elif mutation == "literal_allowed":
        node["actionType"] = "change_posture"
        node["arguments"] = {"posture": {"source": "literal", "value": "floating"}}
    elif mutation == "literal_reference":
        node["actionType"] = "move_to"
        node["arguments"] = {
            "destination": {
                "source": "literal",
                "value": "missing_location",
            }
        }
    elif mutation == "unknown_variable":
        node["preconditions"] = [{"variableId": "missing"}]
    elif mutation == "invalid_variable_value":
        node["preconditions"] = [{"variableId": "resident.age", "operator": "eq", "value": "old"}]
    elif mutation == "required_variable_missing":
        values["variables"]["variables"][0]["required"] = True
    elif mutation == "variable_source_type":
        values["scenario"]["initialState"]["residents"][0]["facts"]["fatigue"] = "high"
    elif mutation == "variable_source_value":
        day_type = next(
            item for item in values["variables"]["variables"] if item["variableId"] == "day.type"
        )
        day_type["allowedValues"] = ["weekend"]
    elif mutation == "duplicate_binding":
        package["bindings"].append(package["bindings"][0])
    elif mutation == "unknown_binding_resident":
        package["bindings"][0]["residentId"] = "missing"
    elif mutation == "unknown_intent":
        package["bindings"][0]["intent"] = "missing"
    elif mutation == "unknown_model":
        package["bindings"][0]["processModelId"] = "missing"
    elif mutation == "resident_mismatch":
        package["processModels"][0]["residentId"] = "resident_2"
        values["scenario"]["residents"].append({"residentId": "resident_2", "profile": {}})
        values["scenario"]["initialState"]["residents"].append(
            {"residentId": "resident_2", "locationId": "bedroom"}
        )
    elif mutation == "component_mismatch":
        model["implementedComponents"] = ["opaque_activity"]
    elif mutation == "component_action_missing":
        clean = next(item for item in model["nodes"] if item.get("actionType") == "clean")
        clean["actionType"] = "inspect"
    elif mutation == "movement_missing":
        node["actionType"] = "leave_home"
        node["arguments"] = {}
    elif mutation == "missing_binding":
        package["bindings"] = package["bindings"][1:]
    elif mutation == "ambiguous_binding":
        duplicate = copy.deepcopy(package["bindings"][0])
        duplicate["bindingId"] = "also_applicable"
        duplicate["fallback"] = False
        package["bindings"][0]["fallback"] = False
        package["bindings"].append(duplicate)
    else:  # pragma: no cover
        raise AssertionError(mutation)

    report = validate(values)
    assert not report.valid
    assert expected_code in {item.code for item in report.issues}


def test_applicability_prefers_matching_specific_binding(
    behavior_payloads: dict[str, Any],
) -> None:
    values = copy.deepcopy(behavior_payloads)
    package = values["package"]
    specific = copy.deepcopy(package["bindings"][0])
    specific["bindingId"] = "working_day_breakfast"
    specific["fallback"] = False
    specific["applicability"] = [
        {"variableId": "day.type", "operator": "eq", "value": "working_day"},
        {"variableId": "calendar.season", "operator": "eq", "value": "autumn"},
        {"variableId": "calendar.weekday", "operator": "eq", "value": 0},
    ]
    package["bindings"].append(specific)

    assert validate(values).valid


def test_nonmatching_specific_binding_uses_fallback(
    behavior_payloads: dict[str, Any],
) -> None:
    values = copy.deepcopy(behavior_payloads)
    specific = copy.deepcopy(values["package"]["bindings"][0])
    specific["bindingId"] = "weekend_only"
    specific["fallback"] = False
    specific["applicability"] = [{"variableId": "day.type", "operator": "eq", "value": "weekend"}]
    values["package"]["bindings"].append(specific)

    assert validate(values).valid


def test_complex_control_flow_is_valid(behavior_payloads: dict[str, Any]) -> None:
    values = copy.deepcopy(behavior_payloads)
    model = values["package"]["processModels"][0]

    def action(
        node_id: str,
        action_type: str = "leave_home",
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "nodeId": node_id,
            "kind": "action",
            "actionType": action_type,
            **({"arguments": arguments} if arguments is not None else {}),
            "durationWeight": 1,
        }

    model["nodes"] = [
        {"nodeId": "start", "kind": "start"},
        action(
            "move",
            "move_to",
            {"destination": {"source": "activity_location", "index": 0}},
        ),
        action("take", "take_item", {"itemRole": {"source": "literal", "value": "tool"}}),
        action(
            "clean",
            "clean",
            {"targetRole": {"source": "literal", "value": "surface"}},
        ),
        action("put", "put_item", {"itemRole": {"source": "literal", "value": "tool"}}),
        {"nodeId": "choice", "kind": "choice"},
        action("choice_left"),
        action("choice_default"),
        {"nodeId": "split", "kind": "parallel_split"},
        action("left"),
        action("right"),
        {"nodeId": "join", "kind": "parallel_join"},
        {"nodeId": "loop", "kind": "loop", "maxIterations": 2},
        action("body"),
        {"nodeId": "end", "kind": "end"},
    ]
    model["edges"] = [
        {"sourceNodeId": "start", "targetNodeId": "move"},
        {"sourceNodeId": "move", "targetNodeId": "take"},
        {"sourceNodeId": "take", "targetNodeId": "clean"},
        {"sourceNodeId": "clean", "targetNodeId": "put"},
        {"sourceNodeId": "put", "targetNodeId": "choice"},
        {
            "sourceNodeId": "choice",
            "targetNodeId": "choice_left",
            "condition": {"variableId": "day.type", "operator": "eq", "value": "working_day"},
        },
        {"sourceNodeId": "choice", "targetNodeId": "choice_default", "isDefault": True},
        {"sourceNodeId": "choice_left", "targetNodeId": "split"},
        {"sourceNodeId": "choice_default", "targetNodeId": "split"},
        {"sourceNodeId": "split", "targetNodeId": "left"},
        {"sourceNodeId": "split", "targetNodeId": "right"},
        {"sourceNodeId": "left", "targetNodeId": "join"},
        {"sourceNodeId": "right", "targetNodeId": "join"},
        {"sourceNodeId": "join", "targetNodeId": "loop"},
        {
            "sourceNodeId": "loop",
            "targetNodeId": "body",
            "condition": {"variableId": "day.type", "operator": "eq", "value": "working_day"},
        },
        {"sourceNodeId": "loop", "targetNodeId": "end", "isDefault": True},
        {"sourceNodeId": "body", "targetNodeId": "loop"},
    ]

    assert validate(values).valid


def test_parallel_split_requires_a_common_join(behavior_payloads: dict[str, Any]) -> None:
    values = copy.deepcopy(behavior_payloads)
    model = values["package"]["processModels"][0]
    model["nodes"] = [
        {"nodeId": "start", "kind": "start"},
        {"nodeId": "split", "kind": "parallel_split"},
        {
            "nodeId": "left",
            "kind": "action",
            "actionType": "leave_home",
            "durationWeight": 1,
        },
        {
            "nodeId": "right",
            "kind": "action",
            "actionType": "leave_home",
            "durationWeight": 1,
        },
        {"nodeId": "end", "kind": "end"},
    ]
    model["edges"] = [
        {"sourceNodeId": "start", "targetNodeId": "split"},
        {"sourceNodeId": "split", "targetNodeId": "left"},
        {"sourceNodeId": "split", "targetNodeId": "right"},
        {"sourceNodeId": "left", "targetNodeId": "end"},
        {"sourceNodeId": "right", "targetNodeId": "end"},
    ]

    assert "PARALLEL_JOIN_MISSING" in {item.code for item in validate(values).issues}


def test_loop_requires_conditioned_repeat_and_default_exit(
    behavior_payloads: dict[str, Any],
) -> None:
    values = copy.deepcopy(behavior_payloads)
    model = values["package"]["processModels"][0]
    model["nodes"] = [
        {"nodeId": "start", "kind": "start"},
        {
            "nodeId": "body",
            "kind": "action",
            "actionType": "leave_home",
            "durationWeight": 1,
        },
        {"nodeId": "loop", "kind": "loop", "maxIterations": 2},
        {"nodeId": "end", "kind": "end"},
    ]
    model["edges"] = [
        {"sourceNodeId": "start", "targetNodeId": "body"},
        {"sourceNodeId": "body", "targetNodeId": "loop"},
        {
            "sourceNodeId": "loop",
            "targetNodeId": "body",
            "condition": {"variableId": "resident.fatigue", "operator": "lt", "value": 0.8},
        },
        {"sourceNodeId": "loop", "targetNodeId": "end"},
    ]

    assert "LOOP_BRANCH_INVALID" in {item.code for item in validate(values).issues}


def test_acceptance_models_preserve_compound_intent_semantics() -> None:
    package = json.loads(
        (ROOT / "examples/behavior/mario_rossi_week_2026_10_12.behavior.json").read_text()
    )
    catalog = json.loads(
        (ROOT / "src/smart_home_sim/catalogs/activity-catalog-1.0.0.json").read_text()
    )
    models = {item["processModelId"]: item for item in package["processModels"]}
    components = {item["intent"]: item["components"] for item in catalog["activities"]}

    for binding in package["bindings"]:
        assert (
            models[binding["processModelId"]]["implementedComponents"]
            == components[binding["intent"]]
        )

    def actions(intent: str) -> set[str]:
        model = models[f"resident_mario_rossi__{intent}"]
        return {node["actionType"] for node in model["nodes"] if node["kind"] == "action"}

    assert {"prepare_food", "consume"} <= actions("prepare_and_eat_breakfast")
    assert {"dress", "consume"} <= actions("change_clothes_and_eat_snack")
    assert {"travel_to", "enter_home", "put_item"} <= actions("return_home_and_store_purchases")
    assert any(
        node["kind"] == "parallel_split"
        for node in models["resident_mario_rossi__eat_breakfast_and_listen_to_radio"]["nodes"]
    )
    assert any(
        node["kind"] == "choice" for node in models["resident_mario_rossi__rest_or_nap"]["nodes"]
    )
    assert any(
        node["kind"] == "loop" for node in models["resident_mario_rossi__work_shift"]["nodes"]
    )


def test_expression_validation_variable_and_reference_kinds(
    behavior_payloads: dict[str, Any],
) -> None:
    cases = [
        ({"source": "variable", "variableId": "missing"}, "UNKNOWN_VARIABLE"),
        (
            {"source": "variable", "variableId": "resident.age"},
            "ACTION_ARGUMENT_TYPE_MISMATCH",
        ),
        ({"source": "actor"}, "ACTION_ARGUMENT_TYPE_MISMATCH"),
    ]
    for expression, expected in cases:
        values = copy.deepcopy(behavior_payloads)
        node = values["package"]["processModels"][0]["nodes"][1]
        node["actionType"] = "move_to"
        node["arguments"] = {"destination": expression}
        assert expected in {item.code for item in validate(values).issues}


def test_condition_allowed_values_are_checked(behavior_payloads: dict[str, Any]) -> None:
    values = copy.deepcopy(behavior_payloads)
    values["package"]["bindings"][0]["applicability"] = [
        {"variableId": "calendar.season", "operator": "eq", "value": "monsoon"}
    ]

    assert "INVALID_VARIABLE_VALUE" in {item.code for item in validate(values).issues}


def test_value_type_helpers_cover_all_catalog_types() -> None:
    from smart_home_sim.domain.behavior import ValueType

    assert service._value_matches(True, ValueType.boolean)
    assert service._value_matches(1, ValueType.integer)
    assert service._value_matches(1.5, ValueType.number)
    assert service._value_matches({}, ValueType.object)
    assert service._value_matches([], ValueType.array)
    assert service._types_compatible(ValueType.integer, ValueType.number)


def test_behavior_issue_rejects_unregistered_code() -> None:
    with pytest.raises(ValueError):
        behavior_issue("NOT_REGISTERED", "structure", "$", "invalid")


@pytest.mark.parametrize(
    ("operator", "actual", "value", "expected"),
    [
        ("exists", 1, None, True),
        ("not_exists", None, None, True),
        ("truthy", 1, None, True),
        ("falsy", 0, None, True),
        ("eq", 2, 2, True),
        ("ne", 2, 3, True),
        ("gt", 3, 2, True),
        ("gte", 2, 2, True),
        ("lt", 1, 2, True),
        ("lte", 2, 2, True),
        ("in", "a", ["a", "b"], True),
        ("not_in", "c", ["a", "b"], True),
        ("gt", "high", 2, False),
    ],
)
def test_condition_operators(
    operator: str,
    actual: Any,
    value: Any,
    expected: bool,
) -> None:
    condition = VariableCondition.model_validate_json(
        json.dumps(
            {
                "variableId": "test",
                "operator": operator,
                **({"value": value} if value is not None else {}),
            }
        )
    )
    present = actual is not None
    assert service._condition_matches(condition, present, actual) is expected


def test_variable_resolution_covers_all_scopes(behavior_payloads: dict[str, Any]) -> None:
    scenario = Scenario.model_validate_json(json.dumps(behavior_payloads["scenario"]))
    catalog = VariableCatalog.model_validate_json(json.dumps(behavior_payloads["variables"]))
    definitions = {item.variable_id: item for item in catalog.variables}
    day = scenario.days[0]

    assert service._resolve_variable(definitions["day.type"], scenario, day, "resident_1") == (
        True,
        "working_day",
    )
    assert service._resolve_variable(
        definitions["calendar.weekday"], scenario, day, "resident_1"
    ) == (True, 0)
    assert service._resolve_variable(
        definitions["calendar.season"], scenario, day, "resident_1"
    ) == (True, "autumn")
    assert service._resolve_variable(
        definitions["resident.fatigue"], scenario, day, "resident_1"
    ) == (False, None)
    assert service._resolve_variable(definitions["resident.age"], scenario, day, "resident_1") == (
        False,
        None,
    )


def test_public_models_round_trip(behavior_payloads: dict[str, Any]) -> None:
    package = PersonalProcessPackage.model_validate_json(json.dumps(behavior_payloads["package"]))
    catalog = ActivityCatalog.model_validate_json(json.dumps(behavior_payloads["activities"]))
    actions = ActionCatalog.model_validate_json(json.dumps(behavior_payloads["actions"]))

    assert package.model_dump(by_alias=True)["documentType"] == "personal_process_package"
    assert len(catalog.activities) > 90
    assert all(activity.components for activity in catalog.activities)
    assert all(activity.relevant_variable_ids for activity in catalog.activities)
    assert all(
        {"requiredCapabilities", "preconditions", "effects"}
        <= action.model_dump(by_alias=True).keys()
        for action in actions.actions
    )
