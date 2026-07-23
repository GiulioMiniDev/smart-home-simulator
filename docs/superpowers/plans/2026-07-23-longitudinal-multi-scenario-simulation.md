# Longitudinal Multi-Scenario Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development` (recommended) or `executing-plans` to implement
> this plan task-by-task. Keep the checkboxes current.

**Goal:** Accept an ordered set of consecutive scenario JSON files for one
resident and home, execute them as one stateful longitudinal run, and publish
one digest-verifiable dataset so the previous and guarded Tommaso months can be
launched as only two simulations.

**Architecture:** Add a versioned longitudinal manifest and a sequential
orchestrator above the existing compiler, environment builder, simulation
engine and sensor projector. The orchestrator validates and prebuilds the whole
sequence, creates one home and one union-coverage sensor model, passes each
chunk's `FinalWorldState` into the next engine invocation, checkpoints every
accepted chunk atomically, and publishes flattened aggregate artifacts only
after all chunks succeed. Existing single-scenario and independent batch paths
remain unchanged.

**Tech Stack:** Python 3.12+, Pydantic 2, Typer, SimPy, FastAPI, React 19,
TypeScript, pytest, Vitest, Ruff, ESLint.

## Safety and scientific constraints

- No LLM is called during simulation.
- The first scenario's declared initial state is authoritative; later declared
  initial states are planning inputs only.
- A handoff uses the exact terminal resident position, posture, facts, entity
  states, environment facts and resource availability from the preceding
  trace.
- Every scenario must have the same logical `scenarioId`, resident set,
  timezone, seed, home reference, location/resource topology and catalog
  references.
- Windows must be ordered and exactly contiguous.
- Activity IDs must be globally unique across chunks.
- All chunks are compiled and bound before execution starts.
- Home topology is generated once. Sensor coverage is computed from the union
  of all chunk action bindings and sensor IDs remain stable.
- The current engine has no serializable mid-process continuation. Any
  canonical activity with `truncatedAtSimulationEnd: true` is rejected before
  execution. Never silently complete or restart it.
- Randomness remains deterministic because each event uses the existing
  SHA-256 named stream policy and globally unique event/activity IDs. The
  checkpoint records the policy and seed; no mutable PRNG cursor is invented.
- A successful checkpoint is written only after the chunk artifacts and their
  digests are durable.
- Aggregate trace, sensor log, oracle and report are published only after every
  chunk succeeds.
- Resume verifies manifest, input, policy, shared-model and completed-chunk
  digests before doing work.
- Existing `run-synthetic`, `simulate`, `simulate-batch`, replay and export
  behavior must not regress.
- Generated Tommaso manifests, packages and run outputs stay under the ignored
  `generated/` tree.

## File map

- Create `src/smart_home_sim/domain/longitudinal.py`: manifest, checkpoint,
  chunk record and run report contracts.
- Create `src/smart_home_sim/simulation/longitudinal_validation.py`: manifest
  loading, path resolution and sequence compatibility gates.
- Create `src/smart_home_sim/simulation/longitudinal_state.py`: exact
  `FinalWorldState` handoff validation.
- Create `src/smart_home_sim/simulation/longitudinal_aggregate.py`: flatten and
  digest trace, sensor and oracle artifacts.
- Create `src/smart_home_sim/simulation/longitudinal.py`: transactional
  orchestration, atomic checkpointing and resume.
- Modify `src/smart_home_sim/simulation/service.py`: optional authoritative
  starting world state without changing the default path.
- Modify `src/smart_home_sim/sensors/service.py`: optional authoritative
  starting state for initial observations.
- Modify `src/smart_home_sim/materialization/service.py`: union-coverage sensor
  deployment helper while preserving `deploy_sensors`.
- Modify `src/smart_home_sim/simulation/__init__.py`: export the longitudinal
  entry points.
- Modify `src/smart_home_sim/cli.py`: schema options and
  `run-longitudinal`.
- Modify `src/smart_home_sim/application/jobs.py`: longitudinal worker and job
  manager entry point.
- Modify `src/smart_home_sim/web/app.py`: API request/endpoint for multiple
  scenario artifact IDs.
