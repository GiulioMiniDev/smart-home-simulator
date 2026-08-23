# Dual-mode Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed-interval movement slideshow with a digest-verified, timestamp-correct replay that offers synchronized Presentation and Analysis modes.

**Architecture:** `ReplayService` builds a digest-keyed temporal index over immutable run artifacts and exposes bounded event windows plus deterministic frames. A frontend replay controller owns one simulation clock and persists its state; presentation and analysis components are projections of that controller. `PlanCanvas` remains the authoritative spatial renderer and receives typed replay overlays rather than replaying the simulation itself.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, pytest, React 19, TypeScript 5.8, SVG, Vitest, Testing Library, Playwright, axe-core.

## Global Constraints

- Preserve the execution trace, observable log, oracle mapping, home model, and simulation bundle as immutable sources of truth.
- Verify the semantic digest before enabling playback; never present a mismatched run as replayable.
- Observable responses must never contain resident, activity, or action identity unless `includeOracle=true` is explicit.
- Keep event-window responses bounded to at most 5,000 records and never fetch a whole yearly timeline in the browser.
- Reuse the existing `PlanCanvas`, product tokens, Source Sans 3 typography, controls, focus treatment, light theme, and dark theme.
- Use indigo for computed routes and temporal selection, teal for physical resources, and amber for obstacles and warnings.
- Support WCAG 2.2 AA, complete keyboard operation, non-color identity cues, and `prefers-reduced-motion`.
- Do not add runtime dependencies unless the existing platform cannot implement the required behavior.
- Follow test-driven development and commit after every task.

---

## File map

- `src/smart_home_sim/domain/application.py`: typed replay event, frame, filter, and session response contracts.
- `src/smart_home_sim/application/replay.py`: digest-keyed index, window queries, interpolation, state reconstruction, and verification.
- `src/smart_home_sim/web/app.py`: replay HTTP query and persistence endpoints.
- `tests/test_application_replay_export.py`: service-level replay correctness and Observable/Oracle isolation.
- `tests/test_web_application.py`: HTTP validation, response shape, bounds, and persistence.
- `schemas/application-replay-1.1.0.schema.json`: new composite application replay contract; the
  frozen verification-only 1.0.0 schema remains published.
- `schemas/application-replay-1.1.0.schema.sha256`: new contract checksum.
- `frontend/src/types.ts`: TypeScript mirror of replay contracts and spatial overlay types.
- `frontend/src/replay/replay-clock.ts`: pure clock, interpolation, range, and event-clustering functions.
- `frontend/src/replay/useReplayController.ts`: verification, window/frame loading, playback, selection, and session persistence.
- `frontend/src/replay/ReplayWorkbench.tsx`: shared composition and mode switch.
- `frontend/src/replay/ReplayToolbar.tsx`: transport, speed, mode, and visibility controls.
- `frontend/src/replay/ReplayStage.tsx`: adapter from replay frames to `PlanCanvas` and its structured alternative.
- `frontend/src/replay/ReplayTimeline.tsx`: bounded multitrack analysis timeline.
- `frontend/src/replay/ReplayInspector.tsx`: selected evidence and current-state details.
- `frontend/src/replay/replay.css`: replay-only layout and state styling built from existing tokens.
- `frontend/src/components.tsx`: typed resident, region, trajectory, and sensor overlays in `PlanCanvas`.
- `frontend/src/App.tsx`: replace the legacy replay JSX and fixed 650 ms interval with `ReplayWorkbench`.
- `frontend/src/main.tsx`: import replay styles.
- `frontend/src/test/replay-clock.test.ts`: pure temporal behavior.
- `frontend/src/test/useReplayController.test.tsx`: controller integration with fake time and mocked HTTP.
- `frontend/src/test/ReplayWorkbench.test.tsx`: mode, analysis, presentation, accessibility, and failure states.
- `frontend/src/test/components.test.tsx`: plan overlay rendering and keyboard alternatives.
- `frontend/e2e/replay.spec.ts`: real-backend replay journey.
- `tools/build_replay_e2e_workspace.py`: deterministic completed workspace for Playwright.
- `frontend/playwright.config.ts`: build the replay fixture before launching the real backend.
- `README.md`: document dual-mode replay controls and evidence guarantees.

---

### Task 1: Freeze replay query and frame contracts

**Files:**
- Modify: `src/smart_home_sim/domain/application.py`
- Modify: `tests/test_json_schema.py`
- Modify: `src/smart_home_sim/cli.py`
- Create: `schemas/application-replay-1.1.0.schema.json`
- Create: `schemas/application-replay-1.1.0.schema.sha256`

**Interfaces:**
- Consumes: `ObservationCause`, `Point2D`, `JsonValue`, and `ContractModel`.
- Produces: `ReplayEventView`, `ReplayEventWindow`, `ReplayResidentFrame`, `ReplaySensorFrame`, `ReplayFrame`, `ReplayFilters`, and `ReplaySessionState`.

- [ ] **Step 1: Write failing contract and schema tests**

Add imports and assertions to `tests/test_json_schema.py`:

```python
from smart_home_sim.domain.application import (
    ReplayEventWindow,
    ReplayFilters,
    ReplayFrame,
    ReplaySessionState,
)


def test_application_replay_contract_covers_windows_frames_and_sessions() -> None:
    schema = ReplayFrame.model_json_schema(by_alias=True)
    assert {"runId", "at", "traceStart", "traceEnd", "residents", "sensorStates"} <= set(
        schema["required"]
    )
    assert ReplayEventWindow.model_fields["items"].annotation is not None
    filters = ReplayFilters.model_validate(
        {
            "eventKinds": ["movement", "observation"],
            "detailMode": "analysis",
            "visibilityMode": "observable",
            "speed": 4,
        }
    )
    session = ReplaySessionState(
        runId="run_1",
        verifiedDigest="a" * 64,
        positionAt="2026-08-23T08:00:00+00:00",
        filters=filters,
    )
    assert session.filters.speed == 4
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'; uv run pytest tests/test_json_schema.py::test_application_replay_contract_covers_windows_frames_and_sessions -q
```

