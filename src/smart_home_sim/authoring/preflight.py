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
from smart_home_sim.domain.environment import (
    ENTITY_TYPE_CAPABILITIES,
    UNIVERSAL_ENTITY_CAPABILITIES,
)
from smart_home_sim.domain.models import (
    DayPlan,
    LocationKind,
    Scenario,
    resource_roles_for_type,
    resource_types_for_role,
)
from smart_home_sim.domain.plan import CanonicalActivity, CanonicalPlan
from smart_home_sim.domain.sensors import CONTACT_INSTRUMENTED_TYPES

_UNKNOWN = object()
_ABSENT = object()
# Capabilities the resident carries or the floor provides, never a piece of furniture. The
# materialiser excludes them when it assigns capabilities, and a reachability check has to exclude
# them too or every object would look reachable through `move_to`.
_SELF_CAPABILITIES = frozenset({"reachable", "transport_reachable", "posture_control"})


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
            present = expression.index is not None and expression.index < len(
                activity.required_resources
            )
            value = activity.required_resources[expression.index].resource_id if present else None
        elif expression.source is ValueSource.activity_intent:
            present, value = True, activity.intent
        elif expression.source is ValueSource.actor:
            present, value = True, activity.actor_id
        else:
            definition = variables.get(expression.variable_id or "")
            if definition is None:
                present, value = False, None
            else:
                present, value = _resolve_variable(definition, scenario, day, activity.actor_id)
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
            [item for item in current if item != value] if isinstance(current, list) else _UNKNOWN
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


def validate_away_round_trips(package: PersonalProcessPackage) -> list[PreflightFinding]:
    """An activity performed away from home has to bring the resident back.

    `leave_home` requires `resident.at_home` to be true and `enter_home` requires it to be false,
    so a model that leaves without returning does not merely describe an odd day: it leaves the
    fact stuck, and *every later outing* fails a precondition that is now deterministically false.
    On one authored horizon that surfaced as five `DETERMINISTIC_PRECONDITION_FAILED` findings
    against events weeks apart, none of which named the model that had actually broken the state.

    The mirror image is just as wrong and much quieter. A model bound to an away intent that never
    leaves at all — `work_shift` implemented as sitting down at a desk — is accepted by every gate,
    and the resident then spends the whole horizon indoors: one generated eight-month run contains
    zero `leave_home` actions and 74 door events, against roughly 3.9 a day in CASAS Aruba. Nothing
    reported it, because nothing was looking.

    Both are structural, so both are caught here rather than after a horizon has been expanded.
    """
    from smart_home_sim.hybrid_planning.intents import intent_spec

    def is_outdoors(intent: str) -> bool:
        """Where the catalog puts the activity, not which list the intent came from.

        Two mechanisms used to decide this and they disagreed. `away_intent_specs` selects by
        category — travel, work, social_visit — while the room comes from `default_location`, and
        `evening_walk` and `buy_groceries` sit `outdoors` under categories the first one does not
        collect. They slipped through: a horizon where the resident shopped weekly and walked most
        evenings produced sixteen door crossings in eight months, all of them from two events.
        The room is the fact that matters, so the room decides.
        """
        try:
            return intent_spec(intent).default_location == "outdoors"
        except KeyError:
            return False

    models = {model.process_model_id: model for model in package.process_models}
    findings: list[PreflightFinding] = []
    for index, binding in enumerate(package.bindings):
        if not is_outdoors(binding.intent):
            continue
        model = models.get(binding.process_model_id)
        if model is None:
            continue
        leaves = sum(1 for node in model.nodes if node.action_type == "leave_home")
        enters = sum(1 for node in model.nodes if node.action_type == "enter_home")
        if leaves == enters and leaves > 0:
            continue
        if leaves == 0 and enters == 0:
            message = (
                f"Process model {model.process_model_id!r} implements the away intent "
                f"{binding.intent!r} without ever leaving the home. The resident stays indoors, "
                "the door is never observed, and the absence is invisible to any sensor."
            )
        else:
            message = (
                f"Process model {model.process_model_id!r} leaves the home {leaves} time(s) and "
                f"returns {enters} time(s). An away activity is a round trip: unbalanced, it "
                "leaves 'resident.at_home' stuck and every later outing fails its precondition."
            )
        findings.append(
            PreflightFinding(
                path=f"$.bindings[{index}].processModelId",
                message=message,
                details={
                    "intent": binding.intent,
                    "processModelId": model.process_model_id,
                    "leaveHome": leaves,
                    "enterHome": enters,
                },
            )
        )
    return findings