- Modify `frontend/src/App.tsx` and `frontend/src/types.ts`: multi-file
  selection, chronological preview and one-job launch.
- Add frozen schemas under `schemas/`.
- Add `examples/longitudinal/two-chunk.manifest.json`.
- Create focused backend tests in
  `tests/test_longitudinal_simulation.py`.
- Modify `tests/test_simulation.py`, `tests/test_sensors.py`,
  `tests/test_cli.py`, `tests/test_json_schema.py`,
  `tests/test_application_jobs.py`, `tests/test_web_application.py` and
  frontend tests.
- Modify `README.md` and `ROADMAP.md`.

---

### Task 1: Define and freeze the longitudinal contracts

**Files:**

- Create: `src/smart_home_sim/domain/longitudinal.py`
- Modify: `src/smart_home_sim/cli.py`
- Modify: `tests/test_json_schema.py`
- Modify: `tests/test_cli.py`
- Create:
  `schemas/longitudinal-simulation-manifest-1.0.0.schema.json`
- Create:
  `schemas/longitudinal-simulation-manifest-1.0.0.schema.sha256`
- Create:
  `schemas/longitudinal-simulation-report-1.0.0.schema.json`
- Create:
  `schemas/longitudinal-simulation-report-1.0.0.schema.sha256`

**Public interfaces:**

```python
class LongitudinalSimulationManifest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["longitudinal_simulation_manifest"]
    run_id: str
    scenario_paths: list[str]
    personal_process_package_path: str
    home_policy_path: str | None = None
    sensor_policy_path: str | None = None
    seed: int


class LongitudinalChunkRecord(ContractModel):
    chunk_index: int
    scenario_path: str
    scenario_sha256: str
    input_state_sha256: str | None
    artifact_path: str
    bundle_sha256: str
    trace_sha256: str
    terminal_state_sha256: str
    sensor_log_sha256: str
    oracle_mapping_sha256: str


class LongitudinalCheckpoint(ContractModel):
    checkpoint_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    manifest_sha256: str
    configuration_sha256: str
    completed_chunk_count: int
    random_stream_policy: Literal["sha256-named-streams-1.0.0"]
    terminal_state: FinalWorldState | None
    chunks: list[LongitudinalChunkRecord]


class LongitudinalSimulationReport(ContractModel):
    report_version: Literal["1.0.0"] = "1.0.0"
    success: bool
    run_id: str
    manifest_sha256: str
    started_at: AwareDatetime
    ended_at: AwareDatetime
    chunks: list[LongitudinalChunkRecord]
    issues: list[LongitudinalSimulationIssue]
```

- [ ] **Step 1: Write failing contract and schema tests**

In `tests/test_longitudinal_simulation.py`, verify strict parsing, unique
non-empty paths, safe relative paths and checkpoint count/record consistency.
In `tests/test_json_schema.py`, add both public models to a
`LONGITUDINAL_SCHEMAS` mapping. In `tests/test_cli.py`, request both contracts
through `smart-home-sim schema --contract ...`.

- [ ] **Step 2: Run the focused tests and confirm imports/options are absent**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_simulation.py tests/test_json_schema.py tests/test_cli.py -v
```

Expected: collection or assertion failure because the contracts and CLI enum
members do not exist.

- [ ] **Step 3: Implement the strict Pydantic models**

Use the repository's `ContractModel`, camel-case aliases and
`RUN_ID_PATTERN`. Reject absolute paths, `..` traversal, duplicate
`scenarioPaths`, inconsistent checkpoint counts and successful reports that
contain issues.

- [ ] **Step 4: Expose and freeze the schemas**

Add `SchemaContract.longitudinal_simulation_manifest` and
`SchemaContract.longitudinal_simulation_report` to `src/smart_home_sim/cli.py`.
Generate each schema with the CLI, ensure LF line endings, and generate the
`.sha256` sidecar with the repository's canonical checksum convention.

- [ ] **Step 5: Re-run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_simulation.py tests/test_json_schema.py tests/test_cli.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add src/smart_home_sim/domain/longitudinal.py src/smart_home_sim/cli.py `
  schemas/longitudinal-* tests/test_longitudinal_simulation.py `
  tests/test_json_schema.py tests/test_cli.py
git commit -m "feat: define longitudinal simulation contracts"
```