Expected: collection fails because the replay models do not exist.

- [ ] **Step 3: Add the application replay models**

Add these contracts to `src/smart_home_sim/domain/application.py`, importing `Literal` and
`Point2D` as required:

```python
ReplayEventKind = Literal[
    "activity",
    "action",
    "movement",
    "observation",
    "state_transition",
    "resource",
    "runtime_event",
    "plan_deviation",
]
ReplayDetailMode = Literal["presentation", "analysis"]
ReplayVisibilityMode = Literal["observable", "oracle"]


class ReplayWaypoint(ContractModel):
    at: AwareDatetime
    region_id: str = Field(min_length=1)
    position: Point2D
    traversal_mode: str = Field(min_length=1)


class ReplayEventView(ContractModel):
    at: AwareDatetime
    end: AwareDatetime | None = None
    kind: ReplayEventKind
    event_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: str | None = None
    actor_id: str | None = None
    sensor_id: str | None = None
    waypoints: list[ReplayWaypoint] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ReplayEventWindow(ContractModel):
    items: list[ReplayEventView]
    total: int = Field(ge=0)
    trace_start: AwareDatetime
    trace_end: AwareDatetime
    window_start: AwareDatetime
    window_end: AwareDatetime


class ReplayResidentFrame(ContractModel):
    resident_id: str = Field(min_length=1)
    region_id: str | None = None
    position: Point2D | None = None
    posture: str | None = None
    execution_state: str = Field(min_length=1)
    activity_execution_id: str | None = None
    action_execution_id: str | None = None
    held_resource_ids: list[str] = Field(default_factory=list)
    facts: dict[str, JsonValue] = Field(default_factory=dict)


class ReplaySensorFrame(ContractModel):
    observation_id: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    sensor_type: str = Field(min_length=1)
    observed_at: AwareDatetime
    measurement: str = Field(min_length=1)
    value: JsonValue
    unit: str | None = None
    quality: str = Field(min_length=1)
    changed: bool = False
    oracle_cause: ObservationCause | None = None


class ReplayFrame(ContractModel):
    run_id: str = Field(min_length=1)
    at: AwareDatetime
    trace_start: AwareDatetime
    trace_end: AwareDatetime
    residents: list[ReplayResidentFrame]
    sensor_states: list[ReplaySensorFrame]
    entity_states: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    environment_facts: dict[str, JsonValue] = Field(default_factory=dict)
    resource_available_units: dict[str, int] = Field(default_factory=dict)
    active_event_ids: list[str] = Field(default_factory=list)


class ReplayFilters(ContractModel):
    event_kinds: list[ReplayEventKind] = Field(default_factory=list)
    actor_ids: list[str] = Field(default_factory=list)
    sensor_ids: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    detail_mode: ReplayDetailMode = "presentation"
    visibility_mode: ReplayVisibilityMode = "observable"
    speed: float = Field(default=1, ge=0.25, le=32)
    selected_resident_id: str | None = None


class ReplaySessionState(ContractModel):
    replay_id: str | None = None
    run_id: str = Field(min_length=1)
    verified_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    position_at: AwareDatetime | None = None
    filters: ReplayFilters = Field(default_factory=ReplayFilters)
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class ApplicationReplayContract(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:application-replay:1.1.0",
            "title": "Smart Home Application Replay 1.1.0",
        },
    )

    verification: ReplayVerification
    event_window: ReplayEventWindow
    frame: ReplayFrame
    session: ReplaySessionState
```

Change the `application-replay` schema CLI mapping from `ReplayVerification` to
`ApplicationReplayContract`. Add `application-replay-1.1.0.schema.json` to `APPLICATION_SCHEMAS` in
`tests/test_json_schema.py`, leave `application-replay-1.0.0.schema.json` mapped to
`ReplayVerification` as a historical schema, then generate the new schema and checksum using the
existing schema command and checksum convention:

```powershell
$env:PYTHONPATH='src'; uv run smart-home-sim schema --contract application-replay --output schemas/application-replay-1.1.0.schema.json
```

- [ ] **Step 4: Run contract tests and schema checksum validation**

Run:

```powershell
$env:PYTHONPATH='src'; uv run pytest tests/test_json_schema.py -q
```

Expected: all schema tests pass and the regenerated checksum matches the schema contents.

- [ ] **Step 5: Commit the frozen contracts**

```powershell
git add src/smart_home_sim/domain/application.py src/smart_home_sim/cli.py tests/test_json_schema.py schemas/application-replay-1.1.0.schema.json schemas/application-replay-1.1.0.schema.sha256
git commit -m "feat: freeze temporal replay contracts"
```

---

### Task 2: Build a deterministic replay index and frame service

**Files:**
- Modify: `src/smart_home_sim/application/replay.py`
- Modify: `tests/test_application_replay_export.py`

**Interfaces:**
- Consumes: Task 1 replay contracts and immutable `ExecutionTrace`, `SimulationBundle`, `ObservableSensorLog`, and `OracleMapping` artifacts.
- Produces: `ReplayService.events() -> ReplayEventWindow` and `ReplayService.frame() -> ReplayFrame`.

- [ ] **Step 1: Write failing service tests for all event families, bounded windows, and seeks**

Add these tests to `tests/test_application_replay_export.py`:

