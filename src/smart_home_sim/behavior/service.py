from __future__ import annotations

import json
from collections import defaultdict
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smart_home_sim.behavior.issues import behavior_issue
from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    ActionDefinition,
    ActionParameterDefinition,
    ActivityCatalog,
    PersonalProcessPackage,
    ProcessBinding,
    ProcessModel,
    ProcessNodeKind,
    ReferenceKind,
    ValueExpression,
    ValueSource,
    ValueType,
    VariableCatalog,
    VariableCondition,
    VariableDefinition,
    VariableScope,
)
from smart_home_sim.domain.behavior_report import (
    BehaviorValidationIssue,
    BehaviorValidationReport,
)
from smart_home_sim.domain.models import ConditionOperator, DayPlan, Scenario
from smart_home_sim.validation.service import (
    MAX_JSON_NESTING,
    MAX_SCENARIO_BYTES,
    DuplicateJsonKeyError,
    InvalidJsonConstantError,
    _exceeds_json_nesting_limit,
    _json_path,
    _reject_duplicate_keys,
    _reject_non_finite_constant,
    validate_file,
    validate_payload,
)

SUPPORTED_BEHAVIOR_VERSION = "1.0.0"


def _default_catalog_path(filename: str) -> Path:
    return Path(str(files("smart_home_sim.catalogs").joinpath(filename)))


def default_activity_catalog_path(version: str = "1.0.0") -> Path:
    if version not in {"1.0.0", "1.1.0"}:
        raise ValueError(f"unsupported built-in activity catalog version: {version}")
    return _default_catalog_path(f"activity-catalog-{version}.json")


def default_variable_catalog_path() -> Path:
    return _default_catalog_path("variable-catalog-1.0.0.json")


def default_action_catalog_path(version: str = "1.0.0") -> Path:
    if version not in {"1.0.0", "1.1.0"}:
        raise ValueError(f"unsupported built-in action catalog version: {version}")
    return _default_catalog_path(f"action-catalog-{version}.json")


def _read_json(path: Path, artifact_name: str) -> tuple[Any | None, BehaviorValidationIssue | None]:
    try:
        encoded = path.read_bytes()
    except FileNotFoundError:
        return None, behavior_issue(
            "FILE_NOT_FOUND",
            "structure",
            "$",
            f"{artifact_name} file not found: {path}",
            details={"artifact": artifact_name},
        )
    except OSError as error:
        return None, behavior_issue(
            "FILE_READ_ERROR",
            "structure",
            "$",
            f"Cannot read {artifact_name}: {error}",
            details={"artifact": artifact_name},
        )
    if len(encoded) > MAX_SCENARIO_BYTES:
        return None, behavior_issue(
            "FILE_TOO_LARGE",
            "structure",
            "$",
            f"{artifact_name} exceeds the {MAX_SCENARIO_BYTES}-byte input limit.",
            details={"artifact": artifact_name, "sizeBytes": len(encoded)},
        )
    try:
        raw = encoded.decode("utf-8")
    except UnicodeDecodeError as error:
        return None, behavior_issue(
            "FILE_ENCODING_ERROR",
            "structure",
            "$",
            f"{artifact_name} is not valid UTF-8.",
            details={"artifact": artifact_name, "byteOffset": error.start},
        )
    if _exceeds_json_nesting_limit(raw):
        return None, behavior_issue(
            "JSON_NESTING_TOO_DEEP",
            "structure",
            "$",
            f"{artifact_name} exceeds the limit of {MAX_JSON_NESTING} nesting levels.",
            details={"artifact": artifact_name},
        )
    try:
        return (
            json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite_constant,
            ),
            None,
        )
    except DuplicateJsonKeyError as error:
        message = f"{artifact_name} repeats JSON key '{error.key}'."
    except InvalidJsonConstantError as error:
        message = f"{artifact_name} contains non-finite number '{error.value}'."
    except (json.JSONDecodeError, RecursionError) as error:
        message = f"Invalid JSON in {artifact_name}: {error}"
    return None, behavior_issue(
        "JSON_SYNTAX",
        "structure",
        "$",
        message,
        details={"artifact": artifact_name},
    )


def _parse_model[ModelT: ContractModel](
    payload: Any,
    model: type[ModelT],
    artifact_name: str,
) -> tuple[ModelT | None, list[BehaviorValidationIssue]]:
    if not isinstance(payload, dict):
        return None, [
            behavior_issue(
                "STRUCTURE_INVALID",
                "structure",
                "$",
                f"{artifact_name} must be a JSON object.",
                details={"artifact": artifact_name},
            )
        ]
    if payload.get("schemaVersion") != SUPPORTED_BEHAVIOR_VERSION:
        return None, [
            behavior_issue(
                "UNSUPPORTED_SCHEMA_VERSION",
                "structure",
                "$.schemaVersion",
                f"Expected schemaVersion '{SUPPORTED_BEHAVIOR_VERSION}' for {artifact_name}.",
                details={"artifact": artifact_name},
            )
        ]
    try:
        parsed = model.model_validate_json(json.dumps(payload, separators=(",", ":")))
    except ValidationError as error:
        return None, [
            behavior_issue(
                "STRUCTURE_INVALID",
                "structure",
                _json_path(item["loc"]),
                item["msg"],
                details={"artifact": artifact_name, "type": item["type"]},
            )
            for item in error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
        ]
    return parsed, []