---

### Task 2: Validate the entire scenario sequence before execution

**Files:**

- Create:
  `src/smart_home_sim/simulation/longitudinal_validation.py`
- Modify: `tests/test_longitudinal_simulation.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ResolvedLongitudinalInputs:
    manifest_path: Path
    manifest: LongitudinalSimulationManifest
    scenarios: tuple[Scenario, ...]
    scenario_paths: tuple[Path, ...]
    package: PersonalProcessPackage
    package_path: Path
    home_policy: HomeGenerationPolicy
    sensor_policy: SensorDeploymentPolicy
    manifest_sha256: str
    configuration_sha256: str


def load_and_validate_longitudinal_manifest(
    manifest_path: Path,
) -> ResolvedLongitudinalInputs: ...
```

- [ ] **Step 1: Add table-driven failing validation tests**

Start from two copies of the accepted minimal scenario with shifted windows and
date-namespaced activity IDs. Cover:

- relative path resolution against the manifest directory;
- malformed/missing files;
- reversed order, gap and overlap;
- different resident, timezone, seed, home/catalog reference;
- different location/resource topology;
- package `sourceScenarioId` mismatch;
- duplicate activity IDs across chunks;
- a later `initialState.at` not equal to its window start;
- a valid two-chunk sequence.

- [ ] **Step 2: Run only the new validation tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_simulation.py -k "manifest or sequence" -v
```

Expected: fail because no loader exists.

- [ ] **Step 3: Implement strict loading and compatibility fingerprints**

Resolve paths without changing the process working directory. Compare stable
canonical fingerprints for residents, locations, resources and
`modelReferences`. Treat a shared `scenarioId` as required logical identity;
require globally unique activity IDs. Validate the shared behavior package
against every scenario, not only the first.

- [ ] **Step 4: Verify no simulation function was called**

Add a monkeypatch sentinel for `simulate_bundle` to the valid-sequence test and
assert the loader never invokes it.

- [ ] **Step 5: Re-run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_simulation.py -k "manifest or sequence" -v
git add src/smart_home_sim/simulation/longitudinal_validation.py `
  tests/test_longitudinal_simulation.py
git commit -m "feat: validate longitudinal scenario sequences"
```

---

### Task 3: Let simulation and projection consume an authoritative start state

**Files:**

- Create: `src/smart_home_sim/simulation/longitudinal_state.py`
- Modify: `src/smart_home_sim/simulation/service.py`
- Modify: `src/smart_home_sim/sensors/service.py`
- Modify: `tests/test_simulation.py`
- Modify: `tests/test_sensors.py`
- Modify: `tests/test_longitudinal_simulation.py`

**Interfaces:**

```python
def validate_handoff(
    bundle: SimulationBundle,
    state: FinalWorldState,
) -> list[SimulationIssue]: ...


def simulate_bundle(
    bundle: SimulationBundle,
    *,
    initial_world_state: FinalWorldState | None = None,
) -> SimulationResult: ...


def project_sensors(
    trace: ExecutionTrace,
    bundle: SimulationBundle,
    sensor_model: SensorModel,
    *,
    initial_world_state: FinalWorldState | None = None,
) -> SensorProjectionResult: ...
```

- [ ] **Step 1: Write failing exact-handoff tests**

Create a `FinalWorldState` at the second chunk start with a resident positioned
away from the location anchor, posture `sitting`, changed resident facts,
changed entity state and changed environment facts. Assert the first movement,
initial sensor causes and second trace's starting effects reflect those values,
not `scenario.initialState` or `HomeEntity.initialState`.

Also test rejection for wrong timestamp, unknown/missing resident, invalid
region/position, missing/unknown entity and resource availability outside
`0..capacity`.

- [ ] **Step 2: Prove current reset behavior**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_simulation.py tests/test_sensors.py `
  tests/test_longitudinal_simulation.py -k "handoff or authoritative_start" -v