```python
def test_replay_indexes_every_trace_family_and_bounds_windows(
    completed_workspace: tuple[WorkspaceService, str],
) -> None:
    workspace, run_id = completed_workspace
    replay = ReplayService(workspace)
    trace = json.loads(workspace.read_artifact(workspace.run_artifacts(run_id)["execution_trace"].artifact_id))
    start = datetime.fromisoformat(trace["startedAt"])
    end = start + timedelta(hours=12)
    window = replay.events(run_id, start=start, end=end, limit=37)
    assert len(window.items) <= 37
    assert window.window_start == start
    assert window.window_end == end
    assert {item.kind for item in replay.events(run_id, start=start, end=end, limit=5000).items} >= {
        "activity", "action", "movement", "state_transition", "resource", "runtime_event"
    }


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
```

Add a focused interpolation test using a two-waypoint movement where the requested instant is
exactly halfway and assert the returned position is the arithmetic midpoint.

- [ ] **Step 2: Run the service tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='src'; uv run pytest tests/test_application_replay_export.py -k "replay_indexes or random_seek or interpolation" -q
```

Expected: failures report missing `events` and `frame` methods.

- [ ] **Step 3: Implement digest-keyed indexing and timestamp interpolation**

In `src/smart_home_sim/application/replay.py`, add immutable indexes and bisect-based selection:

```python
@dataclass(frozen=True)
class _ReplayIndex:
    trace_start: datetime
    trace_end: datetime
    events: tuple[ReplayEventView, ...]
    event_times: tuple[datetime, ...]
    trace: ExecutionTrace
    observations: ObservableSensorLog
    oracle: OracleMapping | None


def _point_at(movement: MovementExecution, at: datetime) -> Point2D:
    waypoints = movement.waypoints
    if at <= waypoints[0].at:
        return waypoints[0].position
    if at >= waypoints[-1].at:
        return waypoints[-1].position
    times = [item.at for item in waypoints]
    right = bisect_right(times, at)
    left_item, right_item = waypoints[right - 1], waypoints[right]
    span = (right_item.at - left_item.at).total_seconds()
    ratio = 0.0 if span == 0 else (at - left_item.at).total_seconds() / span
    return Point2D(
        x=left_item.position.x + (right_item.position.x - left_item.position.x) * ratio,
        y=left_item.position.y + (right_item.position.y - left_item.position.y) * ratio,
    )


def _apply_transition(target: dict[str, JsonValue], transition: StateTransition) -> None:
    if transition.operation in {"set", "increment", "decrement", "append"}:
        target[transition.fact] = transition.value
    elif transition.operation == "remove":
        target.pop(transition.fact, None)
    else:
        target[transition.fact] = None
```

Build `_ReplayIndex.events` from all trace families plus observations. Put only device fields in
observation `details`; attach `ObservationCause` only inside `frame` or `events` when
`include_oracle=True`. Sort by `(at, kind, event_id)` and use `bisect_left`/`bisect_right` for
window queries. Enforce `limit = max(1, min(limit, 5_000))`. Use each record's authoritative time;
because `PlanDeviation` has no timestamp of its own, place it at its owning activity's
`actual_start` and include that activity execution ID in `details`. Use `final_state` only to verify
the reconstructed frame at `trace_end`; do not create a synthetic timeline event for it.

Implement the public signatures exactly:

```python
def events(
    self,
    run_id: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    kinds: set[ReplayEventKind] | None = None,
    actor_id: str | None = None,
    sensor_id: str | None = None,
    include_oracle: bool = False,
    limit: int = 2_000,
) -> ReplayEventWindow:
    index = self._index(run_id)
    window_start = max(start or index.trace_start, index.trace_start)
    window_end = min(end or index.trace_end, index.trace_end)
    left = bisect_left(index.event_times, window_start)
    right = bisect_right(index.event_times, window_end)
    selected = [
        item
        for item in index.events[left:right]
        if (kinds is None or item.kind in kinds)
        and (actor_id is None or item.actor_id == actor_id)
        and (sensor_id is None or item.sensor_id == sensor_id)
    ]
    if not include_oracle:
        selected = [_without_oracle(item) for item in selected]
    bounded = max(1, min(limit, 5_000))
    return ReplayEventWindow(
        items=selected[:bounded],
        total=len(selected),
        traceStart=index.trace_start,
        traceEnd=index.trace_end,
        windowStart=window_start,
        windowEnd=window_end,
    )

def frame(
    self,
    run_id: str,
    *,
    at: datetime,
    include_oracle: bool = False,
) -> ReplayFrame:
    index = self._index(run_id)
    instant = min(max(at, index.trace_start), index.trace_end)
    residents, active_ids = _resident_frames(index.trace, instant)
    entity_states, environment_facts = _world_state_at(index.trace, instant)
    resources = _resource_state_at(index.trace, instant)
    sensors = _sensor_state_at(index.observations, index.oracle, instant, include_oracle)
    return ReplayFrame(
        runId=run_id,
        at=instant,
        traceStart=index.trace_start,
        traceEnd=index.trace_end,
        residents=residents,
        sensorStates=sensors,
        entityStates=entity_states,
        environmentFacts=environment_facts,
        resourceAvailableUnits=resources,
        activeEventIds=active_ids,
    )