def validate_the_resident_goes_out(scenario: Scenario) -> list[PreflightFinding]:
    """Does this horizon ever take the resident through the front door on a routine?

    A warning rather than a rejection, because a housebound resident is a legitimate — and
    research-relevant — subject. What is not legitimate is producing one by accident, which is what
    kept happening: an outline declaring no outdoor recurring activity at all yielded sixteen door
    crossings across eight months, every one of them from an event, while a real household records
    several a day. The front door is the single most informative sensor in a smart home, and a
    horizon that never uses it has thrown that channel away without anyone deciding to.
    """
    from smart_home_sim.hybrid_planning.intents import intent_spec

    def outdoors(intent: str) -> bool:
        try:
            return intent_spec(intent).default_location == "outdoors"
        except KeyError:
            return False

    outings = sum(
        1 for day in scenario.days for activity in day.activities if outdoors(activity.intent)
    )
    days = max(len(scenario.days), 1)
    per_week = 7 * outings / days
    if per_week >= 1:
        return []
    return [
        PreflightFinding(
            path="$.days",
            message=(
                f"The resident leaves the home {outings} time(s) across {days} days — fewer than "
                "once a week. Declare recurring outdoor activities such as a weekly shop or a "
                "walk: without them the door sensor observes almost nothing, and the horizon "
                "describes someone housebound."
            ),
            details={"outings": outings, "days": days, "outingsPerWeek": round(per_week, 3)},
        )
    ]


# The intent that puts paid work inside the dwelling. Named here rather than imported so this
# module keeps depending on nothing in `hybrid_planning`.
_HOME_WORK_INTENT = "work_from_home"
# Two home-work activities closer together than this are one stretch at the desk: the resident
# stood up and sat back down, which is not a break by any measure a sensor would recognise.
_HOME_WORK_JOIN_MINUTES = 15
# How long an unbroken stretch may run before it stops describing someone at home. Four hours is
# the outer edge of what the occupational-health literature treats as one work bout, and it is also
# where a single activity starts to own a whole room's sensor signal for the afternoon.
_HOME_WORK_MONOLITH_MINUTES = 240
# The share of working days that must show the monolith before it is the horizon's shape rather
# than a deadline.
_HOME_WORK_MONOLITH_SHARE = 0.5


def validate_home_work_is_fragmented(scenario: Scenario) -> list[PreflightFinding]:
    """Does the resident who works from home ever get up from the desk?

    Working from home is the one occupation a home sensor network can observe, and what it observes
    is movement: the kitchen at eleven, the balcony at three, a call taken standing in the hallway.
    A resident modelled as a single unbroken block is a resident modelled as furniture. Her motion
    sensor reports one long occupancy, every other room falls silent for the whole afternoon, and
    the segmentation target for the middle of the day becomes a rectangle no algorithm has to work
    to find.

    The check is on the *plan*, not on the outline, because the two ways of authoring a working day
    arrive here as the same thing: a `fixedCommitment` from 09:00 to 17:30 and a daily recurring
    activity whose one occurrence runs seven hours are both one activity in the day, and both are
    what this is looking for.

    A warning, not a rejection. Eight hours at a desk without standing up is a real way to spend a
    Tuesday and a legitimate case to study — a researcher who wants it says so with a commitment
    and keeps this finding. What is not legitimate is arriving at it by default, which is the
    likelier reading when it holds on most of the horizon's working days.
    """
    stretches: list[float] = []
    monoliths = 0
    by_day: dict[object, list[tuple[float, float]]] = defaultdict(list)
    for day in scenario.days:
        for activity in day.activities:
            if activity.intent != _HOME_WORK_INTENT:
                continue
            if activity.start_window is None or activity.duration is None:
                continue
            begin = activity.start_window.preferred
            offset = float(begin.hour * 60 + begin.minute)
            by_day[day.date].append((offset, offset + float(activity.duration.preferred_minutes)))

    for spans in by_day.values():
        longest = 0.0
        current_start, current_end = None, None
        for start, end in sorted(spans):
            if current_end is not None and start - current_end <= _HOME_WORK_JOIN_MINUTES:
                current_end = max(current_end, end)
            else:
                if current_end is not None and current_start is not None:
                    longest = max(longest, current_end - current_start)
                current_start, current_end = start, end
        if current_end is not None and current_start is not None:
            longest = max(longest, current_end - current_start)
        stretches.append(longest)
        if longest >= _HOME_WORK_MONOLITH_MINUTES:
            monoliths += 1

    if not stretches or monoliths < _HOME_WORK_MONOLITH_SHARE * len(stretches):
        return []
    longest_overall = max(stretches)
    return [
        PreflightFinding(
            path="$.days",
            message=(
                f"On {monoliths} of {len(stretches)} working days the resident works from home in "
                f"one unbroken stretch of at least {_HOME_WORK_MONOLITH_MINUTES // 60} hours — the "
                f"longest runs {longest_overall / 60:.1f}. Working from home is observable only "
                "through the breaks: give the activity a daily cadence with several occurrences so "
                "the day is blocks rather than a block, and declare what happens between them. A "
                "single stretch leaves one room's sensor holding the whole afternoon and hands a "
                "segmentation algorithm a rectangle."
            ),
            details={
                "workingDays": len(stretches),
                "monolithicDays": monoliths,
                "longestStretchMinutes": round(longest_overall, 1),
                "thresholdMinutes": _HOME_WORK_MONOLITH_MINUTES,
            },
        )
    ]


