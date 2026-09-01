from __future__ import annotations

import json
import random
import shutil
import zipfile
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree
from xml.sax.saxutils import XMLGenerator

import pytest
from pydantic import ValidationError

from smart_home_sim.application.export import (
    ExportService,
    _csv,
    _filtered,
    _items,
    _record_time,
    _xes,
    _xes_attribute,
)
from smart_home_sim.application.replay import ReplayService, _daily_summary_available_at
from smart_home_sim.application.workspace import WorkspaceError, WorkspaceService
from smart_home_sim.domain.application import (
    ExportFormat,
    ExportManifest,
    ExportRequest,
    JobProgress,
    JobStatus,
)
from smart_home_sim.domain.environment import Point2D
from smart_home_sim.domain.execution import (
    ActivityExecution,
    MovementExecution,
    StateTransition,
    TraceCausality,
)

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE = PROJECT_ROOT / "examples/materialization/mario_rossi_2026_10_30"


def _completed_workspace(root: Path) -> tuple[WorkspaceService, str]:
    """One imported run, ready to replay or export.

    A function rather than only a fixture because the module fixture is shared and one test
    deliberately corrupts a file in it, which puts the workspace into diagnostic mode: a test that
    needs to write afterwards has to bring its own.
    """
    workspace = WorkspaceService.create(root, "Replay")
    home = workspace.create_home("Mario")
    job = workspace.create_job("simulation", home_id=home.home_id, seed=123)
    workspace.update_job(
        job.job_id,
        JobStatus.running,
        JobProgress(phase="execution", percent=50, message="Executing"),
    )
    destination = workspace.runs_path / job.job_id
    shutil.copytree(SOURCE, destination)
    workspace.import_run_directory(job.job_id, destination)
    workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Done"),
        result_reference=job.job_id,
    )
    return workspace, job.job_id


@pytest.fixture(scope="module")
def completed_workspace(tmp_path_factory: pytest.TempPathFactory) -> tuple[WorkspaceService, str]:
    return _completed_workspace(tmp_path_factory.mktemp("application-run") / "workspace")