def validate_behavior_files(
    package_path: Path,
    scenario_path: Path,
    *,
    activity_catalog_path: Path | None = None,
    variable_catalog_path: Path | None = None,
    action_catalog_path: Path | None = None,
) -> BehaviorValidationReport:
    scenario_report = validate_file(scenario_path)
    if not scenario_report.valid:
        return BehaviorValidationReport.from_issues(
            [
                behavior_issue(
                    "INPUT_SCENARIO_INVALID",
                    "compatibility",
                    "$",
                    "The source scenario is invalid.",
                    details={"scenarioErrorCount": scenario_report.summary.error_count},
                )
            ],
            scenario_id=scenario_report.scenario_id,
        )
    scenario_payload, scenario_error = _read_json(scenario_path, "scenario")
    assert scenario_error is None
    scenario = Scenario.model_validate_json(json.dumps(scenario_payload, separators=(",", ":")))

    package_preview: Any = None
    if action_catalog_path is None or activity_catalog_path is None:
        package_preview, _ = _read_json(package_path, "personal process package")
    if action_catalog_path is None:
        catalog_version = "1.0.0"
        if isinstance(package_preview, dict):
            catalogs = package_preview.get("catalogs")
            if isinstance(catalogs, dict):
                action_reference = catalogs.get("actionCatalog")
                if isinstance(action_reference, dict):
                    catalog_version = str(action_reference.get("version", "1.0.0"))
        try:
            action_catalog_path = default_action_catalog_path(catalog_version)
        except ValueError:
            action_catalog_path = _default_catalog_path(f"action-catalog-{catalog_version}.json")
    if activity_catalog_path is None:
        activity_catalog_version = "1.0.0"
        if isinstance(package_preview, dict):
            catalogs = package_preview.get("catalogs")
            if isinstance(catalogs, dict):
                activity_reference = catalogs.get("activityCatalog")
                if isinstance(activity_reference, dict):
                    activity_catalog_version = str(activity_reference.get("version", "1.0.0"))
        try:
            activity_catalog_path = default_activity_catalog_path(activity_catalog_version)
        except ValueError:
            activity_catalog_path = _default_catalog_path(
                f"activity-catalog-{activity_catalog_version}.json"
            )

    paths = (
        (package_path, "personal process package", PersonalProcessPackage),
        (
            activity_catalog_path,
            "activity catalog",
            ActivityCatalog,
        ),
        (
            variable_catalog_path or default_variable_catalog_path(),
            "variable catalog",
            VariableCatalog,
        ),
        (
            action_catalog_path,
            "action catalog",
            ActionCatalog,
        ),
    )
    parsed: list[ContractModel] = []
    issues: list[BehaviorValidationIssue] = []
    package_payload: Any = None
    for path, artifact_name, model in paths:
        payload, read_issue = _read_json(path, artifact_name)
        if read_issue is not None:
            issues.append(read_issue)
            continue
        value, parse_issues = _parse_model(payload, model, artifact_name)
        issues.extend(parse_issues)
        if value is not None:
            parsed.append(value)
        if model is PersonalProcessPackage:
            package_payload = payload
    if issues:
        package_id = (
            str(package_payload.get("packageId"))
            if isinstance(package_payload, dict) and package_payload.get("packageId")
            else None
        )
        return BehaviorValidationReport.from_issues(
            sorted(issues, key=_issue_sort_key),
            package_id=package_id,
            scenario_id=scenario.scenario_id,
        )
    package, activity_catalog, variable_catalog, action_catalog = parsed
    assert isinstance(package, PersonalProcessPackage)
    assert isinstance(activity_catalog, ActivityCatalog)
    assert isinstance(variable_catalog, VariableCatalog)
    assert isinstance(action_catalog, ActionCatalog)
    return validate_behavior(
        package,
        scenario,
        activity_catalog,
        variable_catalog,
        action_catalog,
    )


def validate_behavior_payloads(
    package_payload: Any,
    scenario_payload: Any,
    activity_catalog_payload: Any,
    variable_catalog_payload: Any,
    action_catalog_payload: Any,
) -> BehaviorValidationReport:
    scenario_report = validate_payload(scenario_payload)
    if not scenario_report.valid:
        return BehaviorValidationReport.from_issues(
            [
                behavior_issue(
                    "INPUT_SCENARIO_INVALID",
                    "compatibility",
                    "$",
                    "The source scenario is invalid.",
                )
            ],
            scenario_id=scenario_report.scenario_id,
        )
    inputs: tuple[tuple[Any, type[ContractModel], str], ...] = (
        (package_payload, PersonalProcessPackage, "personal process package"),
        (activity_catalog_payload, ActivityCatalog, "activity catalog"),
        (variable_catalog_payload, VariableCatalog, "variable catalog"),
        (action_catalog_payload, ActionCatalog, "action catalog"),
    )
    values: list[ContractModel] = []
    issues: list[BehaviorValidationIssue] = []
    for payload, model, artifact_name in inputs:
        value, parse_issues = _parse_model(payload, model, artifact_name)
        issues.extend(parse_issues)
        if value is not None:
            values.append(value)
    if issues:
        return BehaviorValidationReport.from_issues(sorted(issues, key=_issue_sort_key))
    package, activity_catalog, variable_catalog, action_catalog = values
    return validate_behavior(
        package,  # type: ignore[arg-type]
        Scenario.model_validate_json(json.dumps(scenario_payload, separators=(",", ":"))),
        activity_catalog,  # type: ignore[arg-type]
        variable_catalog,  # type: ignore[arg-type]
        action_catalog,  # type: ignore[arg-type]
    )