# A room hosting at least this many distinct intents is somewhere the resident works, not passes
# through, and needs more than one object to work with.
_BUSY_ROOM_INTENTS = 3


def validate_rooms_are_furnished(scenario: Scenario) -> list[PreflightFinding]:
    """Does every busy room contain the objects its activities need?

    The home generator materialises the resources the scenario declares and fabricates one
    `generated_environment_service` per room for everything else — a provider with no footprint and
    no contact sensor. Nothing reports the substitution, so a kitchen declaring a single moka
    absorbed seven intents and 705 hours of cooking, eating and cleaning against one phantom point.

    The consequences are not subtle. Every one of those hours retriggered the same motion sensor,
    which ended up carrying 66.5% of an entire eight-month dataset; and contact sensors attach to
    objects that open, so a kitchen with no fridge and no cupboards contributed none. The whole
    house had one contact sensor where CASAS Aruba has four.

    Caught here, on the scenario, because it costs an author one line to fix and costs a run eight
    months to discover.
    """
    # Rooms only. `outdoors` hosts the shopping and the walks and is furnished by the world, not by
    # the resident; a composite is a grouping and owns nothing of its own.
    rooms = {
        location.location_id
        for location in scenario.locations
        if location.kind is LocationKind.room
    }
    intents_by_room: dict[str, set[str]] = defaultdict(set)
    activities_by_room: dict[str, int] = defaultdict(int)
    for day in scenario.days:
        for activity in day.activities:
            for location in activity.location_ids[:1]:
                if location not in rooms:
                    continue
                intents_by_room[location].add(activity.intent)
                activities_by_room[location] += 1

    resources_by_room: dict[str, list[str]] = defaultdict(list)
    for resource in scenario.resources:
        resources_by_room[resource.location_id].append(resource.resource_id)

    findings: list[PreflightFinding] = []
    for room in sorted(intents_by_room):
        intents = intents_by_room[room]
        declared = resources_by_room.get(room, [])
        if len(intents) < _BUSY_ROOM_INTENTS or len(declared) > 1:
            continue
        findings.append(
            PreflightFinding(
                path="$.resources",
                message=(
                    f"Room {room!r} hosts {len(intents)} distinct intents across "
                    f"{activities_by_room[room]} activities but declares "
                    f"{len(declared)} object(s): {', '.join(declared) or 'none'}. Everything else "
                    "will run against a generated placeholder with no footprint and no contact "
                    "sensor, concentrating the room's whole signal on one point. Declare the "
                    "furniture the activities use."
                ),
                details={
                    "room": room,
                    "intents": sorted(intents),
                    "activities": activities_by_room[room],
                    "declaredResources": sorted(declared),
                },
            )
        )
    return findings


# Somewhere a person can plausibly settle for a while. A corridor with a shoe cabinet is not.
_DWELLABLE_RESOURCE_TYPES = frozenset(
    {"armchair", "bed", "bench", "chair", "couch", "recliner", "sofa", "stool"}
)