```

Implement `_without_oracle`, `_resident_frames`, `_world_state_at`, `_resource_state_at`, and
`_sensor_state_at` in the same module. Each helper takes only immutable trace/index data and the
requested instant. Seed initial resident and entity state from the simulation bundle where
present; otherwise use the first transition's `previousValue` and return `None` for absent spatial
fields. Fold transitions and resource events through `at`, find interval-containing activities and
actions, interpolate active movements, retain the last authoritative waypoint for completed
movements, and take the last observation per sensor at or before `at`. Set `changed=True` only
when that observation lies in `(at - 500 ms, at]`.

- [ ] **Step 4: Run replay service tests and the existing export suite**

Run:

```powershell
$env:PYTHONPATH='src'; uv run pytest tests/test_application_replay_export.py tests/test_simulation.py -q
```

Expected: all tests pass; existing deterministic M5 replay behavior remains unchanged.

- [ ] **Step 5: Commit the replay index**

```powershell
git add src/smart_home_sim/application/replay.py tests/test_application_replay_export.py
git commit -m "feat: index deterministic replay frames"
```

---

### Task 3: Expose bounded replay APIs and typed session persistence

**Files:**
- Modify: `src/smart_home_sim/web/app.py`
- Modify: `src/smart_home_sim/application/workspace.py`
- Modify: `tests/test_web_application.py`
- Modify: `tests/test_application_workspace.py`

**Interfaces:**
- Consumes: `ReplayService.events`, `ReplayService.frame`, `ReplayFilters`, and `ReplaySessionState`.
- Produces: `GET /api/runs/{run_id}/replay/events`, `GET /api/runs/{run_id}/replay/frame`, typed replay session GET/PUT, and backward-compatible `/timeline`.

- [ ] **Step 1: Write failing HTTP and persistence tests**

Extend `tests/test_web_application.py`:

```python
events = client.get(
    f"/api/runs/{job.job_id}/replay/events",
    params={"limit": 25, "kinds": "movement,observation", "include_oracle": "false"},
    headers=headers,
)
assert events.status_code == 200
assert len(events.json()["items"]) <= 25
assert {item["kind"] for item in events.json()["items"]} <= {"movement", "observation"}

target = events.json()["items"][0]["at"]
frame = client.get(
    f"/api/runs/{job.job_id}/replay/frame",
    params={"at": target, "include_oracle": "false"},
    headers=headers,
)
assert frame.status_code == 200
assert all(item.get("oracleCause") is None for item in frame.json()["sensorStates"])

saved = client.put(
    f"/api/runs/{job.job_id}/replay/session",
    json={
        "positionAt": target,
        "filters": {
            "eventKinds": ["movement"],
            "detailMode": "analysis",
            "visibilityMode": "observable",
            "speed": 8,
        },
    },
    headers=headers,
)
assert saved.json()["filters"]["speed"] == 8
```

Add 422 assertions for `limit=5001`, `speed=64`, an inverted time window, and an unknown event
kind. Extend the workspace test to prove a saved session whose digest differs from the current
trace is returned with `positionAt=None` and default filters.

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='src'; uv run pytest tests/test_web_application.py::test_run_replay_export_sse_and_file_endpoints tests/test_application_workspace.py -k replay -q
```

Expected: new endpoint assertions fail with 404 or validation errors.

- [ ] **Step 3: Add validated endpoints and digest-aware persistence**

Replace the loose session update model in `src/smart_home_sim/web/app.py`:

```python
class ReplaySessionUpdate(ApiModel):
    position_at: Annotated[AwareDatetime, Field(strict=False)] | None = None
    filters: ReplayFilters = Field(default_factory=ReplayFilters)
```

Add endpoint functions with FastAPI validation:

```python
@app.get("/api/runs/{run_id}/replay/events", dependencies=[secured])
def replay_events(
    run_id: str,
    start: Annotated[AwareDatetime | None, Query(strict=False)] = None,
    end: Annotated[AwareDatetime | None, Query(strict=False)] = None,
    kinds: str = "",
    actor_id: str | None = None,
    sensor_id: str | None = None,
    include_oracle: bool = False,
    limit: int = Query(default=2_000, ge=1, le=5_000),
) -> dict[str, Any]:
    selected = {item for item in kinds.split(",") if item}
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail={"code": "INVALID_REPLAY_WINDOW", "message": "Replay window start must not follow its end."})
    return replay.events(
        run_id,
        start=start,
        end=end,
        kinds=cast(set[ReplayEventKind], selected) or None,
        actor_id=actor_id,
        sensor_id=sensor_id,
        include_oracle=include_oracle,
        limit=limit,
    ).model_dump(mode="json", by_alias=True)


@app.get("/api/runs/{run_id}/replay/frame", dependencies=[secured])
def replay_frame(
    run_id: str,
    at: Annotated[AwareDatetime, Query(strict=False)],
    include_oracle: bool = False,
) -> dict[str, Any]:
    return replay.frame(run_id, at=at, include_oracle=include_oracle).model_dump(
        mode="json", by_alias=True
    )
```

Validate `kinds` against `typing.get_args(ReplayEventKind)` before the cast. Keep `/timeline` as a
deprecated adapter returning only activity, action, and movement events until frontend migration is
complete. Make `WorkspaceService.replay_session` return `ReplaySessionState`; compare its stored
verified digest to the execution trace semantic digest and reset stale position and filters without
deleting the audit row.

- [ ] **Step 4: Run application service and HTTP tests**

Run:

```powershell
$env:PYTHONPATH='src'; uv run pytest tests/test_application_workspace.py tests/test_application_replay_export.py tests/test_web_application.py -q
```

Expected: all tests pass, including existing `/timeline` consumers.

- [ ] **Step 5: Commit the replay API**

```powershell
git add src/smart_home_sim/web/app.py src/smart_home_sim/application/workspace.py tests/test_web_application.py tests/test_application_workspace.py
git commit -m "feat: expose bounded replay frames"
```

---

### Task 4: Implement the shared frontend replay clock and controller

**Files:**
- Create: `frontend/src/replay/replay-clock.ts`
- Create: `frontend/src/replay/useReplayController.ts`
- Create: `frontend/src/test/replay-clock.test.ts`
- Create: `frontend/src/test/useReplayController.test.tsx`
- Modify: `frontend/src/types.ts`

**Interfaces:**
- Consumes: Task 3 HTTP endpoints.
- Produces: `useReplayController(runId)` and pure `advanceTime`, `interpolateWaypoints`, and `clusterEvents` helpers.

- [ ] **Step 1: Write failing pure-clock and controller tests**