def _issue_sort_key(item: BehaviorValidationIssue) -> tuple[str, str, str]:
    return item.path, item.code, item.message


def validate_behavior(
    package: PersonalProcessPackage,
    scenario: Scenario,
    activity_catalog: ActivityCatalog,
    variable_catalog: VariableCatalog,
    action_catalog: ActionCatalog,
) -> BehaviorValidationReport:
    issues: list[BehaviorValidationIssue] = []
    issues.extend(_validate_catalogs(activity_catalog, variable_catalog, action_catalog))
    issues.extend(
        _validate_package_references(
            package,
            scenario,
            activity_catalog,
            variable_catalog,
            action_catalog,
        )
    )
    issues.extend(_validate_variable_sources(scenario, variable_catalog))
    variables = {item.variable_id: item for item in variable_catalog.variables}
    actions = {item.action_type: item for item in action_catalog.actions}
    issues.extend(_validate_models(package, scenario, variables, actions))
    binding_issues, covered_count = _validate_bindings(
        package,
        scenario,
        {item.intent: item.components for item in activity_catalog.activities},
        {item.component_id: item.required_action_types for item in activity_catalog.components},
        variables,
    )
    issues.extend(binding_issues)
    package_digest = sha256(
        json.dumps(
            package.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return BehaviorValidationReport.from_issues(
        sorted(issues, key=_issue_sort_key),
        package_version=package.package_version,
        package_id=package.package_id,
        scenario_id=scenario.scenario_id,
        package_sha256=package_digest,
        process_model_count=len(package.process_models),
        binding_count=len(package.bindings),
        covered_activity_count=covered_count,
    )


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _validate_catalogs(
    activity_catalog: ActivityCatalog,
    variable_catalog: VariableCatalog,
    action_catalog: ActionCatalog,
) -> list[BehaviorValidationIssue]:
    issues: list[BehaviorValidationIssue] = []
    collections = (
        (
            "activity component",
            [item.component_id for item in activity_catalog.components],
            "$.components",
        ),
        ("activity", [item.intent for item in activity_catalog.activities], "$.activities"),
        ("variable", [item.variable_id for item in variable_catalog.variables], "$.variables"),
        ("action", [item.action_type for item in action_catalog.actions], "$.actions"),
    )
    for kind, values, path in collections:
        for duplicate in sorted(_duplicates(values)):
            issues.append(
                behavior_issue(
                    "DUPLICATE_CATALOG_ENTRY",
                    "catalog",
                    path,
                    f"Duplicate {kind} catalog identifier '{duplicate}'.",
                    details={"identifier": duplicate},
                )
            )
    for action_index, action in enumerate(action_catalog.actions):
        for duplicate in sorted(_duplicates([item.parameter_name for item in action.parameters])):
            issues.append(
                behavior_issue(
                    "DUPLICATE_ACTION_PARAMETER",
                    "catalog",
                    f"$.actions[{action_index}].parameters",
                    f"Action '{action.action_type}' repeats parameter '{duplicate}'.",
                )
            )
    component_ids = {item.component_id for item in activity_catalog.components}
    action_types = {item.action_type for item in action_catalog.actions}
    variable_ids = {item.variable_id for item in variable_catalog.variables}
    for activity_index, activity in enumerate(activity_catalog.activities):
        for component in activity.components:
            if component not in component_ids:
                issues.append(
                    behavior_issue(
                        "UNKNOWN_ACTIVITY_COMPONENT",
                        "catalog",
                        f"$.activities[{activity_index}].components",
                        f"Activity '{activity.intent}' references unknown component '{component}'.",
                    )
                )
        for variable_id in activity.relevant_variable_ids:
            if variable_id not in variable_ids:
                issues.append(
                    behavior_issue(
                        "UNKNOWN_VARIABLE",
                        "catalog",
                        f"$.activities[{activity_index}].relevantVariableIds",
                        f"Activity '{activity.intent}' references unknown variable "
                        f"'{variable_id}'.",
                    )
                )
    for component_index, component in enumerate(activity_catalog.components):
        for action_type in component.required_action_types:
            if action_type not in action_types:
                issues.append(
                    behavior_issue(
                        "UNKNOWN_ACTION_TYPE",
                        "catalog",
                        f"$.components[{component_index}].requiredActionTypes",
                        f"Component '{component.component_id}' requires unknown action "
                        f"'{action_type}'.",
                    )
                )
    return issues


def _validate_package_references(
    package: PersonalProcessPackage,
    scenario: Scenario,
    activity_catalog: ActivityCatalog,
    variable_catalog: VariableCatalog,
    action_catalog: ActionCatalog,
) -> list[BehaviorValidationIssue]:
    issues: list[BehaviorValidationIssue] = []
    if (
        package.source_scenario_id != scenario.scenario_id
        or package.source_scenario_version != scenario.schema_version
    ):
        issues.append(
            behavior_issue(
                "PACKAGE_SCENARIO_MISMATCH",
                "compatibility",
                "$.sourceScenarioId",
                "The process package targets a different scenario identity or version.",
            )
        )
    references = (
        ("activityCatalog", package.catalogs.activity_catalog, activity_catalog),
        ("variableCatalog", package.catalogs.variable_catalog, variable_catalog),
        ("actionCatalog", package.catalogs.action_catalog, action_catalog),
    )
    for field_name, reference, catalog in references:
        if (
            reference.catalog_id != catalog.catalog_id
            or reference.version != catalog.catalog_version
        ):
            issues.append(
                behavior_issue(
                    "CATALOG_REFERENCE_MISMATCH",
                    "catalog",
                    f"$.catalogs.{field_name}",
                    f"Package reference for {field_name} does not match the loaded catalog.",
                )
            )
    return issues


def _validate_models(
    package: PersonalProcessPackage,
    scenario: Scenario,
    variables: dict[str, VariableDefinition],
    actions: dict[str, ActionDefinition],
) -> list[BehaviorValidationIssue]:
    issues: list[BehaviorValidationIssue] = []
    residents = {item.resident_id for item in scenario.residents}
    model_ids = [item.process_model_id for item in package.process_models]
    for duplicate in sorted(_duplicates(model_ids)):
        issues.append(
            behavior_issue(
                "DUPLICATE_PROCESS_MODEL_ID",
                "graph",
                "$.processModels",
                f"Duplicate processModelId '{duplicate}'.",
            )
        )
    for model_index, model in enumerate(package.process_models):
        model_path = f"$.processModels[{model_index}]"
        if model.resident_id not in residents:
            issues.append(
                behavior_issue(
                    "UNKNOWN_RESIDENT",
                    "compatibility",
                    f"{model_path}.residentId",
                    f"Unknown resident '{model.resident_id}'.",
                )
            )
        issues.extend(_validate_graph(model, model_path, variables, actions, scenario))
    return issues


def _validate_variable_sources(
    scenario: Scenario,
    variable_catalog: VariableCatalog,
) -> list[BehaviorValidationIssue]:
    issues: list[BehaviorValidationIssue] = []
    for definition in variable_catalog.variables:
        if definition.scope in {VariableScope.day, VariableScope.derived_calendar}:
            contexts = [
                (day_index, day, scenario.residents[0].resident_id)
                for day_index, day in enumerate(scenario.days)
            ]
        else:
            contexts = [
                (0, scenario.days[0], resident.resident_id) for resident in scenario.residents
            ]
        for day_index, day, resident_id in contexts:
            present, value = _resolve_variable(definition, scenario, day, resident_id)
            if not present:
                if definition.required:
                    issues.append(
                        behavior_issue(
                            "REQUIRED_VARIABLE_MISSING",
                            "compatibility",
                            f"$.days[{day_index}]",
                            f"Required variable '{definition.variable_id}' cannot be resolved.",
                            details={"residentId": resident_id},
                        )
                    )
                continue
            if not _value_matches(value, definition.value_type):
                issues.append(
                    behavior_issue(
                        "VARIABLE_SOURCE_TYPE_MISMATCH",
                        "compatibility",
                        f"$.days[{day_index}]",
                        f"Source value for '{definition.variable_id}' has the wrong type.",
                        details={"residentId": resident_id},
                    )
                )
            elif definition.allowed_values and value not in definition.allowed_values:
                issues.append(
                    behavior_issue(
                        "VARIABLE_SOURCE_VALUE_INVALID",
                        "compatibility",
                        f"$.days[{day_index}]",
                        f"Source value for '{definition.variable_id}' is outside its catalog.",
                        details={"residentId": resident_id},
                    )
                )
    return issues


def _validate_graph(
    model: ProcessModel,
    path: str,
    variables: dict[str, VariableDefinition],
    actions: dict[str, ActionDefinition],
    scenario: Scenario,
) -> list[BehaviorValidationIssue]:
    issues: list[BehaviorValidationIssue] = []
    if not any(
        node.kind is ProcessNodeKind.action
        and node.action_type in {"move_to", "move_to_capability", "travel_to"}
        for node in model.nodes
    ):
        issues.append(
            behavior_issue(
                "PROCESS_MOVEMENT_MISSING",
                "graph",
                f"{path}.nodes",
                "A process model must expose movement at the project trace granularity.",
            )
        )
    node_ids = [node.node_id for node in model.nodes]
    for duplicate in sorted(_duplicates(node_ids)):
        issues.append(
            behavior_issue(
                "DUPLICATE_NODE_ID",
                "graph",
                f"{path}.nodes",
                f"Duplicate nodeId '{duplicate}'.",
            )
        )
    edge_keys = [f"{edge.source_node_id}\0{edge.target_node_id}" for edge in model.edges]
    for duplicate in sorted(_duplicates(edge_keys)):
        source, target = duplicate.split("\0")
        issues.append(
            behavior_issue(
                "DUPLICATE_EDGE",
                "graph",
                f"{path}.edges",
                f"Duplicate edge '{source}' -> '{target}'.",
            )
        )
    nodes = {node.node_id: node for node in model.nodes}
    outgoing: dict[str, list[Any]] = defaultdict(list)
    incoming: dict[str, list[Any]] = defaultdict(list)
    for edge_index, edge in enumerate(model.edges):
        if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
            issues.append(
                behavior_issue(
                    "UNKNOWN_EDGE_NODE",
                    "graph",
                    f"{path}.edges[{edge_index}]",
                    "Edge references an unknown process node.",
                )
            )
            continue
        outgoing[edge.source_node_id].append(edge)
        incoming[edge.target_node_id].append(edge)
        if edge.condition is not None:
            issues.extend(
                _validate_condition(
                    edge.condition,
                    f"{path}.edges[{edge_index}].condition",
                    variables,
                )
            )
    starts = [node for node in model.nodes if node.kind is ProcessNodeKind.start]
    ends = [node for node in model.nodes if node.kind is ProcessNodeKind.end]
    if len(starts) != 1:
        issues.append(
            behavior_issue(
                "GRAPH_START_INVALID",
                "graph",
                f"{path}.nodes",
                "A process model requires exactly one start node.",
                details={"startCount": len(starts)},
            )
        )
    if not ends:
        issues.append(
            behavior_issue(
                "GRAPH_END_INVALID",
                "graph",
                f"{path}.nodes",
                "A process model requires at least one end node.",
            )
        )
    for node_index, node in enumerate(model.nodes):
        degree_path = f"{path}.nodes[{node_index}]"
        out_count = len(outgoing[node.node_id])
        in_count = len(incoming[node.node_id])
        invalid = False
        if node.kind is ProcessNodeKind.start:
            invalid = in_count != 0 or out_count != 1
        elif node.kind is ProcessNodeKind.end:
            invalid = in_count < 1 or out_count != 0
        elif node.kind is ProcessNodeKind.choice:
            choice_edges = outgoing[node.node_id]
            defaults = sum(edge.is_default for edge in choice_edges)
            conditioned = sum(edge.condition is not None for edge in choice_edges)
            if out_count < 2 or defaults != 1 or conditioned != out_count - 1:
                issues.append(
                    behavior_issue(
                        "CHOICE_BRANCH_INVALID",
                        "graph",
                        degree_path,
                        "Choice nodes require at least two branches, one default, "
                        "and conditions on all other branches.",
                    )
                )
            invalid = in_count < 1
        elif node.kind is ProcessNodeKind.parallel_split:
            invalid = in_count < 1 or out_count < 2
        elif node.kind is ProcessNodeKind.parallel_join:
            invalid = in_count < 2 or out_count != 1
        elif node.kind is ProcessNodeKind.loop:
            loop_edges = outgoing[node.node_id]
            defaults = sum(edge.is_default for edge in loop_edges)
            conditioned = sum(edge.condition is not None for edge in loop_edges)
            if out_count != 2 or defaults != 1 or conditioned != 1:
                issues.append(
                    behavior_issue(
                        "LOOP_BRANCH_INVALID",
                        "graph",
                        degree_path,
                        "Loop nodes require one conditioned repeat branch and one default exit.",
                    )
                )
            invalid = in_count < 1 or out_count != 2
        else:
            invalid = in_count < 1 or out_count != 1
        if invalid:
            issues.append(
                behavior_issue(
                    "INVALID_GRAPH_DEGREE",
                    "graph",
                    degree_path,
                    f"Node '{node.node_id}' has invalid incoming/outgoing degree "
                    f"for kind '{node.kind}'.",
                    details={"incoming": in_count, "outgoing": out_count},
                )
            )
        if node.kind is ProcessNodeKind.action:
            assert node.action_type is not None
            action = actions.get(node.action_type)
            if action is None:
                issues.append(
                    behavior_issue(
                        "UNKNOWN_ACTION_TYPE",
                        "catalog",
                        f"{degree_path}.actionType",
                        f"Unknown action type '{node.action_type}'.",
                    )
                )
            else:
                issues.extend(
                    _validate_action_arguments(
                        node.arguments,
                        action,
                        degree_path,
                        variables,
                        scenario,
                    )
                )
            for condition_index, condition in enumerate(node.preconditions):
                issues.extend(
                    _validate_condition(
                        condition,
                        f"{degree_path}.preconditions[{condition_index}]",
                        variables,
                    )
                )
    if len(starts) == 1:
        reachable = _reachable(starts[0].node_id, outgoing, forward=True)
        can_reach_end: set[str] = set()
        for end in ends:
            can_reach_end.update(_reachable(end.node_id, incoming, forward=False))
        for node_id in sorted(set(nodes) - (reachable & can_reach_end)):
            issues.append(
                behavior_issue(
                    "GRAPH_NODE_DEAD",
                    "graph",
                    f"{path}.nodes",
                    f"Node '{node_id}' is not on a path from start to an end node.",
                )
            )
        issues.extend(_validate_parallel_joins(model, path, outgoing))
        cycle = _find_unbounded_cycle(starts[0].node_id, nodes, outgoing)
        if cycle:
            issues.append(
                behavior_issue(
                    "GRAPH_CYCLE_UNBOUNDED",
                    "graph",
                    f"{path}.edges",
                    "Every process cycle must pass through a loop node with maxIterations.",
                    details={"cycle": cycle},
                )
            )
    return issues


def _validate_parallel_joins(
    model: ProcessModel,
    path: str,
    outgoing: dict[str, list[Any]],
) -> list[BehaviorValidationIssue]:
    issues: list[BehaviorValidationIssue] = []
    joins = {node.node_id for node in model.nodes if node.kind is ProcessNodeKind.parallel_join}
    for node_index, node in enumerate(model.nodes):
        if node.kind is not ProcessNodeKind.parallel_split:
            continue
        branch_join_sets: list[set[str]] = []
        for edge in outgoing[node.node_id]:
            reachable = _reachable(edge.target_node_id, outgoing, forward=True)
            branch_join_sets.append(reachable & joins)
        common_joins = set.intersection(*branch_join_sets) if branch_join_sets else set()
        if not common_joins:
            issues.append(
                behavior_issue(
                    "PARALLEL_JOIN_MISSING",
                    "graph",
                    f"{path}.nodes[{node_index}]",
                    f"Parallel split '{node.node_id}' has no join reachable from every branch.",
                )
            )
    return issues


def _reachable(start: str, edges: dict[str, list[Any]], *, forward: bool) -> set[str]:
    result: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        for edge in edges[current]:
            pending.append(edge.target_node_id if forward else edge.source_node_id)
    return result


def _find_unbounded_cycle(
    start: str,
    nodes: dict[str, Any],
    outgoing: dict[str, list[Any]],
) -> list[str]:
    reachable = _reachable(start, outgoing, forward=True)
    allowed = {node_id for node_id in reachable if nodes[node_id].kind is not ProcessNodeKind.loop}
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node_id: str) -> list[str]:
        state[node_id] = 1
        stack.append(node_id)
        for edge in outgoing[node_id]:
            target = edge.target_node_id
            if target not in allowed:
                continue
            if state.get(target, 0) == 0:
                found = visit(target)
                if found:
                    return found
            elif state.get(target) == 1:
                return stack[stack.index(target) :]
        stack.pop()
        state[node_id] = 2
        return []

    for node_id in sorted(allowed):
        if state.get(node_id, 0) == 0:
            cycle = visit(node_id)
            if cycle:
                return cycle
    return []


def _validate_condition(
    condition: VariableCondition,
    path: str,
    variables: dict[str, VariableDefinition],
) -> list[BehaviorValidationIssue]:
    definition = variables.get(condition.variable_id)
    if definition is None:
        return [
            behavior_issue(
                "UNKNOWN_VARIABLE",
                "catalog",
                f"{path}.variableId",
                f"Unknown variable '{condition.variable_id}'.",
            )
        ]
    if condition.value is not None and not _value_matches(condition.value, definition.value_type):
        return [
            behavior_issue(
                "INVALID_VARIABLE_VALUE",
                "catalog",
                f"{path}.value",
                f"Condition value does not match variable type '{definition.value_type}'.",
            )
        ]
    if definition.allowed_values and condition.value is not None:
        candidates = condition.value if isinstance(condition.value, list) else [condition.value]
        if any(item not in definition.allowed_values for item in candidates):
            return [
                behavior_issue(
                    "INVALID_VARIABLE_VALUE",
                    "catalog",
                    f"{path}.value",
                    f"Condition uses a value outside the catalog for '{condition.variable_id}'.",
                )
            ]
    return []


def _validate_action_arguments(
    arguments: dict[str, ValueExpression],
    action: ActionDefinition,
    path: str,
    variables: dict[str, VariableDefinition],
    scenario: Scenario,
) -> list[BehaviorValidationIssue]:
    issues: list[BehaviorValidationIssue] = []
    parameters = {item.parameter_name: item for item in action.parameters}
    missing = sorted(
        item.parameter_name
        for item in action.parameters
        if item.required and item.parameter_name not in arguments
    )
    unknown = sorted(set(arguments) - set(parameters))
    if missing or unknown:
        issues.append(
            behavior_issue(
                "INVALID_ACTION_ARGUMENTS",
                "catalog",
                f"{path}.arguments",
                f"Action '{action.action_type}' has missing or unknown arguments.",
                details={"missing": missing, "unknown": unknown},
            )
        )
    for name, expression in arguments.items():
        parameter = parameters.get(name)
        if parameter is None:
            continue
        issues.extend(
            _validate_expression(
                expression,
                parameter,
                f"{path}.arguments.{name}",
                variables,
                scenario,
            )
        )
    return issues


def _validate_expression(
    expression: ValueExpression,
    parameter: ActionParameterDefinition,
    path: str,
    variables: dict[str, VariableDefinition],
    scenario: Scenario,
) -> list[BehaviorValidationIssue]:
    if expression.source is ValueSource.literal:
        if not _value_matches(expression.value, parameter.value_type):
            return [
                behavior_issue(
                    "ACTION_ARGUMENT_TYPE_MISMATCH",
                    "catalog",
                    path,
                    f"Literal argument does not match expected type '{parameter.value_type}'.",
                )
            ]
        if parameter.allowed_values and expression.value not in parameter.allowed_values:
            return [
                behavior_issue(
                    "ACTION_ARGUMENT_TYPE_MISMATCH",
                    "catalog",
                    path,
                    "Literal argument is outside the allowed value set.",
                )
            ]
        references = {
            ReferenceKind.location: {item.location_id for item in scenario.locations},
            ReferenceKind.resource: {item.resource_id for item in scenario.resources},
            ReferenceKind.resident: {item.resident_id for item in scenario.residents},
            ReferenceKind.external_person: {
                item.external_person_id for item in scenario.external_people
            },
        }
        allowed = references.get(parameter.reference_kind)
        if allowed is not None and expression.value not in allowed:
            return [
                behavior_issue(
                    "INVALID_LITERAL_REFERENCE",
                    "compatibility",
                    path,
                    f"Literal does not resolve to a known {parameter.reference_kind}.",
                )
            ]
    elif expression.source is ValueSource.variable:
        assert expression.variable_id is not None
        definition = variables.get(expression.variable_id)
        if definition is None:
            return [
                behavior_issue(
                    "UNKNOWN_VARIABLE",
                    "catalog",
                    path,
                    f"Unknown variable '{expression.variable_id}'.",
                )
            ]
        if not _types_compatible(definition.value_type, parameter.value_type):
            return [
                behavior_issue(
                    "ACTION_ARGUMENT_TYPE_MISMATCH",
                    "catalog",
                    path,
                    "Variable type is incompatible with the action parameter.",
                )
            ]
    else:
        inferred = _expression_type(expression.source)
        if not _types_compatible(inferred, parameter.value_type):
            return [
                behavior_issue(
                    "ACTION_ARGUMENT_TYPE_MISMATCH",
                    "catalog",
                    path,
                    "Expression source is incompatible with the action parameter.",
                )
            ]
        reference_expectations = {
            ValueSource.activity_location: ReferenceKind.location,
            ValueSource.activity_resource: ReferenceKind.resource,
            ValueSource.actor: ReferenceKind.resident,
        }
        expected_reference = reference_expectations.get(expression.source)
        if expected_reference is not None and parameter.reference_kind not in {
            expected_reference,
            ReferenceKind.none,
        }:
            return [
                behavior_issue(
                    "ACTION_ARGUMENT_TYPE_MISMATCH",
                    "catalog",
                    path,
                    "Expression reference kind is incompatible with the action parameter.",
                )
            ]
    return []


def _expression_type(source: ValueSource) -> ValueType:
    if source in {
        ValueSource.activity_location,
        ValueSource.activity_resource,
        ValueSource.activity_intent,
        ValueSource.actor,
    }:
        return ValueType.string
    raise AssertionError(f"Cannot infer static type for {source}")


def _types_compatible(actual: ValueType, expected: ValueType) -> bool:
    return actual is expected or (actual is ValueType.integer and expected is ValueType.number)


def _value_matches(value: Any, value_type: ValueType) -> bool:
    if value_type is ValueType.string:
        return isinstance(value, str)
    if value_type is ValueType.boolean:
        return isinstance(value, bool)
    if value_type is ValueType.integer:
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type is ValueType.number:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type is ValueType.object:
        return isinstance(value, dict)
    return isinstance(value, list)


def _validate_bindings(
    package: PersonalProcessPackage,
    scenario: Scenario,
    intent_components: dict[str, list[str]],
    component_actions: dict[str, list[str]],
    variables: dict[str, VariableDefinition],
) -> tuple[list[BehaviorValidationIssue], int]:
    issues: list[BehaviorValidationIssue] = []
    residents = {item.resident_id for item in scenario.residents}
    models = {item.process_model_id: item for item in package.process_models}
    for duplicate in sorted(_duplicates([item.binding_id for item in package.bindings])):
        issues.append(
            behavior_issue(
                "DUPLICATE_BINDING_ID",
                "compatibility",
                "$.bindings",
                f"Duplicate bindingId '{duplicate}'.",
            )
        )
    for binding_index, binding in enumerate(package.bindings):
        path = f"$.bindings[{binding_index}]"
        if binding.resident_id not in residents:
            issues.append(
                behavior_issue(
                    "UNKNOWN_RESIDENT",
                    "compatibility",
                    f"{path}.residentId",
                    f"Unknown resident '{binding.resident_id}'.",
                )
            )
        if binding.intent not in intent_components:
            issues.append(
                behavior_issue(
                    "UNKNOWN_INTENT",
                    "catalog",
                    f"{path}.intent",
                    f"Unknown activity intent '{binding.intent}'.",
                )
            )
        model = models.get(binding.process_model_id)
        if model is None:
            issues.append(
                behavior_issue(
                    "UNKNOWN_PROCESS_MODEL",
                    "compatibility",
                    f"{path}.processModelId",
                    f"Unknown process model '{binding.process_model_id}'.",
                )
            )
        elif model.resident_id != binding.resident_id:
            issues.append(
                behavior_issue(
                    "PROCESS_MODEL_RESIDENT_MISMATCH",
                    "compatibility",
                    path,
                    "Binding and process model target different residents.",
                )
            )
        elif (
            binding.intent in intent_components
            and model.implemented_components != intent_components[binding.intent]
        ):
            issues.append(
                behavior_issue(
                    "PROCESS_COMPONENT_MISMATCH",
                    "compatibility",
                    f"{path}.processModelId",
                    "The process model does not implement the intent's ordered components.",
                    details={
                        "expected": intent_components[binding.intent],
                        "implemented": model.implemented_components,
                    },
                )
            )
        elif binding.intent in intent_components:
            missing_components = [
                component
                for component in intent_components[binding.intent]
                if not _graph_contains_action_sequence(
                    model,
                    component_actions.get(component, []),
                )
            ]
            if missing_components:
                issues.append(
                    behavior_issue(
                        "PROCESS_COMPONENT_MISMATCH",
                        "compatibility",
                        f"{path}.processModelId",
                        "The process graph omits an ordered action sequence required by "
                        "its components.",
                        details={"missingComponents": missing_components},
                    )
                )
        for condition_index, condition in enumerate(binding.applicability):
            issues.extend(
                _validate_condition(
                    condition,
                    f"{path}.applicability[{condition_index}]",
                    variables,
                )
            )
    covered = 0
    bindings_by_key: dict[tuple[str, str], list[ProcessBinding]] = defaultdict(list)
    for binding in package.bindings:
        bindings_by_key[(binding.resident_id, binding.intent)].append(binding)
    for day_index, day in enumerate(scenario.days):
        for activity_index, activity in enumerate(day.activities):
            activity_path = f"$.days[{day_index}].activities[{activity_index}]"
            candidates = bindings_by_key[(activity.actor_id, activity.intent)]
            applicable = [
                item
                for item in candidates
                if _binding_applies(item, scenario, day, activity.actor_id, variables)
            ]
            primary = [item for item in applicable if not item.fallback]
            selected = primary if primary else [item for item in applicable if item.fallback]
            if not selected:
                issues.append(
                    behavior_issue(
                        "MISSING_PROCESS_BINDING",
                        "compatibility",
                        activity_path,
                        f"No process model applies to '{activity.intent}' "
                        f"for '{activity.actor_id}'.",
                    )
                )
            elif len(selected) > 1:
                issues.append(
                    behavior_issue(
                        "AMBIGUOUS_PROCESS_BINDING",
                        "compatibility",
                        activity_path,
                        f"Multiple process models apply to '{activity.intent}'.",
                        details={"bindingIds": sorted(item.binding_id for item in selected)},
                    )
                )
            else:
                covered += 1
    return issues, covered


def _graph_contains_action_sequence(
    model: ProcessModel,
    required_action_types: list[str],
) -> bool:
    if not required_action_types:
        return False
    nodes = {node.node_id: node for node in model.nodes}
    outgoing: dict[str, list[Any]] = defaultdict(list)
    for edge in model.edges:
        if edge.source_node_id in nodes and edge.target_node_id in nodes:
            outgoing[edge.source_node_id].append(edge)
    frontier = {node.node_id for node in model.nodes if node.kind is ProcessNodeKind.start}
    for action_type in required_action_types:
        matches: set[str] = set()
        for origin in frontier:
            pending = [edge.target_node_id for edge in outgoing[origin]]
            visited: set[str] = set()
            while pending:
                node_id = pending.pop()
                if node_id in visited:
                    continue
                visited.add(node_id)
                node = nodes[node_id]
                if node.kind is ProcessNodeKind.action and node.action_type == action_type:
                    matches.add(node_id)
                pending.extend(edge.target_node_id for edge in outgoing[node_id])
        if not matches:
            return False
        frontier = matches
    return True


def _binding_applies(
    binding: ProcessBinding,
    scenario: Scenario,
    day: DayPlan,
    resident_id: str,
    variables: dict[str, VariableDefinition],
) -> bool:
    for condition in binding.applicability:
        definition = variables.get(condition.variable_id)
        if definition is None:
            return False
        present, actual = _resolve_variable(definition, scenario, day, resident_id)
        if not _condition_matches(condition, present, actual):
            return False
    return True


def _resolve_variable(
    definition: VariableDefinition,
    scenario: Scenario,
    day: DayPlan,
    resident_id: str,
) -> tuple[bool, Any]:
    if definition.scope is VariableScope.derived_calendar:
        if definition.source_path == "weekday":
            return True, day.date.weekday()
        month = day.date.month
        season = (
            "winter"
            if month in {12, 1, 2}
            else "spring"
            if month in {3, 4, 5}
            else "summer"
            if month in {6, 7, 8}
            else "autumn"
        )
        return True, season
    if definition.scope is VariableScope.resident:
        resident = next(item for item in scenario.residents if item.resident_id == resident_id)
        return _lookup_path(resident.profile, definition.source_path or "")
    if definition.scope is VariableScope.day:
        source = day.model_dump(mode="python", by_alias=True)["context"]
        return _lookup_path(source, definition.source_path or "")
    initial = next(
        (item for item in scenario.initial_state.residents if item.resident_id == resident_id),
        None,
    )
    if initial is None:
        return False, None
    return _lookup_path(initial.facts, definition.source_path or "")


def _lookup_path(source: Any, path: str) -> tuple[bool, Any]:
    current = source
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _condition_matches(condition: VariableCondition, present: bool, actual: Any) -> bool:
    operator = condition.operator
    if operator is ConditionOperator.exists:
        return present
    if operator is ConditionOperator.not_exists:
        return not present
    if not present:
        return False
    if operator is ConditionOperator.truthy:
        return bool(actual)
    if operator is ConditionOperator.falsy:
        return not bool(actual)
    if operator is ConditionOperator.eq:
        return actual == condition.value
    if operator is ConditionOperator.ne:
        return actual != condition.value
    try:
        if operator is ConditionOperator.gt:
            return actual > condition.value
        if operator is ConditionOperator.gte:
            return actual >= condition.value
        if operator is ConditionOperator.lt:
            return actual < condition.value
        if operator is ConditionOperator.lte:
            return actual <= condition.value
    except TypeError:
        return False
    if operator is ConditionOperator.in_:
        return actual in condition.value
    return actual not in condition.value