def validate_activities_do_not_park_the_resident(
    scenario: Scenario, package: PersonalProcessPackage
) -> list[PreflightFinding]:
    """Where does a process model leave the resident standing when it ends?

    Whatever room the last action reaches is where she stays until the next activity moves her,
    and that is most of a day. On one authored horizon eight of twenty-two models ended with
    `move_to hallway`, so the resident spent 4.1 hours a day standing in a corridor furnished with
    a shoe cabinet.

    Nothing reported it because standing still used to be invisible: motion pulses came only from
    movements and from catalogued actions, so a parked resident emitted nothing and the corridor
    looked quiet. Once presence began to register, those two corridor sensors carried 23% of the
    whole dataset — the defect had been there all along, silently distorting where the resident
    was, and only the sensor model had been hiding it.

    A warning, not a rejection: ending in a hallway is fine when the next activity starts there.
    Ending *every* activity there is an author having declined to say where the resident lives
    between them.
    """
    dwellable_rooms = {
        resource.location_id
        for resource in scenario.resources
        if resource.resource_type in _DWELLABLE_RESOURCE_TYPES
    }
    rooms = {
        location.location_id
        for location in scenario.locations
        if location.kind is LocationKind.room
    }

    findings: list[PreflightFinding] = []
    for index, model in enumerate(package.process_models):
        terminal = {edge.source_node_id for edge in model.edges if edge.target_node_id == "end"}
        nodes = {node.node_id: node for node in model.nodes}
        for node_id in sorted(terminal):
            node = nodes.get(node_id)
            if node is None or node.action_type != "move_to":
                continue
            argument = node.arguments.get("destination")
            destination = getattr(argument, "value", None) if argument is not None else None
            if not isinstance(destination, str):
                continue
            if destination not in rooms or destination in dwellable_rooms:
                continue
            findings.append(
                PreflightFinding(
                    path=f"$.processModels[{index}].nodes",
                    message=(
                        f"Process model {model.process_model_id!r} ends by moving the resident to "
                        f"{destination!r}, which declares nothing to sit or lie on. She stays "
                        "there until the next activity moves her, so a room meant to be crossed "
                        "becomes where she spends her day and its sensors dominate the log. End "
                        "the model where she would actually settle, or leave her where she is."
                    ),
                    details={
                        "processModelId": model.process_model_id,
                        "destination": destination,
                        "nodeId": node_id,
                    },
                )
            )
    return findings


def validate_declared_objects_are_reachable(
    scenario: Scenario, package: PersonalProcessPackage, action_catalog: ActionCatalog
) -> list[PreflightFinding]:
    """Could any action in the package ever bind to this piece of furniture at all?

    The sibling check above asks whether an *instrumented* object is ever opened, so it sees only
    things with a door. This one asks the prior question of every declared object: is there any
    action, anywhere in the package, that could reach it. A five-month horizon for a father of two
    declared a wardrobe, a washing machine and three storage cabinets and then gave him no laundry,
    no change of clothes and no cleaning — the furniture was right and the life was missing.

    "Reachable" is deliberately weaker than "used". An action binds to a provider by asking for a
    capability, optionally narrowed to a role, and the binder then picks one of the candidates. A
    sofa that offers `leisure_support` is reachable by every `leisure` action even when the armchair
    wins the tie, and flagging it would be wrong: nothing in the authored bundle decides that
    contest. Only an object no request can name is reported, which is why this is a warning about a
    hole in the *behaviour*, not about a piece of furniture the binder happened not to choose.

    A resource type absent from `ENTITY_TYPE_CAPABILITIES` offers everything, so a scenario naming
    its own furniture is never reported here.
    """
    definitions = {item.action_type: item for item in action_catalog.actions}
    requests: set[tuple[str, str | None]] = set()
    for model in package.process_models:
        for node in model.nodes:
            definition = definitions.get(node.action_type or "")
            if definition is None:
                continue
            for requirement in definition.required_capabilities:
                if requirement.capability in _SELF_CAPABILITIES:
                    continue
                role: str | None = None
                if requirement.parameter_name is not None:
                    argument = node.arguments.get(requirement.parameter_name)
                    # A role the author did not spell as a literal is resolved at run time, so it
                    # could name anything: treat it as the wildcard it is rather than guess.
                    if argument is not None and argument.source is ValueSource.literal:
                        role = str(argument.value)
                requests.add((requirement.capability, role))

    by_type: dict[str, list[str]] = defaultdict(list)
    for resource in scenario.resources:
        offered = ENTITY_TYPE_CAPABILITIES.get(resource.resource_type)
        roles = {resource.resource_id, resource.resource_type} | resource_roles_for_type(
            resource.resource_type
        )
        if any(
            (
                offered is None
                or capability in offered
                or capability in UNIVERSAL_ENTITY_CAPABILITIES
            )
            and (role is None or role in roles)
            for capability, role in requests
        ):
            continue
        by_type[resource.resource_type].append(resource.resource_id)

    findings: list[PreflightFinding] = []
    for resource_type in sorted(by_type):
        resources = sorted(by_type[resource_type])
        findings.append(
            PreflightFinding(
                path="$.world.resources",
                message=(
                    f"The home declares {len(resources)} {resource_type!r} "
                    f"({', '.join(resources)}), but no activity in the profile ever reaches one: "
                    "no action in any process model asks for a capability this object offers. It "
                    "will stand in the home for the whole horizon untouched. Either add the "
                    "recurring activity that uses it, or remove the object from the world."
                ),
                details={"resourceType": resource_type, "resources": resources},
            )
        )
    return findings