Create `frontend/src/test/replay-clock.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { advanceTime, clusterEvents, interpolateWaypoints } from "../replay/replay-clock";
import type { ReplayEvent } from "../types";

const event = (eventId: string, offsetMs: number): ReplayEvent => ({
  at: new Date(offsetMs).toISOString(),
  kind: "action",
  eventId,
  label: eventId,
  waypoints: [],
  details: {},
});

describe("replay clock", () => {
  it("advances simulation time by wall time times speed and clamps at the trace end", () => {
    const start = Date.parse("2026-08-23T08:00:00Z");
    expect(advanceTime(start, 500, 8, start + 3_000)).toBe(start + 3_000);
  });

  it("interpolates timestamped waypoints rather than event indexes", () => {
    const point = interpolateWaypoints([
      { at: "2026-08-23T08:00:00Z", regionId: "hall", traversalMode: "walking", position: { x: 0, y: 2 } },
      { at: "2026-08-23T08:00:10Z", regionId: "kitchen", traversalMode: "walking", position: { x: 10, y: 4 } },
    ], Date.parse("2026-08-23T08:00:05Z"));
    expect(point).toEqual({ x: 5, y: 3 });
  });

  it("clusters dense events without dropping their ids", () => {
    const clusters = clusterEvents([event("a", 0), event("b", 1)], 0, 10, 10);
    expect(clusters.flatMap((item) => item.eventIds)).toEqual(["a", "b"]);
  });
});
```

Create controller tests with `vi.useFakeTimers()` that assert automatic verification, blocked
playback on mismatch, restored session position, request of a bounded window around the position,
forward and backward seek stability, mode continuity, and a debounced session PUT.

- [ ] **Step 2: Run frontend tests and verify they fail**

Run:

```powershell
Set-Location frontend
npm test -- --run src/test/replay-clock.test.ts src/test/useReplayController.test.tsx
```

Expected: imports fail because replay clock and controller files do not exist.

- [ ] **Step 3: Add TypeScript contracts, pure clock functions, and the controller hook**

Mirror Task 1 models in `frontend/src/types.ts`. Use `eventId`, not the legacy `id`, and define:

```typescript
export type ReplayStatus = "verifying" | "ready" | "blocked";
export type ReplayDetailMode = "presentation" | "analysis";
export type ReplayVisibilityMode = "observable" | "oracle";
export type ReplayEventKind = "activity" | "action" | "movement" | "observation" |
  "state_transition" | "resource" | "runtime_event" | "plan_deviation";
```

Implement `frontend/src/replay/replay-clock.ts` as pure functions. `advanceTime` clamps to the trace
range; `interpolateWaypoints` uses adjacent waypoint timestamps and returns `undefined` for an empty
trajectory; `clusterEvents` groups only events whose rendered x coordinates are less than 6 pixels
apart and retains all IDs.

Implement this public controller shape in `useReplayController.ts`:

```typescript
export interface ReplayController {
  status: ReplayStatus;
  verification?: ReplayVerification;
  session?: ReplaySessionState;
  positionMs: number;
  playing: boolean;
  filters: ReplayFilters;
  selectedEventId?: string;
  events?: ReplayEventWindow;
  frame?: ReplayFrame;
  error?: ApiError;
  play(): void;
  pause(): void;
  seek(positionMs: number): void;
  step(direction: -1 | 1): void;
  selectEvent(eventId?: string): void;
  updateFilters(patch: Partial<ReplayFilters>): void;
}
```

The hook must POST verification, GET the saved session, request an event window centered on the
position, and request the matching frame. Use `requestAnimationFrame` while playing and
`performance.now()` deltas with `advanceTime`. Debounce session PUT by 400 ms. Abort stale window
and frame requests, pause at the trace end, and never request Oracle data while visibility mode is
Observable.

- [ ] **Step 4: Run controller tests, typecheck, and lint**

Run:

```powershell
Set-Location frontend
npm test -- --run src/test/replay-clock.test.ts src/test/useReplayController.test.tsx
npm run typecheck
npm run lint
```

Expected: all commands pass with no warnings.

- [ ] **Step 5: Commit the temporal controller**

```powershell
git add frontend/src/types.ts frontend/src/replay/replay-clock.ts frontend/src/replay/useReplayController.ts frontend/src/test/replay-clock.test.ts frontend/src/test/useReplayController.test.tsx
git commit -m "feat: add timestamp-correct replay controller"
```

---

### Task 5: Add truthful replay overlays to the shared plan

**Files:**
- Create: `frontend/src/replay/ReplayStage.tsx`
- Modify: `frontend/src/components.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/test/components.test.tsx`
- Modify: `frontend/src/test/ReplayWorkbench.test.tsx`

**Interfaces:**
- Consumes: `ReplayFrame`, selected movement event, `HomeModel`, and `SensorModel`.
- Produces: `ReplayOverlay` and `ReplayStage` with synchronized visual and structured alternatives.

- [ ] **Step 1: Write failing plan-overlay tests**

Extend `frontend/src/test/components.test.tsx`:

```typescript
it("shows replay residents, active regions and changed sensors without inventing unknown positions", () => {
  const overlay: ReplayOverlay = {
    residents: [
      { residentId: "mario", label: "Mario", marker: "M", regionId: "kitchen", position: { x: 2, y: 2 }, executionState: "moving" },
      { residentId: "luisa", label: "Luisa", marker: "L", executionState: "idle" },
    ],
    activeRegionIds: ["kitchen"],
    activeSensorIds: ["pir"],
    trajectory: [{ x: 1, y: 1 }, { x: 2, y: 2 }],
  };
  render(<PlanCanvas home={home} sensors={sensors} replayOverlay={overlay} />);
  expect(screen.getByLabelText("Mario in kitchen, moving")).toBeInTheDocument();
  expect(screen.queryByLabelText(/Luisa in/)).not.toBeInTheDocument();
  expect(document.querySelector("[data-region-id='kitchen']")).toHaveClass("is-replay-active");
  expect(screen.getByLabelText("pir sensor pir")).toHaveClass("is-replay-active");
});
```

