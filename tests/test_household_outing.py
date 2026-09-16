"""A shared outing: the participant goes out of the door with the actor, and comes back through it.

The engine sends a participant to the room the actor's providers are in, and read the first one it
found. An outing opens with `leave_home`, bound to the front door in the living room, so for a month
of Saturdays the participant of the household shop "bought groceries" on the living-room sofa while
the actor was at the supermarket — the trace, the sensor log and the habit ground truth all said so.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from smart_home_sim.domain.behavior import (
    PersonalProcessPackage,
    ProcessEdge,
    ProcessModel,
    ProcessNode,
)
from smart_home_sim.domain.environment import SimulationBundle
from smart_home_sim.domain.execution import ActivityExecution, ExecutionTrace
from smart_home_sim.hybrid_planning.outline import HorizonOutline, JointActivity
from smart_home_sim.hybrid_planning.recurring_activities import RecurringActivityKind
from tests.test_household_simulation import (
    _RESIDENTS,
    _ROOMS,
    _executions,
    _is,
    _outline,
    _package,
    _placed,
    _recurring,
    materialized_run,
)


def _through_the_door(model: ProcessModel) -> ProcessModel:
    """The reference shop, the way an authored outing writes it: out of the door and back in.

    The reference model walks straight to the shop through the transit and never comes home, so it
    has no door for anybody to follow. An authored one — the Ferri household's — leaves first.
    """

    def action(node_id: str, action_type: str, role: str | None = None) -> ProcessNode:
        arguments = {"targetRole": {"source": "literal", "value": role}} if role else {}
        return ProcessNode.model_validate_json(
            json.dumps(
                {
                    "nodeId": node_id,
                    "kind": "action",
                    "actionType": action_type,
                    "arguments": arguments,
                    "durationWeight": 1.0,
                }
            )
        )

    inner = [item for item in model.nodes if item.kind == "action"]
    nodes = [
        next(item for item in model.nodes if item.kind == "start"),
        action("home_exit", "move_to_capability", "home_exit"),
        action("leave_home", "leave_home"),
        *inner,
        action("home_entrance", "move_to_capability", "home_entrance"),
        action("enter_home", "enter_home"),
        next(item for item in model.nodes if item.kind == "end"),
    ]
    edges = [
        ProcessEdge(source_node_id=left.node_id, target_node_id=right.node_id)
        for left, right in zip(nodes, nodes[1:], strict=False)
    ]
    return model.model_copy(update={"nodes": nodes, "edges": edges})


def _outing_package() -> PersonalProcessPackage:
    package = _package()
    return package.model_copy(
        update={
            "process_models": [
                _through_the_door(item)
                if item.process_model_id.endswith("__buy_groceries")
                else item
                for item in package.process_models
            ]
        }
    )


def _outing_outline() -> HorizonOutline:
    outline = _outline()
    shop = JointActivity(
        activity=_recurring(
            "groceries", RecurringActivityKind.anchor, ("15:00", "17:00"), "buy_groceries"
        ),
        participant_ids=list(_RESIDENTS),
    )
    household = outline.household.model_copy(
        update={"joint_activities": [*outline.household.joint_activities, shop]}
    )
    return HorizonOutline.model_validate_json(
        outline.model_copy(update={"household": household}).model_dump_json(by_alias=True)
    )


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return materialized_run(_outing_outline(), tmp_path_factory.mktemp("outing"), _outing_package())


@pytest.fixture(scope="module")
def trace(run: Path) -> ExecutionTrace:
    return ExecutionTrace.model_validate_json(
        (run / "execution-trace.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def outings(trace: ExecutionTrace) -> list[ActivityExecution]:
    found = [
        item
        for item in trace.activity_executions
        if item.intent == "buy_groceries" and item.participant_ids and item.status != "dropped"
    ]
    assert found, "the plan shared no outing to test"
    return found


def _region_at(trace: ExecutionTrace, resident: str, moment: datetime) -> str | None:
    region = None
    for movement in sorted(trace.movements, key=lambda item: item.ended_at):
        if movement.actor_id == resident and movement.ended_at <= moment:
            region = movement.destination_region_id
    return region


def test_the_participant_is_out_where_the_actor_is(
    trace: ExecutionTrace, outings: list[ActivityExecution]
) -> None:
    for item in outings:
        middle = item.actual_start + (item.actual_end - item.actual_start) / 2
        actor = _region_at(trace, item.actor_id, middle)
        assert actor == "outdoors"
        for participant in item.participant_ids:
            assert _region_at(trace, participant, middle) == actor, (item.actual_start, participant)


def test_the_participant_goes_through_the_front_door_both_ways(
    trace: ExecutionTrace, outings: list[ActivityExecution]
) -> None:
    """Her own `leave_home` and `enter_home`, under the outing, naming the door the actor used."""
    actions = {item.action_execution_id: item for item in trace.action_executions}
    for item in outings:
        mine = [actions[action_id] for action_id in item.action_execution_ids]
        door = {
            provider
            for action in mine
            if action.actor_id == item.actor_id and action.action_type == "leave_home"
            for provider in action.provider_ids
        }
        for participant in item.participant_ids:
            hers = sorted(
                (action for action in mine if action.actor_id == participant),
                key=lambda action: action.started_at,
            )
            crossings = [
                action for action in hers if action.action_type in {"leave_home", "enter_home"}
            ]
            assert [action.action_type for action in crossings] == ["leave_home", "enter_home"]
            assert all(door <= set(action.provider_ids) for action in crossings)

            at_home = [
                transition.value
                for transition in sorted(trace.state_transitions, key=lambda row: row.at)
                if transition.subject_id == participant
                and transition.fact == "at_home"
                and item.actual_start <= transition.at <= item.actual_end
            ]
            assert at_home == [False, True]


def test_the_front_door_contact_hears_the_participant(
    run: Path, outings: list[ActivityExecution]
) -> None:
    """The door opens for two bodies, and the oracle says whose each opening was."""
    links = json.loads((run / "oracle-mapping.json").read_text(encoding="utf-8"))["links"]
    log = json.loads((run / "observable-sensor-log.json").read_text(encoding="utf-8"))
    door = {
        record["observationId"]
        for record in log["records"]
        if record["sensorId"] == "contact_entrance_door"
    }
    opened_by = {
        resident
        for link in links
        if link["observationId"] in door
        and set(link["activityExecutionIds"]) & {item.activity_execution_id for item in outings}
        for resident in link["residentIds"]
    }

    assert opened_by == set(_RESIDENTS)


def test_a_toilet_trip_due_while_she_is_out_is_given_up_not_kept_for_her_return(run: Path) -> None:
    """She cannot be interrupted for the toilet at the supermarket, and it does not wait for her.

    Queued behind the outing on her lock, a trip planned for mid-morning ran the moment she came
    home: 100 on the Verdi months, the latest nine and a half hours after it was due.
    """
    bundle = SimulationBundle.model_validate_json(
        (run / "simulation-bundle.json").read_text(encoding="utf-8")
    )
    outing = next(
        item
        for item in bundle.canonical_plan.days[0].activities
        if item.intent == "buy_groceries" and item.participant_ids
    )
    minutes = int(outing.duration_microseconds // 60_000_000)
    middle = outing.scheduled_start + timedelta(minutes=minutes / 2)
    trace, executions = _executions(
        _placed(
            run,
            {
                "outing": (
                    lambda item: item.source_activity_id == outing.source_activity_id,
                    outing.scheduled_start,
                    minutes,
                ),
                "toilet": (_is(outing.actor_id, "use_toilet"), middle, 6),
            },
        )
    )
    toilet = executions["toilet"]

    assert toilet.status == "dropped"
    assert toilet.actual_start - toilet.planned_start < timedelta(minutes=1)
    assert [
        item.cause_id
        for item in trace.plan_deviations
        if item.activity_execution_id == toilet.activity_execution_id
        and item.kind == "optional_dropped"
    ] == ["resident_away"]


def test_she_is_out_until_she_comes_in_through_the_door(
    trace: ExecutionTrace, outings: list[ActivityExecution]
) -> None:
    """The way home is spent on the way, and the door opens as she arrives.

    Walked first, the minute of walking left the rest of the leg's budget to be spent standing in
    the living room with `at_home` false and the door still shut: 53 minutes of every Verdi Sunday
    out, and six of every working day.
    """
    for item in outings:
        mine = sorted(
            (
                action
                for action in trace.action_executions
                if action.activity_execution_id == item.activity_execution_id
                and action.actor_id == item.actor_id
            ),
            key=lambda action: action.started_at,
        )
        entered = next(action for action in mine if action.action_type == "enter_home")
        arrived = max(
            movement.ended_at
            for movement in trace.movements
            if movement.actor_id == item.actor_id
            and movement.ended_at <= entered.started_at
            and movement.destination_region_id in _ROOMS
            and movement.origin_region_id not in _ROOMS
        )
        assert timedelta() <= entered.started_at - arrived < timedelta(minutes=1)