```

Expected: tests fail because both services use declared initial state only.

- [ ] **Step 3: Implement the optional engine handoff**

Keep `initial_world_state=None` byte-for-byte compatible with current behavior.
When supplied, initialize `ResidentRuntime` with the exact region, position,
posture, execution state, facts and held resources; initialize entity and
environment maps from the handoff. Reject invalid state before starting SimPy.

Resource availability must equal declared capacity in this vertical slice,
because truncated/in-flight activities are rejected and there is no legitimate
held allocation at a boundary. A mismatch is an explicit
`INITIAL_WORLD_STATE_INVALID`, never a reset.

- [ ] **Step 4: Implement authoritative initial sensor observations**

Thread the same optional state into the sensor candidate construction so
temperature/environment and contact initial values describe the actual
boundary state.

- [ ] **Step 5: Run focused and regression tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_simulation.py tests/test_sensors.py `
  tests/test_longitudinal_simulation.py -v
```

Expected: pass, including existing calls with no handoff.

- [ ] **Step 6: Commit**

```powershell
git add src/smart_home_sim/simulation/longitudinal_state.py `
  src/smart_home_sim/simulation/service.py src/smart_home_sim/sensors/service.py `
  tests/test_simulation.py tests/test_sensors.py `
  tests/test_longitudinal_simulation.py
git commit -m "feat: carry authoritative state across simulation chunks"
```

---

### Task 4: Prebuild chunks and deploy one union-coverage sensor model

**Files:**

- Modify: `src/smart_home_sim/materialization/service.py`
- Modify: `src/smart_home_sim/materialization/__init__.py`
- Modify: `tests/test_materialization.py`
- Modify: `tests/test_longitudinal_simulation.py`

**Interfaces:**

```python
def deploy_sensors_for_bundles(
    bundles: Sequence[SimulationBundle],
    policy: SensorDeploymentPolicy | None = None,
) -> SensorDeploymentResult: ...
```

- [ ] **Step 1: Add a failing union-coverage test**

Use two compatible bundles where the second chunk is the only one containing
an action against an openable resource. Assert the longitudinal sensor model
contains the corresponding contact sensor and that `deploy_sensors(first)`
retains its existing result.

- [ ] **Step 2: Run the focused test**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_materialization.py -k "union_coverage" -v
```

Expected: fail because only one bundle is accepted.

- [ ] **Step 3: Factor the deployment core**

Factor the current deployment logic around `(home, seed, action_bindings,
source_provenance)`; make `deploy_sensors` call it with one bundle and the new
helper call it with the stable de-duplicated union of action bindings.
Reject different home digests or seeds.

- [ ] **Step 4: Add the pre-execution truncation gate**

In the longitudinal prebuild path, compile and bind all chunks against the one
home before simulation. Reject any canonical plan containing
`truncatedAtSimulationEnd`. This gate must run before the first call to
`simulate_bundle`.

- [ ] **Step 5: Test and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_materialization.py tests/test_longitudinal_simulation.py `
  -k "union_coverage or prebuild or truncat" -v
git add src/smart_home_sim/materialization/service.py `
  src/smart_home_sim/materialization/__init__.py `
  tests/test_materialization.py tests/test_longitudinal_simulation.py
git commit -m "feat: materialize shared longitudinal sensors"
```

---

### Task 5: Aggregate chunks into ordinary consumable evidence contracts

**Files:**

- Create:
  `src/smart_home_sim/simulation/longitudinal_aggregate.py`
- Modify: `tests/test_longitudinal_simulation.py`

**Interfaces:**

```python
def aggregate_execution_traces(
    run_id: str,
    seed: int,
    traces: Sequence[ExecutionTrace],
) -> ExecutionTrace: ...


def aggregate_sensor_logs(
    logs: Sequence[ObservableSensorLog],
) -> ObservableSensorLog: ...


def aggregate_oracle_mappings(
    trace: ExecutionTrace,
    log: ObservableSensorLog,
    mappings: Sequence[OracleMapping],
) -> OracleMapping: ...
```

- [ ] **Step 1: Write failing aggregation tests**

Assert chronological stable ordering, global ID uniqueness, combined daily
summaries, first/last timestamps, last terminal state, recomputed semantic
digests, oracle references to the aggregate trace/log, and rejection of
overlap, duplicate IDs or mismatched sensor models.

- [ ] **Step 2: Run and observe missing helpers**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_simulation.py -k "aggregate" -v
```