Add a `ReplayStage` test that asserts the structured list contains both residents, explicitly says
“Position unknown” for Luisa, and expands external places only while a visible trajectory leaves
the dwelling.

- [ ] **Step 2: Run component tests and verify they fail**

Run:

```powershell
Set-Location frontend
npm test -- --run src/test/components.test.tsx src/test/ReplayWorkbench.test.tsx
```

Expected: TypeScript reports that `replayOverlay` is not a `PlanCanvas` prop.

- [ ] **Step 3: Implement overlay rendering and the structured alternative**

Add this contract to `frontend/src/types.ts`:

```typescript
export interface ReplayOverlay {
  residents: Array<{
    residentId: string;
    label: string;
    marker: string;
    regionId?: string;
    position?: Point;
    executionState: string;
  }>;
  activeRegionIds: string[];
  activeSensorIds: string[];
  trajectory: Point[];
  selectedResidentId?: string;
}
```

Replace the `activeMovement` prop in `PlanCanvas` with `replayOverlay`. Add `data-region-id` to room
groups, `is-replay-active` to active regions and sensors, and an `active-trajectory` polyline from
`replayOverlay.trajectory`. Render only residents with authoritative positions:

```tsx
<g aria-label="Replay residents" className="replay-residents">
  {replayOverlay?.residents.filter((item) => item.position).map((item) => (
    <g
      key={item.residentId}
      role="img"
      aria-label={`${item.label} in ${item.regionId ?? "unknown region"}, ${item.executionState}`}
      className={`replay-resident ${item.residentId === replayOverlay.selectedResidentId ? "is-selected" : ""}`}
      transform={`translate(${item.position!.x} ${item.position!.y})`}
    >
      <circle r=".22" />
      <text textAnchor="middle" y=".08">{item.marker}</text>
    </g>
  ))}
</g>
```

`ReplayStage` maps `ReplayFrame` into the overlay, computes a stable marker from resident order,
selects active sensor IDs where `changed` is true, and uses a visually hidden `<ol>` as the exact
structured alternative. Do not synthesize a position for a missing resident.

- [ ] **Step 4: Run plan, controller, type, and accessibility component tests**

Run:

```powershell
Set-Location frontend
npm test -- --run src/test/components.test.tsx src/test/ReplayWorkbench.test.tsx src/test/useReplayController.test.tsx
npm run typecheck
```

Expected: all commands pass.

- [ ] **Step 5: Commit spatial replay overlays**

```powershell
git add frontend/src/types.ts frontend/src/components.tsx frontend/src/replay/ReplayStage.tsx frontend/src/test/components.test.tsx frontend/src/test/ReplayWorkbench.test.tsx
git commit -m "feat: render authoritative replay overlays"
```

---

### Task 6: Build Analysis mode with a multitrack timeline and inspector

**Files:**
- Create: `frontend/src/replay/ReplayWorkbench.tsx`
- Create: `frontend/src/replay/ReplayToolbar.tsx`
- Create: `frontend/src/replay/ReplayTimeline.tsx`
- Create: `frontend/src/replay/ReplayInspector.tsx`
- Create: `frontend/src/replay/replay.css`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/test/App.test.tsx`
- Modify: `frontend/src/test/ReplayWorkbench.test.tsx`

**Interfaces:**
- Consumes: `ReplayController`, `ReplayStage`, and run model endpoint.
- Produces: an analysis workbench with synchronized selection, filters, seek, step, and Observable/Oracle structure.

- [ ] **Step 1: Write failing workbench tests**

Create `frontend/src/test/ReplayWorkbench.test.tsx` with mocked controller data and assert:

```typescript
it("keeps the same instant when analysis mode and oracle evidence are opened", async () => {
  render(<ReplayWorkbench runId="run_1" />);
  await screen.findByText("Replay verified");
  const before = screen.getByRole("slider", { name: "Replay time" }).getAttribute("value");
  fireEvent.click(screen.getByRole("button", { name: "Analysis" }));
  expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", before);
  fireEvent.click(screen.getByRole("button", { name: "Oracle" }));
  expect(screen.getByText("Simulated cause")).toBeInTheDocument();
  expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", before);
});