def test_ground_truth_diary_observable_and_oracle_views(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    diary, total = replay.diary(run_id, limit=5)
    assert total > 5
    assert diary[0].actions
    assert diary[0].source_activity_id
    assert len(diary[0].trace_semantic_digest) == 64
    filtered, filtered_total = replay.diary(
        run_id, actor_id=diary[0].actor_id, query=diary[0].intent, status=diary[0].status
    )
    assert filtered_total > 0
    assert all(item.actor_id == diary[0].actor_id for item in filtered)

    observable, observation_total = replay.observations(run_id, limit=3)
    assert observation_total > 3
    assert all(item.oracle_cause is None for item in observable)
    oracle, _ = replay.observations(run_id, include_oracle=True, limit=3)
    assert all(item.oracle_cause is not None for item in oracle)
    sensor_only, _ = replay.observations(run_id, sensor_id=oracle[0].sensor_id, limit=10)
    assert all(item.sensor_id == oracle[0].sensor_id for item in sensor_only)
    timeline = replay.timeline(run_id, limit=100)
    assert timeline == sorted(timeline, key=lambda item: (item["at"], item["kind"], item["id"]))
    assert {item["kind"] for item in timeline} <= {"activity", "action", "movement"}
    verification = replay.verify(run_id)
    assert verification.matches is True
    assert verification.actual_semantic_digest == verification.expected_semantic_digest


def test_replay_indexes_every_trace_family_and_bounds_windows(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    trace = json.loads(
        workspace.read_artifact(workspace.run_artifacts(run_id)["execution_trace"].artifact_id)
    )
    start = datetime.fromisoformat(trace["startedAt"])
    end = start + timedelta(hours=12)

    window = replay.events(run_id, start=start, end=end, limit=37)

    assert len(window.items) <= 37
    assert window.window_start == start
    assert window.window_end == end
    expected_kinds = {
        kind
        for kind, records in {
            "activity": trace["activityExecutions"],
            "action": trace["actionExecutions"],
            "movement": trace["movements"],
            "state_transition": trace["stateTransitions"],
            "resource": trace["resourceEvents"],
            "runtime_event": trace["runtimeEvents"],
            "plan_deviation": trace["planDeviations"],
            "daily_summary": [
                summary
                for summary in trace["dailySummaries"]
                if start
                <= _daily_summary_available_at(
                    date.fromisoformat(summary["date"]), datetime.fromisoformat(trace["endedAt"])
                )
                <= end
            ],
        }.items()
        if records
    }
    assert {
        item.kind for item in replay.events(run_id, start=start, end=end, limit=5000).items
    } >= expected_kinds
    assert "observation" in {item.kind for item in replay.events(run_id, limit=5000).items}


def test_replay_projects_daily_summaries_at_local_day_end_with_authoritative_counts(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    from zoneinfo import ZoneInfo

    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    index = replay._index(run_id)
    summary_timezone = (
        ZoneInfo(index.bundle.scenario.time_zone) if index.bundle is not None else None
    )

    oracle = replay.events(run_id, kinds={"daily_summary"}, include_oracle=True, limit=5_000)
    observable = replay.events(run_id, kinds={"daily_summary"}, limit=5_000)

    assert oracle.total == observable.total == len(index.trace.daily_summaries)
    assert [item.event_id for item in oracle.items] == [
        f"daily_summary:{summary.date.isoformat()}" for summary in index.trace.daily_summaries
    ]
    assert [item.at for item in oracle.items] == [
        _daily_summary_available_at(
            summary.date,
            index.trace.ended_at,
            timezone=summary_timezone,
        )
        for summary in index.trace.daily_summaries
    ]
    assert [(item.at, item.event_id) for item in oracle.items] == sorted(
        (item.at, item.event_id) for item in oracle.items
    )
    assert all(item.status == "completed" for item in oracle.items)
    assert all(item.label.startswith("Daily summary ") for item in oracle.items)
    assert all(
        item.details
        == {
            "completedActivityCount": summary.completed_activity_count,
            "deviatedActivityCount": summary.deviated_activity_count,
            "failedActivityCount": summary.failed_activity_count,
            "droppedActivityCount": summary.dropped_activity_count,
        }
        for item, summary in zip(oracle.items, index.trace.daily_summaries, strict=True)
    )
    assert [item.details for item in observable.items] == [item.details for item in oracle.items]
    assert all(item.label == "Daily Summary event" for item in observable.items)
    assert all(item.actor_id is None for item in observable.items)


def test_daily_summary_availability_uses_next_local_midnight_and_trace_end_clamp() -> None:
    from zoneinfo import ZoneInfo

    rome = ZoneInfo("Europe/Rome")
    trace_end = datetime(2026, 3, 30, 12, tzinfo=UTC)

    assert _daily_summary_available_at(
        date(2026, 3, 29), trace_end, timezone=rome
    ) == datetime(
        2026, 3, 30, 0, tzinfo=rome
    )
    assert _daily_summary_available_at(date(2026, 3, 30), trace_end, timezone=rome) == trace_end


def test_horizon_daily_summaries_keep_the_scenario_timezone_across_dst(tmp_path: Path) -> None:
    """Merged horizons have a scenario artifact, not one simulation bundle to supply its zone."""
    workspace = WorkspaceService.create(tmp_path / "horizon-workspace", "Replay")
    home = workspace.create_home("Mario")
    job = workspace.create_job("simulation", home_id=home.home_id, seed=123)
    destination = workspace.runs_path / job.job_id
    shutil.copytree(SOURCE, destination)
    trace_path = destination / "execution-trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["startedAt"] = "2026-10-24T00:00:00+02:00"
    trace["endedAt"] = "2026-10-27T12:00:00+01:00"
    trace["dailySummaries"] = [
        {
            "date": "2026-10-24",
            "completedActivityCount": 1,
            "deviatedActivityCount": 0,
            "failedActivityCount": 0,
            "droppedActivityCount": 0,
        }
    ]
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    (destination / "simulation-bundle.json").unlink()
    workspace.import_run_directory(job.job_id, destination)
    workspace.update_job(
        job.job_id,
        JobStatus.completed,
        JobProgress(phase="completed", percent=100, message="Done"),
        result_reference=job.job_id,
    )

    summary = ReplayService(workspace).events(
        job.job_id, kinds={"daily_summary"}, include_oracle=True
    ).items

    assert [item.at.isoformat() for item in summary] == ["2026-10-25T00:00:00+02:00"]


def test_replay_actor_filter_requires_oracle_opt_in(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    trace = json.loads(
        workspace.read_artifact(workspace.run_artifacts(run_id)["execution_trace"].artifact_id)
    )
    actor_id = trace["movements"][0]["actorId"]

    with pytest.raises(ValueError, match="actor filter requires include_oracle=True"):
        replay.events(run_id, actor_id=actor_id)

    oracle = replay.events(run_id, actor_id=actor_id, include_oracle=True)
    assert oracle.items
    assert all(item.actor_id == actor_id for item in oracle.items)


def test_replay_status_filter_counts_before_bounding(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    all_events = replay.events(run_id, limit=5000)
    status = next(item.status for item in all_events.items if item.status is not None)

    filtered = replay.events(run_id, statuses={status}, limit=5000)
    assert filtered.total == len(filtered.items)
    assert filtered.items
    assert all(item.status == status for item in filtered.items)
    assert replay.events(run_id, statuses={"not-a-status"}, limit=5000).total == 0


def test_replay_frame_is_random_seek_stable_and_oracle_is_opt_in(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    window = replay.events(run_id, limit=100)
    target = window.items[len(window.items) // 2].at

    first = replay.frame(run_id, at=target, include_oracle=False)
    replay.frame(run_id, at=window.trace_end, include_oracle=False)
    second = replay.frame(run_id, at=target, include_oracle=False)

    assert first == second
    assert all(item.oracle_cause is None for item in first.sensor_states)
    oracle = replay.frame(run_id, at=target, include_oracle=True)
    assert any(item.oracle_cause is not None for item in oracle.sensor_states)


def test_indexed_frame_reconstruction_matches_the_trace_fold_for_random_seeks(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    """The temporal index is an acceleration structure, never another simulation model."""
    from smart_home_sim.application import replay as replay_module

    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    index = replay._index(run_id)
    instants = [index.trace_start, index.trace_end]
    rng = random.Random("replay-index-equivalence-v1")
    seekable = index.event_times + index.observation_times
    instants.extend(seekable[rng.randrange(len(seekable))] for _ in range(48))
    rng.shuffle(instants)

    for instant in instants:
        expected_residents, expected_ids = replay_module._resident_frames(
            index.trace, index.bundle, instant
        )
        expected_world = replay_module._world_state_at(index.trace, index.bundle, instant)
        expected_resources = replay_module._resource_state_at(index.trace, index.bundle, instant)
        actual_residents, actual_ids = replay_module._resident_frames(
            index.trace, index.bundle, instant, index.frame_sources
        )
        actual_world = replay_module._world_state_at(
            index.trace, index.bundle, instant, index.frame_sources
        )
        actual_resources = replay_module._resource_state_at(
            index.trace, index.bundle, instant, index.frame_sources
        )

        assert actual_residents == expected_residents
        assert actual_ids == expected_ids
        assert actual_world == expected_world
        assert actual_resources == expected_resources


def test_replay_interpolation_uses_the_midpoint_between_two_waypoints() -> None:
    from smart_home_sim.application import replay as replay_module

    start = datetime(2026, 8, 23, 8, tzinfo=UTC)
    movement = MovementExecution.model_validate(
        {
            "movementId": "movement_1",
            "actionExecutionId": "action_1",
            "actorId": "resident_1",
            "startedAt": start,
            "endedAt": start + timedelta(seconds=10),
            "originRegionId": "origin",
            "destinationRegionId": "destination",
            "distanceMeters": 10,
            "durationMicroseconds": 10_000_000,
            "waypoints": [
                {
                    "at": start,
                    "regionId": "origin",
                    "position": Point2D(x=2, y=4),
                    "traversalMode": "walking",
                },
                {
                    "at": start + timedelta(seconds=10),
                    "regionId": "origin",
                    "position": Point2D(x=8, y=10),
                    "traversalMode": "walking",
                },
            ],
        }
    )

    assert replay_module._point_at(movement, start + timedelta(seconds=5)) == Point2D(x=5, y=7)


def test_replay_holds_the_body_at_the_foot_of_a_staircase() -> None:
    """Two storeys are drawn side by side, so the stair's two ends are metres apart on the page.

    Interpolated, the eight seconds of the climb are eight seconds of a body sliding diagonally
    across whatever the drawing has between the two blocks — through the bedroom wall and out the
    other side. She waits at the step she left from and arrives when she arrives; the replay has no
    third dimension to show her climbing in, and a body in the wrong room is a worse lie than a
    body that pauses.
    """
    from smart_home_sim.application import replay as replay_module

    start = datetime(2026, 8, 23, 8, tzinfo=UTC)
    movement = MovementExecution.model_validate(
        {
            "movementId": "movement_1",
            "actionExecutionId": "action_1",
            "actorId": "resident_1",
            "startedAt": start,
            "endedAt": start + timedelta(seconds=10),
            "originRegionId": "landing",
            "destinationRegionId": "hallway",
            "distanceMeters": 4.2,
            "durationMicroseconds": 10_000_000,
            "waypoints": [
                {
                    "at": start,
                    "regionId": "landing",
                    "position": Point2D(x=21.5, y=4.5),
                    "traversalMode": "walking",
                },
                {
                    "at": start + timedelta(seconds=10),
                    "regionId": "hallway",
                    "position": Point2D(x=7.0, y=5.6),
                    "traversalMode": "walking",
                },
            ],
        }
    )

    midway = replay_module._point_at(movement, start + timedelta(seconds=5))
    assert midway == Point2D(x=21.5, y=4.5)
    # A doorway is the other kind of crossing, and it is still walked through: its two portals sit
    # on a shared wall, centimetres apart, and holding there would freeze every step between rooms.
    doorway = movement.model_copy(
        update={
            "waypoints": [
                movement.waypoints[0],
                movement.waypoints[1].model_copy(update={"position": Point2D(x=21.5, y=6.5)}),
            ]
        }
    )
    assert replay_module._point_at(doorway, start + timedelta(seconds=5)) == Point2D(x=21.5, y=5.5)


def test_replay_without_a_bundle_seeds_transition_previous_values(tmp_path: Path) -> None:
    workspace, run_id = _completed_workspace(tmp_path / "workspace")
    with workspace.transaction() as connection:
        connection.execute(
            "DELETE FROM artifacts WHERE run_id = ? AND role = 'simulation_bundle'", (run_id,)
        )
    replay = ReplayService(workspace)
    index = replay._index(run_id)
    posture = next(
        item
        for item in index.trace.state_transitions
        if item.subject_type == "resident"
        and item.fact == "posture"
        and item.previous_value is not None
    )
    entity = next(
        item
        for item in index.trace.state_transitions
        if item.subject_type == "entity" and item.previous_value is not None
    )
    instant = min(posture.at, entity.at) - timedelta(microseconds=1)

    frame = replay.frame(run_id, at=instant)

    resident = next(item for item in frame.residents if item.resident_id == posture.subject_id)
    assert resident.posture == posture.previous_value
    assert frame.entity_states[entity.subject_id][entity.fact] == entity.previous_value
    with pytest.raises(WorkspaceError, match="final state"):
        replay.frame(run_id, at=index.trace_end)


def test_replay_bundle_fallback_keeps_the_first_transition_previous_value() -> None:
    from smart_home_sim.application import replay as replay_module

    at = datetime(2026, 8, 23, 8, tzinfo=UTC)
    trace = SimpleNamespace(
        state_transitions=[
            StateTransition(
                transition_id="first",
                at=at,
                subject_type="resident",
                subject_id="resident_1",
                fact="execution_state",
                previous_value="idle",
                value="performing_activity",
                operation="set",
                causality=TraceCausality(cause_type="action_effect", cause_id="action_1"),
            ),
            StateTransition(
                transition_id="second",
                at=at + timedelta(seconds=1),
                subject_type="resident",
                subject_id="resident_1",
                fact="execution_state",
                previous_value="performing_activity",
                value="moving",
                operation="set",
                causality=TraceCausality(cause_type="action_effect", cause_id="action_2"),
            ),
        ]
    )

    seeded = replay_module._initial_residents(trace, None)

    assert seeded["resident_1"]["execution_state"] == "idle"


def test_observable_replay_events_hide_execution_identifiers_but_oracle_events_keep_them(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    index = replay._index(run_id)
    raw_ids = {
        "activity": {item.activity_execution_id for item in index.trace.activity_executions},
        "action": {item.action_execution_id for item in index.trace.action_executions},
        "plan_deviation": {item.deviation_id for item in index.trace.plan_deviations},
    }
    assert all("oracleCause" not in item.details for item in index.events)
    assert all(
        "oracleCause" not in item.details
        for item in replay.events(run_id, kinds={"observation"}, limit=5_000).items
    )
    for kind, identifiers in raw_ids.items():
        observable = json.dumps(
            replay.events(run_id, kinds={kind}).model_dump(mode="json", by_alias=True)
        )
        oracle = json.dumps(
            replay.events(run_id, kinds={kind}, include_oracle=True).model_dump(
                mode="json", by_alias=True
            )
        )

        assert not any(identifier in observable for identifier in identifiers)
        assert all(identifier in oracle for identifier in identifiers)
    assert any(
        "oracleCause" in item.details
        for item in replay.events(run_id, kinds={"observation"}, include_oracle=True).items
    )


def test_replay_observable_and_oracle_results_are_isolated_from_the_cache(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    first = replay.events(run_id, include_oracle=True, limit=5000)
    movement = next(item for item in first.items if item.kind == "movement")
    action = next(item for item in first.items if item.kind == "action")
    movement.waypoints[0].position.x = -999
    action.details["nodeId"] = "mutated"

    second = replay.events(run_id, include_oracle=True, limit=5000)
    cached_movement = next(item for item in second.items if item.event_id == movement.event_id)
    cached_action = next(item for item in second.items if item.event_id == action.event_id)

    assert cached_movement.waypoints[0].position.x != -999
    assert cached_action.details["nodeId"] != "mutated"

    frame = replay.frame(run_id, at=replay._index(run_id).trace.movements[0].started_at)
    frame.residents[0].facts["cacheMutation"] = True
    fresh_frame = replay.frame(run_id, at=replay._index(run_id).trace.movements[0].started_at)
    assert "cacheMutation" not in fresh_frame.residents[0].facts


def test_observable_replay_never_reads_the_oracle_mapping(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    """The largest artifact a run owns is also the one Observable replay may not see.

    Reading it anyway made opening a long run cost more memory than the machine had, for
    evidence the session was never allowed to show.
    """
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    index = replay._index(run_id)

    assert index.oracle.available, "this fixture is only meaningful with an oracle artifact"
    assert not index.oracle.loaded

    replay.events(run_id, limit=5_000)
    replay.frame(run_id, at=index.trace_start)
    replay.frame(run_id, at=index.trace_end)

    assert not index.oracle.loaded

    oracle_window = replay.events(run_id, kinds={"observation"}, include_oracle=True, limit=5_000)

    assert index.oracle.loaded
    assert any(item.details.get("oracleCause") for item in oracle_window.items)


def test_replay_windows_project_observations_only_within_their_bound(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    """Observations outnumber the trace, so they are built per window, not held for the run."""
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    index = replay._index(run_id)

    assert all(item.kind != "observation" for item in index.events)

    full = replay.events(run_id, limit=5_000)
    bounded = replay.events(run_id, limit=3)

    assert {item.kind for item in full.items} >= {"observation"}
    assert bounded.total == full.total
    assert [item.event_id for item in bounded.items] == [item.event_id for item in full.items[:3]]
    # A status or actor filter excludes the whole observation family, which carries neither.
    statuses = replay.events(run_id, statuses={"completed"}, limit=5_000)
    assert all(item.kind != "observation" for item in statuses.items)


def test_replay_indexes_do_not_cross_workspace_service_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workspace, run_id = _completed_workspace(root)
    first = ReplayService(workspace)
    first_index = first._index(run_id)

    reopened = ReplayService(WorkspaceService.open(root))
    second_index = reopened._index(run_id)

    assert first_index is not second_index
    assert first.frame(run_id, at=first_index.trace_start) == reopened.frame(
        run_id, at=second_index.trace_start
    )


def test_replay_uses_right_continuous_duplicate_waypoints() -> None:
    from smart_home_sim.application import replay as replay_module

    start = datetime(2026, 8, 23, 8, tzinfo=UTC)
    movement = MovementExecution.model_validate(
        {
            "movementId": "movement_duplicates",
            "actionExecutionId": "action_1",
            "actorId": "resident_1",
            "startedAt": start,
            "endedAt": start + timedelta(seconds=10),
            "originRegionId": "origin",
            "destinationRegionId": "destination",
            "distanceMeters": 10,
            "durationMicroseconds": 10_000_000,
            "waypoints": [
                {
                    "at": start,
                    "regionId": "origin",
                    "position": Point2D(x=0, y=0),
                    "traversalMode": "walking",
                },
                {
                    "at": start + timedelta(seconds=5),
                    "regionId": "first",
                    "position": Point2D(x=2, y=2),
                    "traversalMode": "walking",
                },
                {
                    "at": start + timedelta(seconds=5),
                    "regionId": "second",
                    "position": Point2D(x=4, y=4),
                    "traversalMode": "walking",
                },
                {
                    "at": start + timedelta(seconds=10),
                    "regionId": "destination",
                    "position": Point2D(x=10, y=10),
                    "traversalMode": "walking",
                },
            ],
        }
    )

    instant = start + timedelta(seconds=5)
    assert replay_module._point_at(movement, instant) == Point2D(x=4, y=4)
    assert replay_module._waypoint_at(movement, instant).region_id == "second"


def test_replay_frame_folds_resources_completed_intervals_and_sensor_change_boundaries(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    index = replay._index(run_id)
    movement = index.trace.movements[0]
    action = next(
        item
        for item in index.trace.action_executions
        if item.action_execution_id == movement.action_execution_id
    )
    activity = next(
        item
        for item in index.trace.activity_executions
        if item.activity_execution_id == action.activity_execution_id
    )
    movement_completed = replay.frame(run_id, at=movement.ended_at)
    resident = next(
        item for item in movement_completed.residents if item.resident_id == movement.actor_id
    )
    completed = replay.frame(run_id, at=max(action.ended_at, activity.actual_end))
    resource_event = index.trace.resource_events[0]
    resource_frame = replay.frame(run_id, at=resource_event.at)
    expected_resource = sorted(
        (
            item
            for item in index.trace.resource_events
            if item.resource_id == resource_event.resource_id and item.at <= resource_event.at
        ),
        key=lambda item: (item.at, item.resource_event_id),
    )[-1]
    observation = index.observations.records[0]
    exact_boundary = replay.frame(run_id, at=observation.observed_at + timedelta(milliseconds=500))
    at_observation = replay.frame(run_id, at=observation.observed_at)

    assert resident.position == movement.waypoints[-1].position
    assert movement.movement_id not in movement_completed.active_event_ids
    assert action.action_execution_id not in completed.active_event_ids
    assert activity.activity_execution_id not in completed.active_event_ids
    assert (
        resource_frame.resource_available_units[resource_event.resource_id]
        == expected_resource.available_units_after
    )
    exact_sensor = next(
        item for item in exact_boundary.sensor_states if item.sensor_id == observation.sensor_id
    )
    changed_sensor = next(
        item for item in at_observation.sensor_states if item.sensor_id == observation.sensor_id
    )
    assert not exact_sensor.changed
    assert changed_sensor.changed


def test_replay_clamps_event_limits_and_verifies_final_states(
    completed_workspace: tuple[WorkspaceService, str], tmp_path: Path
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    assert len(replay.events(run_id, limit=0).items) == 1
    assert len(replay.events(run_id, limit=10_000).items) == 5_000
    trace_end = replay._index(run_id).trace_end
    assert replay.frame(run_id, at=trace_end).at == trace_end

    no_bundle, no_bundle_run = _completed_workspace(tmp_path / "no-bundle")
    with no_bundle.transaction() as connection:
        connection.execute(
            "DELETE FROM artifacts WHERE run_id = ? AND role = 'simulation_bundle'",
            (no_bundle_run,),
        )
    horizon = ReplayService(no_bundle)
    with pytest.raises(WorkspaceError, match="final state"):
        horizon.frame(no_bundle_run, at=horizon._index(no_bundle_run).trace_end)


def test_replay_resident_special_transitions_fold_every_operation() -> None:
    from smart_home_sim.application import replay as replay_module

    at = datetime(2026, 8, 23, 8, tzinfo=UTC)

    def transition(fact: str, operation: str, value: object, offset: int) -> StateTransition:
        return StateTransition(
            transition_id=f"{fact}_{offset}",
            at=at + timedelta(seconds=offset),
            subject_type="resident",
            subject_id="resident_1",
            fact=fact,
            previous_value=None,
            value=value,
            operation=operation,
            causality=TraceCausality(cause_type="action_effect", cause_id="action_1"),
        )

    trace = SimpleNamespace(
        activity_executions=[],
        action_executions=[],
        movements=[],
        resource_events=[],
        state_transitions=[
            transition("location", "set", "kitchen", 0),
            transition("location", "increment", "hall", 1),
            transition("location", "remove", None, 2),
            transition("position", "set", {"x": 1, "y": 1}, 0),
            transition("position", "append", {"x": 2, "y": 2}, 1),
            transition("position", "remove", None, 2),
            transition("posture", "set", "sitting", 0),
            transition("posture", "decrement", "standing", 1),
            transition("posture", "invalidate", None, 2),
            transition("execution_state", "set", "moving", 0),
            transition("execution_state", "append", "performing_activity", 1),
            transition("execution_state", "invalidate", None, 2),
        ],
    )

    resident = replay_module._resident_frames(trace, None, at + timedelta(seconds=2))[0][0]

    assert resident.region_id is None
    assert resident.position is None
    assert resident.posture is None
    assert resident.execution_state == "unknown"


def test_replay_spatial_fold_keeps_later_transitions_over_completed_movement() -> None:
    from smart_home_sim.application import replay as replay_module

    start = datetime(2026, 8, 23, 8, tzinfo=UTC)
    movement = MovementExecution.model_validate(
        {
            "movementId": "movement_1",
            "actionExecutionId": "action_1",
            "actorId": "resident_1",
            "startedAt": start,
            "endedAt": start + timedelta(seconds=10),
            "originRegionId": "origin",
            "destinationRegionId": "movement_destination",
            "distanceMeters": 10,
            "durationMicroseconds": 10_000_000,
            "waypoints": [
                {
                    "at": start,
                    "regionId": "origin",
                    "position": Point2D(x=0, y=0),
                    "traversalMode": "walking",
                },
                {
                    "at": start + timedelta(seconds=10),
                    "regionId": "movement_destination",
                    "position": Point2D(x=10, y=10),
                    "traversalMode": "walking",
                },
            ],
        }
    )

    def transition(fact: str, value: object, at: datetime, identifier: str) -> StateTransition:
        return StateTransition(
            transition_id=identifier,
            at=at,
            subject_type="resident",
            subject_id="resident_1",
            fact=fact,
            previous_value=None,
            value=value,
            operation="set",
            causality=TraceCausality(cause_type="action_effect", cause_id="action_1"),
        )

    trace = SimpleNamespace(
        activity_executions=[],
        action_executions=[],
        movements=[movement],
        resource_events=[],
        state_transitions=[
            transition("location", "same_time", movement.ended_at, "location_same_time"),
            transition("position", {"x": 11, "y": 11}, movement.ended_at, "position_same_time"),
            transition("location", "later", start + timedelta(seconds=20), "location_later"),
            transition(
                "position", {"x": 20, "y": 20}, start + timedelta(seconds=20), "position_later"
            ),
        ],
    )

    same_time = replay_module._resident_frames(trace, None, movement.ended_at)[0][0]
    later = replay_module._resident_frames(trace, None, start + timedelta(seconds=21))[0][0]

    assert same_time.region_id == "same_time"
    assert same_time.position == Point2D(x=11, y=11)
    assert later.region_id == "later"
    assert later.position == Point2D(x=20, y=20)


def test_replay_resident_frame_exposes_activity_only_inside_its_half_open_interval() -> None:
    from smart_home_sim.application import replay as replay_module

    start = datetime(2026, 8, 23, 8, tzinfo=UTC)
    activity = ActivityExecution(
        activity_execution_id="activity_1",
        source_activity_id="breakfast",
        actor_id="resident_1",
        intent="Prepare breakfast",
        process_model_id="process_1",
        planned_start=start,
        planned_end=start + timedelta(minutes=30),
        actual_start=start,
        actual_end=start + timedelta(minutes=30),
        status="completed",
    )
    trace = SimpleNamespace(
        activity_executions=[activity],
        action_executions=[],
        movements=[],
        resource_events=[],
        state_transitions=[],
    )

    active = replay_module._resident_frames(trace, None, start)[0][0]
    ended = replay_module._resident_frames(trace, None, activity.actual_end)[0][0]

    assert active.activity_active is True
    assert active.activity_label == "Prepare breakfast"
    assert ended.activity_active is False
    assert ended.activity_label is None


def test_streaming_export_formats_manifest_and_integrity(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl, ExportFormat.csv, ExportFormat.xes],
            roles=["observable", "activities", "actions"],
        )
    )
    assert manifest.observable_oracle_separated is True
    assert len(manifest.files) == 9
    assert all(item.record_count > 0 for item in manifest.files)
    assert service.verify_manifest(manifest.export_id) == manifest
    observable_jsonl = next(
        item for item in manifest.files if item.role == "observable" and item.format == "jsonl"
    )
    first_record = json.loads(
        (workspace.exports_path / observable_jsonl.relative_path)
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    # `quality` belongs with them: a column stating which of its own readings the noise model
    # disturbed is an admission no real sensor log makes, and an evaluator reading it is being
    # handed part of the answer. It stays in the internal log; it does not ship.
    assert not (
        {"residentId", "activityExecutionId", "actionExecutionId", "quality"} & set(first_record)
    )
    assert {"sensorId", "observedAt", "measurement", "value"} <= set(first_record)

    corrupt = workspace.exports_path / manifest.files[0].relative_path
    corrupt.write_text("corrupt", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="integrity checks"):
        service.verify_manifest(manifest.export_id)


def test_xes_carries_a_day_per_trace_and_the_standard_extension_keys(tmp_path: Path) -> None:
    """The three keys a process miner reads, on a log cut into cases it can compare.

    Every one of these assertions stands for a way the export used to open in ProM without
    complaint and teach an algorithm nothing: one trace for the whole run, the timestamp filed
    under `observedAt` where nothing looks for it, no lifecycle to pair a start with its
    completion, and every sensor firing named after its `measurement` so that 72k PIR events
    arrived as one indistinguishable activity.
    """
    observable = [
        {"observationId": "o1", "sensorId": "pir_kitchen", "measurement": "motion", "value": 1.0},
        {"observationId": "o2", "sensorId": "pir_bedroom", "measurement": "motion", "value": 1.0},
        {"observationId": "o3", "sensorId": "pir_kitchen", "measurement": "motion", "value": 1.0},
    ]
    # Deliberately out of order inside the day: the second reading closes after the third opens.
    for record, stamp in zip(
        observable,
        ("2026-07-24T23:59:00+02:00", "2026-07-25T08:00:00+02:00", "2026-07-25T07:00:00+02:00"),
        strict=True,
    ):
        record["observedAt"] = stamp

    path = tmp_path / "observable.xes"
    assert _xes(path, "observable", observable, "job_1") == 3
    log = ElementTree.parse(path).getroot()
    namespace = "{http://www.xes-standard.org/}"

    assert [item.get("prefix") for item in log.findall(f"{namespace}extension")] == [
        "concept",
        "time",
        "lifecycle",
        "org",
    ]
    assert len(log.findall(f"{namespace}classifier")) == 2
    traces = log.findall(f"{namespace}trace")
    assert [
        trace.find(f"{namespace}string[@key='concept:name']").get("value") for trace in traces
    ] == ["2026-07-24", "2026-07-25"]
    second = traces[1].findall(f"{namespace}event")
    assert [
        event.find(f"{namespace}date[@key='time:timestamp']").get("value") for event in second
    ] == ["2026-07-25T07:00:00+02:00", "2026-07-25T08:00:00+02:00"]
    assert [
        event.find(f"{namespace}string[@key='concept:name']").get("value") for event in second
    ] == ["pir_kitchen", "pir_bedroom"]
    assert all(
        event.find(f"{namespace}string[@key='lifecycle:transition']").get("value") == "complete"
        for event in second
    )
    # The observable half stays blind: naming the resident here would hand over the oracle.
    assert second[0].find(f"{namespace}string[@key='org:resource']") is None

    # An interval record becomes the standard start/complete pair, counted once.
    activity = {
        "activityExecutionId": "a1",
        "intent": "eat_breakfast",
        "actorId": "francesca_verdi",
        "actualStart": "2026-07-24T08:00:00+02:00",
        "actualEnd": "2026-07-24T08:20:00+02:00",
    }
    paired = tmp_path / "activities.xes"
    assert _xes(paired, "activities", [activity], "job_1") == 1
    events = ElementTree.parse(paired).getroot().findall(f".//{namespace}event")
    assert [
        event.find(f"{namespace}string[@key='lifecycle:transition']").get("value")
        for event in events
    ] == ["start", "complete"]
    assert {
        event.find(f"{namespace}string[@key='concept:instance']").get("value") for event in events
    } == {"a1"}
    assert (
        events[0].find(f"{namespace}string[@key='org:resource']").get("value") == "francesca_verdi"
    )


def test_xes_falls_back_for_undated_roles_and_rejects_disordered_sources(tmp_path: Path) -> None:
    # `oracle` is a join table keyed by observation, not a log: no timestamp, so no day to cut.
    links = [{"observationId": "o1", "causeType": "trace"}, {"observationId": "o2"}]
    undated = tmp_path / "oracle.xes"
    assert _xes(undated, "oracle", links, "job_1") == 2
    namespace = "{http://www.xes-standard.org/}"
    log = ElementTree.parse(undated).getroot()
    trace = log.find(f"{namespace}trace")
    assert len(log.findall(f"{namespace}trace")) == 1
    # The `<global>` block still declares the key; no event carries a value for it.
    assert trace.find(f".//{namespace}date[@key='time:timestamp']") is None

    assert _xes(tmp_path / "empty.xes", "observable", [], "job_1") == 0

    mixed = [
        {"sensorId": "pir_kitchen", "observedAt": "2026-07-24T08:00:00+02:00"},
        {"sensorId": "pir_bedroom"},
    ]
    with pytest.raises(WorkspaceError, match="with and without a timestamp"):
        _xes(tmp_path / "mixed.xes", "observable", mixed, "job_1")

    revisited = [
        {"sensorId": "a", "observedAt": "2026-07-24T08:00:00+02:00"},
        {"sensorId": "b", "observedAt": "2026-07-25T08:00:00+02:00"},
        {"sensorId": "c", "observedAt": "2026-07-24T09:00:00+02:00"},
    ]
    with pytest.raises(WorkspaceError, match="not in chronological order"):
        _xes(tmp_path / "disordered.xes", "observable", revisited, "job_1")


def test_replay_requires_complete_run_artifacts(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Incomplete")
    replay = ReplayService(workspace)
    with pytest.raises(WorkspaceError, match="unknown run 'missing'"):
        replay.diary("missing")


def test_export_streaming_helpers_cover_filters_and_malformed_sources(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"records":[1]}', encoding="utf-8")
    with pytest.raises(WorkspaceError, match="not a record sequence"):
        list(_items(malformed, "records.item"))

    request = ExportRequest(
        run_id="run",
        formats=[ExportFormat.csv],
        roles=["observable"],
        include_start=datetime(2026, 7, 22, 9, tzinfo=UTC),
        include_end=datetime(2026, 7, 22, 10, tzinfo=UTC),
    )
    records = [
        {"observedAt": "2026-07-22T08:00:00+00:00", "value": 1},
        {"observedAt": "2026-07-22T09:30:00+00:00", "value": 2},
        {"observedAt": "2026-07-22T11:00:00+00:00", "value": 3},
    ]
    assert list(_filtered(records, request)) == [records[1]]
    assert _record_time({"value": 1}) is None
    assert _csv(tmp_path / "empty.csv", []) == 0
    with pytest.raises(WorkspaceError, match="stable field set"):
        _csv(tmp_path / "unstable.csv", [{"a": 1}, {"b": 2}])

    target = StringIO()
    xml = XMLGenerator(target, encoding="utf-8")
    _xes_attribute(xml, "enabled", True)
    assert 'value="true"' in target.getvalue()


def test_export_rejects_incomplete_provenance_and_missing_role(tmp_path: Path) -> None:
    workspace = WorkspaceService.create(tmp_path / "workspace", "Export guards")
    service = ExportService(workspace)
    request = lambda run_id: ExportRequest(  # noqa: E731
        run_id=run_id,
        formats=[ExportFormat.jsonl],
        roles=["observable"],
    )

    with pytest.raises(WorkspaceError, match="requires bundle"):
        service.export(request("missing"))

    def register_run(run_id: str, trace: dict[str, object]) -> None:
        directory = workspace.runs_path / run_id
        directory.mkdir()
        bundle = directory / "simulation-bundle.json"
        bundle.write_text("{}", encoding="utf-8")
        trace_path = directory / "execution-trace.json"
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        workspace.register_artifact(bundle, role="simulation_bundle", run_id=run_id)
        workspace.register_artifact(trace_path, role="execution_trace", run_id=run_id)

    register_run("no-provenance", {})
    with pytest.raises(WorkspaceError, match="provenance is incomplete"):
        service.export(request("no-provenance"))

    register_run(
        "no-seed",
        {"sourceBundleSha256": "a" * 64, "semanticDigest": "b" * 64},
    )
    with pytest.raises(WorkspaceError, match="seed is invalid"):
        service.export(request("no-seed"))

    register_run(
        "no-observations",
        {"sourceBundleSha256": "a" * 64, "semanticDigest": "b" * 64, "seed": 7},
    )
    with pytest.raises(WorkspaceError, match="has no artifact"):
        service.export(request("no-observations"))
    assert not list(workspace.exports_path.glob(".export_*"))


def test_export_manifest_rejects_missing_and_unsafe_paths(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    with pytest.raises(WorkspaceError, match="escapes"):
        service.verify_manifest("../outside")
    with pytest.raises(WorkspaceError, match="cannot read"):
        service.verify_manifest("missing")

    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["observable"],
        )
    )
    path = workspace.exports_path / manifest.export_id / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["files"][0]["relativePath"] = "../outside.jsonl"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkspaceError, match="unsafe path"):
        service.verify_manifest(manifest.export_id)


def test_export_creates_missing_exports_directory(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    if workspace.exports_path.exists():
        shutil.rmtree(workspace.exports_path)
    assert not workspace.exports_path.exists()

    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["observable"],
        )
    )
    assert workspace.exports_path.exists()
    assert (workspace.exports_path / manifest.export_id / "manifest.json").is_file()


def test_archive_export_creates_valid_zip(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["observable"],
        )
    )
    zip_path = service.archive_export(manifest.export_id)
    assert zip_path.is_file()
    assert zip_path.name == f"{manifest.export_id}.zip"
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        assert f"{manifest.export_id}/manifest.json" in names
        assert f"{manifest.export_id}/observable.jsonl" in names
    relative = f"exports/{manifest.export_id}.zip"
    with workspace.connection() as connection:
        row = connection.execute(
            "SELECT * FROM artifacts WHERE relative_path = ?", (relative,)
        ).fetchone()
    assert row is not None
    assert row["role"] == "export_archive"


def test_repair_auto_registers_orphan_export_zips(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["observable"],
        )
    )
    service.archive_export(manifest.export_id)
    relative = f"exports/{manifest.export_id}.zip"
    # Unregister zip artifact manually to simulate an uncatalogued/orphan export archive
    with workspace.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE relative_path = ?", (relative,))
    assert any(f"orphan file: {relative}" in issue for issue in workspace.reconcile())
    # Repair — which every open runs — adopts the archive rather than reporting it forever.
    assert workspace.repair().artifacts_adopted == 1
    reconciled_issues = [
        issue for issue in workspace.reconcile() if f"orphan file: {relative}" in issue
    ]
    assert reconciled_issues == []
    with workspace.connection() as connection:
        row = connection.execute(
            "SELECT * FROM artifacts WHERE relative_path = ?", (relative,)
        ).fetchone()
    assert row is not None
    assert row["role"] == "export_archive"


def test_the_export_offers_every_role_the_backend_defines() -> None:
    """A role the UI never asks for is a dataset column nobody receives.

    `habit_ground_truth` was added for outline-first horizons, and the value of adding it is
    entirely in it reaching the researcher who downloads the export — so the button must request
    it. Comparing the two lists is what stops one from quietly falling behind the other.
    """
    import re

    from smart_home_sim.application.export import PROFILE_ROLE, ROLE_SOURCES, SUMMARY_ROLE

    source = (PROJECT_ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    match = re.search(r"roles: \[([^\]]+)\]", source)
    assert match is not None, "the export button no longer names its roles"
    requested = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    offered = set(ROLE_SOURCES) | {PROFILE_ROLE, SUMMARY_ROLE}

    assert requested == offered, {
        "missing from the UI": sorted(offered - requested),
        "unknown to the backend": sorted(requested - offered),
    }


def test_an_identical_export_is_reused_rather_than_written_again(tmp_path: Path) -> None:
    """Exporting is deterministic, so a second identical request needs no second copy.

    Each click on the download button was writing another full dataset: one workspace that had
    exported eleven times held 4.5 GB, of which roughly four were duplicates of the same run.
    """
    workspace, run_id = _completed_workspace(tmp_path / "workspace")
    service = ExportService(workspace)
    request = ExportRequest(
        run_id=run_id, formats=[ExportFormat.jsonl], roles=["observable", "activities"]
    )

    first = service.export(request)
    again = service.export(request)

    assert again.export_id == first.export_id
    assert len(list(workspace.exports_path.glob("export_*"))) == 1

    # A different request is a different dataset and still gets its own directory.
    other = service.export(
        ExportRequest(run_id=run_id, formats=[ExportFormat.csv], roles=["observable"])
    )
    assert other.export_id != first.export_id

    # And deleting the files is how the space is reclaimed: the next export rebuilds them.
    shutil.rmtree(workspace.exports_path / first.export_id)
    rebuilt = service.export(request)
    assert rebuilt.export_id != first.export_id
    assert (workspace.exports_path / rebuilt.export_id / "manifest.json").is_file()


def test_export_publishes_the_resident_profile_as_document_page_and_matrix(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)

    manifest = service.export(
        ExportRequest(run_id=run_id, formats=[ExportFormat.jsonl], roles=["resident_profile"])
    )

    assert {item.format for item in manifest.files} == {
        ExportFormat.json,
        ExportFormat.html,
        ExportFormat.csv,
    }
    # The requested format applies to record roles only: a profile is published in the shapes it
    # has, whatever a caller asked for the rest of the dataset.
    assert {item.role for item in manifest.files} == {"resident_profile"}
    assert service.verify_manifest(manifest.export_id) == manifest
    document = next(item for item in manifest.files if item.format == ExportFormat.json)
    payload = json.loads(
        (workspace.exports_path / document.relative_path).read_text(encoding="utf-8")
    )
    assert payload["documentType"] == "resident_profile"
    assert payload["runId"] == run_id
    assert payload["residents"][0]["narrative"]
    page = next(item for item in manifest.files if item.format == ExportFormat.html)
    assert (
        (workspace.exports_path / page.relative_path)
        .read_text(encoding="utf-8")
        .startswith("<!doctype html>")
    )


def test_export_publishes_one_summary_page_that_indexes_the_dataset(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)

    manifest = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["summary", "observable", "activities"],
        )
    )

    summary = next(item for item in manifest.files if item.role == "summary")
    assert summary.format is ExportFormat.html
    assert service.verify_manifest(manifest.export_id) == manifest
    page = (workspace.exports_path / summary.relative_path).read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    # The home model and the sensor field reach a reader for the first time here: no other role
    # publishes them, so without this page the log names sensors that are nowhere to be found.
    assert "The home" in page and 'class="plan"' in page
    assert "pir_kitchen" in page
    # And the page indexes the rest of the export, which is why it is written last whatever order
    # the roles were requested in.
    assert "observable.jsonl" in page and "activities.jsonl" in page


def test_a_rebuilt_summary_is_the_same_page(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    """The export promises that deleting a dataset costs nothing but the time to rebuild it."""
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    request = ExportRequest(run_id=run_id, formats=[ExportFormat.csv], roles=["summary"])
    first = service.export(request)

    shutil.rmtree(workspace.exports_path / first.export_id)
    rebuilt = service.export(request)

    assert rebuilt.export_id != first.export_id
    assert [item.sha256 for item in rebuilt.files] == [item.sha256 for item in first.files]


def test_a_windowed_export_profiles_only_the_window(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    service = ExportService(workspace)
    whole = service.export(
        ExportRequest(run_id=run_id, formats=[ExportFormat.jsonl], roles=["resident_profile"])
    )
    trace = json.loads(
        workspace.artifact_path(
            workspace.run_artifacts(run_id)["execution_trace"].artifact_id
        ).read_text(encoding="utf-8")
    )
    opened = datetime.fromisoformat(trace["startedAt"])

    windowed = service.export(
        ExportRequest(
            run_id=run_id,
            formats=[ExportFormat.jsonl],
            roles=["resident_profile"],
            include_start=opened,
            include_end=opened + timedelta(days=1),
        )
    )

    def day_count(manifest: ExportManifest) -> int:
        document = next(item for item in manifest.files if item.format == ExportFormat.json)
        return json.loads(
            (workspace.exports_path / document.relative_path).read_text(encoding="utf-8")
        )["dayCount"]

    assert day_count(windowed) < day_count(whole)


def test_only_record_formats_can_be_requested() -> None:
    with pytest.raises(ValidationError, match="only jsonl, csv and xes"):
        ExportRequest(run_id="run", formats=[ExportFormat.html], roles=["observable"])