- [ ] **Step 3: Implement flattened aggregate artifacts**

Return the existing `ExecutionTrace`, `ObservableSensorLog` and `OracleMapping`
contracts so diary, timeline and export code can consume the result without a
parallel data format. Derive aggregate IDs and digests from canonical semantic
content. Use a synthetic `sourceBundleId` based on `runId` and hash the ordered
list of source bundle digests into `sourceBundleSha256`.

- [ ] **Step 4: Run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_simulation.py -k "aggregate" -v
git add src/smart_home_sim/simulation/longitudinal_aggregate.py `
  tests/test_longitudinal_simulation.py
git commit -m "feat: aggregate longitudinal evidence"
```

---

### Task 6: Build the transactional orchestrator, checkpoint and resume

**Files:**

- Create: `src/smart_home_sim/simulation/longitudinal.py`
- Modify: `src/smart_home_sim/simulation/__init__.py`
- Modify: `tests/test_longitudinal_simulation.py`

**Interfaces:**

```python
def run_longitudinal_file(
    manifest_path: Path,
    *,
    output_directory: Path,
    resume: bool = True,
    progress: Callable[[str, float, str, dict[str, int]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> LongitudinalSimulationReport: ...
```

**Durable layout:**

```text
run/
  manifest.json
  checkpoint.json
  run.json
  home-model.json
  sensor-model.json
  chunks/0001/...
  attempts/0002-001/...
  aggregate/execution-trace.json
  aggregate/observable-sensor-log.json
  aggregate/oracle-mapping.json
  aggregate/simulation-report.json
  workspace-manifest.json
```

- [ ] **Step 1: Write an end-to-end failing two-chunk test**

Run two contiguous fixtures and assert:

- one home and sensor digest across both chunks;
- chunk 2 `input-state.json` equals chunk 1 `terminal-state.json`;
- chunk 2 behavior reflects the changed chunk 1 facts;
- checkpoint advances from 1 to 2 only after durable chunk publication;
- root `workspace-manifest.json` points standard roles
  `execution_trace`, `observable_sensor_log`, `oracle_mapping`, `home_model`
  and `sensor_model` at aggregate/shared artifacts;
- no aggregate directory exists while the run is incomplete.

- [ ] **Step 2: Add failure and resume tests**

Inject cancellation/failure after chunk 1, corrupt each of manifest, input
state and trace in separate tests, and assert resume either reuses verified
chunk 1 or fails before execution. Compare uninterrupted and resumed aggregate
artifacts byte-for-byte.

- [ ] **Step 3: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_simulation.py -k "orchestrator or resume or end_to_end" -v
```

- [ ] **Step 4: Implement atomic orchestration**

Use `.tmp` plus `os.replace` for JSON/checkpoint files and a staging directory
per chunk. Preserve failed attempts, but rename only accepted attempts into
`chunks/NNNN`. On resume, verify canonical content digests for every recorded
artifact. Finalize aggregate files in a staging aggregate directory and rename
it only when complete.

- [ ] **Step 5: Implement longitudinal replay verification**

Add `verify_longitudinal_run(output_directory)` which replays each chunk with
its persisted `input-state.json`, compares each semantic digest, then rebuilds
and compares aggregate digests. This is required because a longitudinal
aggregate has multiple source bundles.

- [ ] **Step 6: Run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_longitudinal_simulation.py -v
git add src/smart_home_sim/simulation/longitudinal.py `
  src/smart_home_sim/simulation/__init__.py `
  tests/test_longitudinal_simulation.py
git commit -m "feat: execute and resume longitudinal simulations"
```

---

### Task 7: Add the headless command and example manifest

**Files:**

- Modify: `src/smart_home_sim/cli.py`
- Modify: `tests/test_cli.py`
- Create: `examples/longitudinal/two-chunk.manifest.json`
- Modify: `README.md`

- [ ] **Step 1: Add failing CLI tests**