def validate_instrumented_objects_are_opened(
    scenario: Scenario, package: PersonalProcessPackage
) -> list[PreflightFinding]:
    """Does the behaviour ever touch the furniture the deployment puts a reed switch on?

    A contact sensor is fitted because the object has a door, not because the script happens to
    open it — an installer wires the medicine cabinet before the study begins, and eight months of
    silence from it is a measurement. That is the right rule, and it is why this is a check on the
    *behaviour* rather than on the deployment.

    What it catches is the other case: an object the resident demonstrably uses and never opens.
    Measured on a generated year, `start_laundry` ran 104 times and `hang_laundry` 104 more while
    the washing machine's contact reported 53 openings — against 54.8 expected from the noise
    model's false-positive rate alone, so every one of them was spurious. The same held for the
    wardrobe, which a resident who dresses every morning never opened. All 1 444 `open` actions in
    the horizon went to the refrigerator and the kitchen cupboard.

    Four of the home's seven contact sensors therefore published nothing but noise, which is both
    a fifth of the sensor inventory wasted and, worse, a lost behavioural marker: a wardrobe
    opening at 07:00 is exactly what separates "asleep" from "awake" for a segmentation algorithm
    that otherwise sees only a bedroom motion sensor.

    The check is per *type*, because that is the granularity a process model works at: a node
    opens a `storage_cabinet`, and which cabinet it turns out to be is decided at run time by
    where the activity happens. So a home declaring three cabinets of which only the kitchen one is
    ever opened passes this check while leaving two sensors silent. Catching that needs the room
    each activity runs in, and is not attempted here.

    A target is resolved the way materialization resolves it, through `RESOURCE_ROLE_ALIASES`. It
    read the literal as a bare resource type at first, which is not how anyone writes these: the
    reference models open `food_storage` and `laundry_equipment`, never `refrigerator` and
    `washing_machine`, so the check reported all four types as untouched for behaviour that opens
    them correctly — and would have flagged the reference models themselves. It only ever passed
    for an author who had departed from the spelling the reference sets.
    """
    opened: set[str] = set()
    types_by_resource_id = {
        resource.resource_id: resource.resource_type for resource in scenario.resources
    }
    for model in package.process_models:
        for node in model.nodes:
            if node.action_type not in {"open", "close"}:
                continue
            target = node.arguments.get("target")
            if target is None or target.source is not ValueSource.literal:
                continue
            literal = str(target.value)
            # A role can be served by several types and a literal can also name one declared piece
            # of furniture outright; both spellings bind at run time, so both count here.
            opened |= resource_types_for_role(literal)
            if literal in types_by_resource_id:
                opened.add(types_by_resource_id[literal])

    by_type: dict[str, list[str]] = defaultdict(list)
    for resource in scenario.resources:
        if resource.resource_type in CONTACT_INSTRUMENTED_TYPES:
            by_type[resource.resource_type].append(resource.resource_id)

    findings: list[PreflightFinding] = []
    for resource_type in sorted(set(by_type) - opened):
        resources = sorted(by_type[resource_type])
        findings.append(
            PreflightFinding(
                path="$.processModels",
                message=(
                    f"No process model ever opens a {resource_type!r}, but the home declares "
                    f"{len(resources)} of them ({', '.join(resources)}) and the deployment fits "
                    "each with a contact sensor. Those sensors will publish only false positives. "
                    "If the resident uses the object, give the activity that uses it an 'open' "
                    "action on it; if the object is genuinely never opened, the silence is a "
                    "measurement and this warning can stand."
                ),
                details={
                    "resourceType": resource_type,
                    "resources": resources,
                    "openedTypes": sorted(opened),
                },
            )
        )
    return findings
