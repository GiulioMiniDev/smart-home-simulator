from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from pydantic import JsonValue

from smart_home_sim.behavior.service import _binding_applies, _resolve_variable
from smart_home_sim.domain.behavior import (
    ActionCatalog,
    EffectOperation,
    PersonalProcessPackage,
    ProcessModel,
    ProcessNode,
    ProcessNodeKind,
    ValueSource,
    VariableCatalog,
)
from smart_home_sim.domain.models import DayPlan, Scenario
from smart_home_sim.domain.plan import CanonicalActivity, CanonicalPlan

_UNKNOWN = object()
_ABSENT = object()


@dataclass(frozen=True, slots=True)
class PreflightFinding:
    path: str
    message: str
    details: dict[str, JsonValue]


def _default_value(fact: str) -> object:
    if fact.startswith(("entity.", "capability.")):
        return _UNKNOWN
    return _ABSENT


def _fact_value(state: dict[str, object], fact: str) -> object:
    return state.get(fact, _default_value(fact))


def _join(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for fact in left.keys() | right.keys():
        left_value = _fact_value(left, fact)
        right_value = _fact_value(right, fact)
        result[fact] = left_value if left_value == right_value else _UNKNOWN
    return result


def _resolve_arguments(
    node: ProcessNode,
    activity: CanonicalActivity,
    scenario: Scenario,
    day: DayPlan,
    variables: dict[str, Any],
) -> dict[str, JsonValue] | None:
    result: dict[str, JsonValue] = {}
    for name, expression in node.arguments.items():
        if expression.source is ValueSource.literal:
            present, value = True, expression.value
        elif expression.source is ValueSource.activity_location:
            present = expression.index is not None and expression.index < len(activity.location_ids)
            value = activity.location_ids[expression.index] if present else None
        elif expression.source is ValueSource.activity_resource:
            present = (
                expression.index is not None
                and expression.index < len(activity.required_resources)
            )
            value = (
                activity.required_resources[expression.index].resource_id if present else None
            )
        elif expression.source is ValueSource.activity_intent:
            present, value = True, activity.intent
        elif expression.source is ValueSource.actor:
            present, value = True, activity.actor_id
        else:
            definition = variables.get(expression.variable_id or "")
            if definition is None:
                present, value = False, None
            else:
                present, value = _resolve_variable(
                    definition, scenario, day, activity.actor_id
                )
        if not present:
            return None
        result[name] = value
    return result


def _formatted(value: JsonValue, arguments: dict[str, JsonValue]) -> JsonValue:
    if isinstance(value, str):
        return value.format(**{key: str(item) for key, item in arguments.items()})
    return value


def _apply_effect(
    state: dict[str, object], fact: str, operation: EffectOperation, value: JsonValue
) -> dict[str, object]:
    result = dict(state)
    current = _fact_value(result, fact)
    if operation is EffectOperation.set:
        result[fact] = value
    elif operation in {EffectOperation.increment, EffectOperation.decrement}:
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            amount = value if operation is EffectOperation.increment else -value  # type: ignore[operator]
            result[fact] = current + amount
        else:
            result[fact] = _UNKNOWN
    elif operation is EffectOperation.append:
        result[fact] = [*current, value] if isinstance(current, list) else _UNKNOWN
    elif operation is EffectOperation.remove:
        result[fact] = (
            [item for item in current if item != value]
            if isinstance(current, list)
            else _UNKNOWN
        )
    return result


def _transfer(
    state: dict[str, object],
    node: ProcessNode,
    arguments: dict[str, JsonValue],
    action_definitions: dict[str, Any],
) -> dict[str, object]:
    result = dict(state)
    definition = action_definitions[node.action_type or ""]
    string_arguments = {key: str(value) for key, value in arguments.items()}
    for effect in definition.effects:
        fact = effect.fact_template.format(**string_arguments)
        result = _apply_effect(
            result,
            fact,
            effect.operation,
            _formatted(effect.value, arguments),
        )
    for effect in node.effects:
        result = _apply_effect(result, effect.fact, effect.operation, effect.value)
    return result


def _is_definitely_false(actual: object, operator: str, expected: JsonValue | None) -> bool:
    if actual is _UNKNOWN:
        return False
    if operator == "exists":
        return actual is _ABSENT
    if operator == "not_exists":
        return actual is not _ABSENT
    if actual is _ABSENT:
        return True
    if operator == "eq":
        return actual != expected
    if operator == "ne":
        return actual == expected
    return False


def _actual_detail(actual: object) -> JsonValue:
    if actual is _UNKNOWN:
        return "unknown"
    if actual is _ABSENT:
        return "absent"
    return actual  # type: ignore[return-value]


def _analyze_model(
    model: ProcessModel,
    activity: CanonicalActivity,
    scenario: Scenario,
    day: DayPlan,
    initial_state: dict[str, object],
    action_definitions: dict[str, Any],
    variables: dict[str, Any],
    model_index: int,
) -> tuple[dict[str, object], list[PreflightFinding]]:
    nodes = {node.node_id: node for node in model.nodes}
    node_indices = {node.node_id: index for index, node in enumerate(model.nodes)}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in model.edges:
        outgoing[edge.source_node_id].append(edge.target_node_id)
    starts = sorted(node.node_id for node in model.nodes if node.kind is ProcessNodeKind.start)
    if not starts:
        return initial_state, []

    arguments = {
        node.node_id: _resolve_arguments(node, activity, scenario, day, variables)
        for node in model.nodes
        if node.kind is ProcessNodeKind.action
    }
    incoming: dict[str, dict[str, object]] = {starts[0]: dict(initial_state)}
    pending = deque([starts[0]])
    iterations = 0
    iteration_limit = max(100, len(nodes) * len(nodes) * 8)
    while pending and iterations < iteration_limit:
        iterations += 1
        node_id = pending.popleft()
        node = nodes[node_id]
        output = incoming[node_id]
        node_arguments = arguments.get(node_id)
        if node.kind is ProcessNodeKind.action and node_arguments is not None:
            output = _transfer(output, node, node_arguments, action_definitions)
        for target in outgoing[node_id]:
            previous = incoming.get(target)
            merged = output if previous is None else _join(previous, output)
            if previous != merged:
                incoming[target] = merged
                pending.append(target)

    findings: list[PreflightFinding] = []
    for node in model.nodes:
        if node.kind is not ProcessNodeKind.action or node.node_id not in incoming:
            continue
        node_arguments = arguments.get(node.node_id)
        if node_arguments is None:
            continue
        definition = action_definitions[node.action_type or ""]
        string_arguments = {key: str(value) for key, value in node_arguments.items()}
        for precondition in definition.preconditions:
            fact = precondition.fact_template.format(**string_arguments)
            actual = _fact_value(incoming[node.node_id], fact)
            if not _is_definitely_false(actual, precondition.operator, precondition.value):
                continue
            findings.append(
                PreflightFinding(
                    path=(
                        "$.personalProcessPackage.processModels"
                        f"[{model_index}].nodes[{node_indices[node.node_id]}]"
                    ),
                    message=(
                        f"Action '{node.action_type}' has a precondition that is "
                        f"deterministically false for activity '{activity.source_activity_id}'."
                    ),
                    details={
                        "activityId": activity.source_activity_id,
                        "residentId": activity.actor_id,
                        "processModelId": model.process_model_id,
                        "nodeId": node.node_id,
                        "actionType": node.action_type or "",
                        "fact": fact,
                        "operator": precondition.operator,
                        "expected": precondition.value,
                        "actual": _actual_detail(actual),
                    },
                )
            )

    end_states = [
        incoming[node.node_id]
        for node in model.nodes
        if node.kind is ProcessNodeKind.end and node.node_id in incoming
    ]
    if not end_states:
        return initial_state, findings
    final_state = end_states[0]
    for state in end_states[1:]:
        final_state = _join(final_state, state)
    return final_state, findings


def validate_deterministic_preconditions(
    scenario: Scenario,
    plan: CanonicalPlan,
    package: PersonalProcessPackage,
    action_catalog: ActionCatalog,
    variable_catalog: VariableCatalog,
) -> list[PreflightFinding]:
    state: dict[str, object] = {}
    for resident in scenario.initial_state.residents:
        prefix = f"resident:{resident.resident_id}:"
        state[f"{prefix}resident.location"] = resident.location_id
        state[f"{prefix}resident.at_home"] = resident.facts.get(
            "at_home", not resident.location_id.startswith("outside")
        )
        for fact, value in resident.facts.items():
            state[f"{prefix}resident.{fact}"] = value
    for fact, value in scenario.initial_state.environment_facts.items():
        state[f"environment.{fact}"] = value

    models = {model.process_model_id: model for model in package.process_models}
    model_indices = {
        model.process_model_id: index for index, model in enumerate(package.process_models)
    }
    action_definitions = {item.action_type: item for item in action_catalog.actions}
    variables = {item.variable_id: item for item in variable_catalog.variables}
    days = {day.date: day for day in scenario.days}
    activities = sorted(
        (activity for plan_day in plan.days for activity in plan_day.activities),
        key=lambda item: (item.scheduled_start, item.sequence_index, item.source_activity_id),
    )
    findings: list[PreflightFinding] = []
    for activity in activities:
        day = days[activity.scheduled_start.date()]
        candidates = [
            binding
            for binding in package.bindings
            if binding.resident_id == activity.actor_id
            and binding.intent == activity.intent
            and _binding_applies(binding, scenario, day, activity.actor_id, variables)
        ]
        primary = [binding for binding in candidates if not binding.fallback]
        selected = primary if primary else [binding for binding in candidates if binding.fallback]
        if len(selected) != 1:
            continue
        model = models[selected[0].process_model_id]
        prefix = f"resident:{activity.actor_id}:"
        resident_state = {
            fact.removeprefix(prefix): value
            for fact, value in state.items()
            if fact.startswith(prefix)
        }
        shared_state = {
            fact: value for fact, value in state.items() if not fact.startswith("resident:")
        }
        next_state, model_findings = _analyze_model(
            model,
            activity,
            scenario,
            day,
            {**shared_state, **resident_state},
            action_definitions,
            variables,
            model_indices[model.process_model_id],
        )
        findings.extend(model_findings)
        for fact in list(state):
            if fact.startswith(prefix) or not fact.startswith("resident:"):
                del state[fact]
        for fact, value in next_state.items():
            state[f"{prefix}{fact}" if fact.startswith("resident.") else fact] = value
    return findings