Cover successful invocation, existing output with `--no-resume`, valid resume,
invalid manifest exit code `2`, simulation failure exit code `1`, and progress
text containing `chunk 1/2` and `chunk 2/2`.

- [ ] **Step 2: Run the focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_cli.py `
  -k "run_longitudinal" -v
```

- [ ] **Step 3: Add the command**

```python
@app.command("run-longitudinal")
def run_longitudinal_command(
    manifest_path: Path,
    output_directory: Annotated[Path, typer.Option("--output-dir", "-o")],
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
) -> None:
    ...
```

Print one final path and verified artifact count; never print the hidden
comparison baseline or source scenario contents.

- [ ] **Step 4: Document and test**

Document path resolution, package requirement, safe resume and the explicit
boundary-truncation limitation.

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_cli.py tests/test_longitudinal_simulation.py -v
git add src/smart_home_sim/cli.py tests/test_cli.py `
  examples/longitudinal/two-chunk.manifest.json README.md
git commit -m "feat: add longitudinal simulation command"
```

---

### Task 8: Add multi-scenario jobs to the application API

**Files:**

- Modify: `src/smart_home_sim/application/jobs.py`
- Modify: `src/smart_home_sim/web/app.py`
- Modify: `tests/test_application_jobs.py`
- Modify: `tests/test_web_application.py`

**API contract:**

```python
class LongitudinalMaterializationStart(ApiModel):
    scenario_artifact_ids: list[str] = Field(min_length=2)
    behavior_artifact_id: str
    home_policy: dict[str, Any] = Field(default_factory=dict)
    sensor_policy: dict[str, Any] = Field(default_factory=dict)
    resume: bool = True
```

Endpoint:

```text
POST /api/homes/{home_id}/longitudinal-runs
```

- [ ] **Step 1: Write failing manager and API tests**

Assert multiple ordered scenario IDs are stored in the immutable job request,
the worker resolves only artifacts owned by the workspace, writes a frozen
manifest, streams per-chunk progress, imports aggregate artifacts under the
standard roles, and marks structured validation/simulation failures correctly.

- [ ] **Step 2: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_application_jobs.py tests/test_web_application.py `
  -k "longitudinal" -v
```

- [ ] **Step 3: Implement worker and manager dispatch**

Add `_longitudinal_worker` and
`JobManager.start_longitudinal_materialization(...)`. Keep the single-scenario
worker untouched. Job kind must be `longitudinal_materialization`; cancellation
leaves the last verified checkpoint and marks the job interrupted/cancelled
without publishing aggregate evidence.

- [ ] **Step 4: Dispatch replay verification by job kind**

For a longitudinal job, use `verify_longitudinal_run`; for an ordinary job,
retain the current single-bundle replay path.

- [ ] **Step 5: Test and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' `
  tests/test_application_jobs.py tests/test_web_application.py -v
git add src/smart_home_sim/application/jobs.py src/smart_home_sim/web/app.py `
  tests/test_application_jobs.py tests/test_web_application.py
git commit -m "feat: run longitudinal jobs from the application"
```

---

### Task 9: Add the multi-file UI

**Files:**

- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/test/App.test.tsx`
- Modify: `frontend/src/test/api.test.ts`
- Modify: `frontend/e2e/application.spec.ts`

- [ ] **Step 1: Write failing component tests**

On the home page, select multiple `.json` scenario files and one package.
Assert the UI:

- parses and sorts scenarios by `simulationWindow.start`;
- shows filename, start/end and sequence errors before launch;
- refuses gaps, overlaps or different home/resident identity;
- sends one `scenario_artifact_ids` array to the longitudinal endpoint;
- still presents the existing single-scenario flow unchanged.

- [ ] **Step 2: Run the focused frontend tests**

```powershell
Set-Location frontend
npm test -- src/test/App.test.tsx src/test/api.test.ts
Set-Location ..
```

- [ ] **Step 3: Implement the separate longitudinal panel**

Use `<input type="file" multiple accept="application/json,.json">`. Keep this
panel separate from the ordinary authoring/run control. Show the resolved
chronological order and a single action labelled with the number of chunks,
for example `Start 5-chunk longitudinal run`.

- [ ] **Step 4: Add an end-to-end happy path**

Exercise two files for one home and assert only one job row appears with kind
`longitudinal_materialization`.

- [ ] **Step 5: Run frontend quality gates and commit**

```powershell
Set-Location frontend
npm run typecheck
npm run lint
npm test
npm run build
Set-Location ..
git add frontend/src frontend/e2e/application.spec.ts
git commit -m "feat: select multiple scenarios for one run"
```

---

### Task 10: Verify the full repository and prepare the Tommaso A/B launches

**Files:**

- Modify: `ROADMAP.md`
- Generated only, do not commit:
  `generated/longitudinal-simulation/tommaso-previous-month/`
- Generated only, do not commit:
  `generated/longitudinal-simulation/tommaso-guarded-month/`

- [ ] **Step 1: Run backend quality gates**

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest
```