it("steps events, filters tracks and exposes simultaneous events individually", async () => {
  render(<ReplayWorkbench runId="run_1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Analysis" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Sensors" }));
  fireEvent.click(screen.getByRole("button", { name: "Next event" }));
  expect(screen.getAllByRole("button", { name: /08:15/ })).toHaveLength(2);
});
```

Update the legacy App test so opening the replay tab expects automatic verification and does not
look for “Play movements”. Add tests for digest mismatch, missing home model, no Oracle mapping,
window-loading error, keyboard stepping, and an empty event window.

- [ ] **Step 2: Run replay UI tests and verify they fail**

Run:

```powershell
Set-Location frontend
npm test -- --run src/test/ReplayWorkbench.test.tsx src/test/App.test.tsx
```

Expected: missing workbench modules and legacy replay assertions fail.

- [ ] **Step 3: Implement Analysis mode and remove the legacy interval**

`ReplayToolbar` must render mode buttons, previous/play-next transport, a native speed select with
`0.25, 0.5, 1, 2, 4, 8, 16, 32`, Observable/Oracle buttons, and verification status. Disable every
transport when `controller.status !== "ready"`.

`ReplayTimeline` groups events into these fixed tracks:

```typescript
export const REPLAY_TRACKS: Array<{ label: string; kinds: ReplayEventKind[] }> = [
  { label: "Activities", kinds: ["activity"] },
  { label: "Actions", kinds: ["action"] },
  { label: "Movements", kinds: ["movement"] },
  { label: "Sensors", kinds: ["observation"] },
  { label: "State", kinds: ["state_transition"] },
  { label: "Resources", kinds: ["resource"] },
  { label: "Runtime", kinds: ["runtime_event"] },
  { label: "Deviations", kinds: ["plan_deviation"] },
];
```

Render each event as a keyboard-focusable button positioned by its timestamp within the returned
window. Render clusters as one button whose accessible name includes the event count and whose
activation expands an inline list. A native range input controls the current instant. The inspector
shows event kind, status, interval, actor or sensor, details, source IDs, current resident state,
resources, and facts. Oracle cause content appears in a separately labelled section only in Oracle
mode.

Compose Analysis mode with this stable structure:

```tsx
<section className="replay-workbench" data-mode="analysis">
  <ReplayToolbar controller={controller} />
  <div className="replay-analysis-stage">
    <ReplayStage controller={controller} models={models} />
    <ReplayInspector controller={controller} />
  </div>
  <ReplayTimeline controller={controller} />
</section>
```

In `App.tsx`, delete `selectedEvent`, `playing`, the 650 ms `setInterval`, the eager timeline
resource, the legacy replay JSX, and `ReplayPlan`. Render `<ReplayWorkbench runId={runId} />` only
when the replay tab is active. Import `replay.css` from `main.tsx`.

Style with existing variables. Use a two-column stage and bottom timeline above 980 px; stack the
inspector and provide horizontal timeline scrolling below that breakpoint. Do not introduce cards
around each track or nested bordered surfaces.

- [ ] **Step 4: Run frontend unit, accessibility, type, lint, and build checks**

Run:

```powershell
Set-Location frontend
npm test -- --run src/test/ReplayWorkbench.test.tsx src/test/App.test.tsx src/test/components.test.tsx
npm run typecheck
npm run lint
npm run build
```

Expected: all commands pass and the production bundle contains no TypeScript errors.

- [ ] **Step 5: Commit Analysis mode**

```powershell
git add frontend/src/replay frontend/src/App.tsx frontend/src/main.tsx frontend/src/test/App.test.tsx frontend/src/test/ReplayWorkbench.test.tsx
git commit -m "feat: add scientific replay analysis mode"
```

---

### Task 7: Add Presentation mode and motion/accessibility polish

**Files:**
- Modify: `frontend/src/replay/ReplayWorkbench.tsx`
- Modify: `frontend/src/replay/ReplayToolbar.tsx`
- Modify: `frontend/src/replay/ReplayStage.tsx`
- Modify: `frontend/src/replay/replay.css`
- Modify: `frontend/src/test/ReplayWorkbench.test.tsx`
- Modify: `frontend/src/test/components.test.tsx`

**Interfaces:**
- Consumes: the exact controller and frame used by Analysis mode.
- Produces: presentation projection, evidence handoff, captions, sensor pulses, and reduced-motion behavior without changing temporal state.

- [ ] **Step 1: Write failing presentation and reduced-motion tests**

Add to `frontend/src/test/ReplayWorkbench.test.tsx`:

```typescript
it("presents the plan first and opens evidence at the identical instant", async () => {
  render(<ReplayWorkbench runId="run_1" />);
  expect(await screen.findByRole("heading", { name: "Mario prepares breakfast" })).toBeInTheDocument();
  const before = screen.getByRole("slider", { name: "Replay time" }).getAttribute("value");
  fireEvent.click(screen.getByRole("button", { name: "Open evidence" }));
  expect(screen.getByRole("button", { name: "Analysis" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("slider", { name: "Replay time" })).toHaveAttribute("value", before);
});

it("steps resident positions when reduced motion is requested", async () => {
  matchMediaMock.setMatches("(prefers-reduced-motion: reduce)", true);
  render(<ReplayWorkbench runId="run_1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Play" }));
  expect(screen.getByLabelText("Mario in kitchen, moving")).toHaveAttribute("data-motion", "step");
});
```

Add assertions that captions use event data rather than inferred prose, unknown positions remain
explicit, resident labels are visible, and sensor pulses do not run under reduced motion.

- [ ] **Step 2: Run presentation tests and verify they fail**

Run:

```powershell
Set-Location frontend
npm test -- --run src/test/ReplayWorkbench.test.tsx src/test/components.test.tsx
```

Expected: Presentation caption, evidence action, and reduced-motion attributes are absent.

- [ ] **Step 3: Implement the presentation projection using existing visual language**

Render Presentation mode from the same controller:

```tsx
<section className="replay-workbench" data-mode="presentation">
  <ReplayToolbar controller={controller} compact />
  <div className="replay-presentation-stage">
    <ReplayStage controller={controller} models={models} presentation />
    <div className="replay-caption" aria-live="polite">
      <p className="eyebrow">Current evidence</p>
      <h2>{caption.title}</h2>
      <p>{caption.region} · {caption.time}</p>
      <button className="button secondary" onClick={() => controller.updateFilters({ detailMode: "analysis" })}>
        Open evidence
      </button>
    </div>
  </div>
</section>
```

Build captions only from authoritative labels, resident IDs or display names, regions, and times.
Do not generate narrative claims. Keep the plan visually dominant; the caption is an anchored
strip, not a floating glass panel. Use `data-resident-index` plus marker text for multi-resident
identity.

In `replay.css`, add 150–250 ms state transitions using the existing exponential-style easing.
Animate SVG `transform` and `opacity`, never layout properties. Under
`@media (prefers-reduced-motion: reduce)`, set replay transition durations to zero, remove sensor
pulse keyframes, and retain all state changes. Use the existing warm and cool surfaces in both
themes; add no hard-coded white, black, gradients, or blur.

- [ ] **Step 4: Run the complete frontend suite and inspect both themes**

Run:

```powershell
Set-Location frontend
npm test
npm run typecheck
npm run lint
npm run build
```

Expected: coverage thresholds pass, no lint warnings are emitted, and the production build
succeeds. Inspect Presentation and Analysis at 1440×900 and 390×844 in both themes; verify no
page-level horizontal overflow and that the plan remains the primary object.

- [ ] **Step 5: Commit Presentation mode**

```powershell
git add frontend/src/replay frontend/src/test/ReplayWorkbench.test.tsx frontend/src/test/components.test.tsx
git commit -m "feat: add replay presentation mode"
```

---

### Task 8: Prove the real replay journey and document it

**Files:**
- Create: `tools/build_replay_e2e_workspace.py`
- Create: `frontend/e2e/replay.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Modify: `README.md`
- Modify: `Makefile`

**Interfaces:**
- Consumes: all previous replay service, API, and UI interfaces.
- Produces: reproducible real-backend acceptance coverage and operator documentation.

- [ ] **Step 1: Write the failing real-backend Playwright test**

Create `frontend/e2e/replay.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";
import axe from "axe-core";
import { readFile } from "node:fs/promises";

test("replays one verified run in presentation and analysis modes", async ({ page }) => {
  const run = JSON.parse(await readFile("../reports/e2e-replay-run.json", "utf8")) as { runId: string };
  await page.goto(`/simulations/${run.runId}`);
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByText("Replay verified")).toBeVisible();
  const time = page.getByRole("slider", { name: "Replay time" });
  const initial = await time.inputValue();
  await page.getByRole("button", { name: "Play" }).click();
  await expect.poll(() => time.inputValue()).not.toBe(initial);
  await page.getByRole("button", { name: "Open evidence" }).click();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await page.getByRole("button", { name: "Oracle" }).click();
  await expect(page.getByText("Simulated cause").first()).toBeVisible();

  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => (await window.axe.run(document)).violations);
  expect(violations).toEqual([]);
});

test("replay survives reload and keyboard stepping", async ({ page }) => {
  const run = JSON.parse(await readFile("../reports/e2e-replay-run.json", "utf8")) as { runId: string };
  await page.goto(`/simulations/${run.runId}`);
  await page.getByRole("tab", { name: "replay" }).click();
  await page.getByRole("button", { name: "Analysis" }).click();
  await page.getByRole("button", { name: "Next event" }).press("Enter");
  const saved = await page.getByRole("slider", { name: "Replay time" }).inputValue();
  await page.reload();
  await page.getByRole("tab", { name: "replay" }).click();
  await expect(page.getByRole("slider", { name: "Replay time" })).toHaveValue(saved);
});
```

Import `readFile` from `node:fs/promises` at the top of the test and use the same typed
`window as typeof window & { axe: ... }` cast already established in `frontend/e2e/app.spec.ts`
when running axe.

- [ ] **Step 2: Run the new E2E test and verify fixture failure**

Run:

```powershell
Set-Location frontend
npx playwright test e2e/replay.spec.ts --project=desktop-chromium
```

Expected: the fixture metadata file or completed run does not exist yet.

- [ ] **Step 3: Build a deterministic E2E workspace and document the controls**

Implement `tools/build_replay_e2e_workspace.py` with `WorkspaceService.create`, create one
simulation job, copy
`examples/materialization/mario_rossi_2026_10_30` into its run directory, import the artifacts, and
mark the job completed using the same sequence as `_completed_workspace` in
`tests/test_application_replay_export.py`. Write its generated `job.job_id` as
`{"runId": "..."}` to `reports/e2e-replay-run.json`. Remove only the explicitly resolved
`reports/e2e-workspace` fixture before recreating it; assert its resolved path is inside the
repository `reports` directory before deletion.

Update `frontend/playwright.config.ts` to invoke this builder in a Playwright `globalSetup` module
before the server starts. Keep the existing loopback port, real launcher, and mobile project.

Add a README replay section describing:

- automatic digest verification;
- shared clock across Presentation and Analysis;
- play, pause, step, seek, zoom, speed, and filters;
- Observable versus Oracle guarantees;
- keyboard operation and reduced motion;
- explicit behavior for mismatches, missing artifacts, and unknown positions.

Add a `benchmark-replay` Make target that measures index construction, 100 deterministic random
frame seeks, and 100 bounded event windows against weekly, monthly, and yearly fixtures. Set the
acceptance conditions to no unbounded response, equal repeated frames, and median frame latency
below 100 ms after index construction on the existing benchmark machine; report timings rather
than failing on wall-clock variance outside CI.

- [ ] **Step 4: Run final application checks**

Run:

```powershell
$env:PYTHONPATH='src'; uv run pytest -q
$env:PYTHONPATH='src'; uv run ruff check src tests tools
Set-Location frontend
npm test
npm run lint
npm run typecheck
npm run build
npx playwright test e2e/replay.spec.ts
Set-Location ..
make benchmark-replay
git diff --check
```

Expected: Python and frontend suites pass, coverage thresholds hold, both Playwright projects pass,
replay benchmark invariants hold, and `git diff --check` emits no output.

- [ ] **Step 5: Commit acceptance evidence and documentation**

```powershell
git add tools/build_replay_e2e_workspace.py frontend/e2e/replay.spec.ts frontend/playwright.config.ts README.md Makefile
git commit -m "test: prove dual-mode replay journey"
```

---

## Final review checkpoint

After Task 8, compare the implementation against
`docs/plans/2026-08-23-dual-mode-replay-design.md` and record evidence for these exact claims:

- the same timestamp and selection survive mode changes;
- playback position derives from trace and waypoint timestamps, never a fixed event interval;
- all trace families and observations appear in bounded analysis windows;
- the plan never displays an invented resident position;
- Observable mode contains no oracle identity;
- mismatched digests block playback;
- session restore is invalidated by a changed digest;
- both modes match the simulator's established visual language;
- keyboard, reduced-motion, dark-theme, narrow-screen, monthly, and yearly cases are verified.