Expected: Ruff clean; the repository coverage threshold remains at least 95%.

- [ ] **Step 2: Run frontend quality gates**

```powershell
Set-Location frontend
npm run typecheck
npm run lint
npm test
npm run build
Set-Location ..
```

- [ ] **Step 3: Prepare one shared Tommaso process package**

Build one package from the union of intents used by both the previous and
guarded months. It may reuse an existing process model only when
`implementedComponents` exactly match the activity catalog. Generate and
validate new process models for the remaining component combinations. Set the
package `sourceScenarioId` to the shared logical hybrid scenario ID and
validate the exact same package against all ten scenario chunks.

Do not pass the old month's day plan or aggregate statistics to an LLM. Only
catalog definitions, the stable Tommaso behavioral profile and the union of
required intents may be used to complete missing process models.

- [ ] **Step 4: Create two ignored manifests**

Create:

- one manifest referencing the five accepted previous-month scenarios;
- one manifest referencing the five accepted guarded-month scenarios.

Both must use the same package, policies, home reference, sensor policy and
seed. Run manifest validation before execution.

- [ ] **Step 5: Launch a two-chunk smoke test for each arm**

First exercise only the first two chunks of each arm. Verify checkpoint
handoff, stable home/sensor digests, non-empty aggregate evidence and
longitudinal replay.

- [ ] **Step 6: Launch the complete months as two simulations**

```powershell
.\.venv\Scripts\smart-home-sim.exe run-longitudinal `
  generated/longitudinal-simulation/tommaso-previous-month/manifest.json `
  --output-dir generated/longitudinal-simulation/tommaso-previous-month/run

.\.venv\Scripts\smart-home-sim.exe run-longitudinal `
  generated/longitudinal-simulation/tommaso-guarded-month/manifest.json `
  --output-dir generated/longitudinal-simulation/tommaso-guarded-month/run
```

- [ ] **Step 7: Verify comparison readiness**

Assert equal simulated date range, resident, package digest, home digest,
sensor-model digest and seed between arms. Record only artifact paths and
digests in the experiment note; do not reveal the hidden baseline to the
generation path.

- [ ] **Step 8: Update the roadmap and commit tracked documentation only**

```powershell
git status --short
git check-ignore -v generated/longitudinal-simulation/tommaso-previous-month/run.json
git add ROADMAP.md
git commit -m "docs: record longitudinal simulation milestone"
```

Do not stage any file under `generated/`.

---

## Final review checklist

- [ ] Review the diff for accidental changes to ignored generated artifacts.
- [ ] Confirm no implementation path imports `hybrid_planning` from the
  simulation engine.
- [ ] Confirm no prompt, request or repair artifact contains the hidden
  previous month as an example.
- [ ] Confirm single-scenario results remain byte-stable in existing golden
  tests.
- [ ] Confirm chunk 2 demonstrably starts from chunk 1 terminal state.
- [ ] Confirm interrupted and resumed runs are byte-identical to uninterrupted
  runs.
- [ ] Confirm aggregate diary, timeline, observations, oracle and exports work
  through the existing application readers.
- [ ] Confirm longitudinal replay verifies every chunk plus aggregate digests.
- [ ] Confirm the UI creates one job for five files, so the two experiment arms
  appear as exactly two simulations.
- [ ] Run `git diff --check`.
