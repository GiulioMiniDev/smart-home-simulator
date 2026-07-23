# Longitudinal Multi-Scenario Simulation Design

## Goal

Allow a researcher to select multiple consecutive scenario files for the same
resident and home and execute them as one longitudinal simulation job.

The initial use case is to launch only two jobs for the Tommaso experiment:

- the five accepted chunks of the previous hybrid month;
- the five accepted chunks of the guarded hybrid month.

Each job must produce one completed monthly dataset without resetting the
authoritative state at weekly boundaries.

## Non-goals

- Merging all scenario files into one large scenario before compilation.
- Running chunks as independent batch replicas.
- Invoking an LLM during simulation.
- Changing or reusing hybrid-planning memory as simulation state.
- Publishing a partially completed month as a successful dataset.
- Implementing Monte Carlo replicas in the first vertical slice.

## Chosen approach

Introduce a versioned longitudinal simulation manifest. The manifest references
an ordered list of scenario files plus the shared behavioral package and
optional home/sensor policies.

The runtime validates the complete sequence before execution, then processes
one chunk at a time. Each accepted chunk starts from the authoritative state
produced by the preceding chunk. Chunk artifacts remain independently
inspectable, while the job also publishes aggregated monthly outputs.

This approach is preferred over concatenating scenarios because it keeps
validation and compilation bounded, supports checkpoint/resume, and scales to
three, six, and twelve months.

## Manifest contract

The public JSON contract will be versioned and use a shape similar to:

```json
{
  "schemaVersion": "1.0.0",
  "documentType": "longitudinal_simulation_manifest",
  "runId": "tommaso_guarded_month",
  "scenarioPaths": [
    "chunks/2026-08-10/scenario.json",
    "chunks/2026-08-17/scenario.json",
    "chunks/2026-08-24/scenario.json",
    "chunks/2026-08-31/scenario.json",
    "chunks/2026-09-07/scenario.json"
  ],
  "personalProcessPackagePath": "personal-process-package.json",
  "homePolicyPath": null,
  "sensorPolicyPath": null,
  "seed": 42
}
```

Paths are resolved relative to the manifest. The manifest records inputs and
configuration only; runtime progress belongs in a separate checkpoint.

The CLI may also accept repeated `--scenario` arguments and generate an
equivalent frozen manifest inside the run directory. The UI uses the same
contract after multi-file selection.

## Sequence validation

The whole sequence is rejected before execution unless all scenarios have:

- the same resident identity;
- the same home-model reference and timezone;
- compatible activity and behavior references;
- the same logical scenario identity (the current hybrid chunks intentionally
  retain one `scenarioId`);
- globally unique activity identifiers across chunks;
- chronological ordering;
- contiguous windows with no gaps or overlaps;
- matching end/start boundaries;
- valid individual scenario contracts.

The first scenario supplies the initial authoritative state. Initial states in
later scenario files are treated as planning-time declarations, not as runtime
authority. They are checked for structural compatibility but replaced by the
previous chunk's actual terminal state at execution.

## Runtime data flow

For every chunk:

1. Load and validate the referenced scenario.
2. Rebase its initial state onto the prior chunk's terminal authoritative state.
3. Compile the rebased scenario.
4. Materialize or reuse the same executable home and sensor deployment.
5. Build the resolved simulation bundle.
6. Execute the bundle.
7. Persist trace, report, terminal state, and semantic digests.
8. Atomically advance the checkpoint.

The next chunk cannot begin until the preceding checkpoint is durable.

State transferred across boundaries includes:

- resident location and resident variables;
- environment variables;
- resource and inventory state;
- device and actuator state;
- unfinished activities that explicitly allow boundary continuation;
- deterministic random-stream position where required.

Planned activities do not override observed terminal state.

The current compiler can mark an activity as truncated at the simulation
boundary, but the execution engine does not yet expose a resumable mid-process
state. The first vertical slice therefore rejects a chunk whose canonical plan
contains `truncatedAtSimulationEnd: true`. This preserves scientific correctness
instead of silently completing or restarting an activity across a checkpoint.
Explicit mid-activity continuation is a later milestone with its own versioned
state contract.

## Home and sensor continuity

The home topology and sensor deployment are created once per longitudinal job
and reused by every chunk. The runtime rejects a later scenario that requires an
incompatible home reference.

Sensor identifiers remain stable across chunks. Event sequence numbers and
timestamps are globally monotonic in the aggregated monthly log.

## Checkpoint and resume

The checkpoint records:

- manifest and configuration digests;
- completed chunk index;
- terminal authoritative state;
- random-stream checkpoint;
- per-chunk artifact paths and digests;
- aggregate trace and sensor-log progress.

Resume verifies every recorded digest before skipping completed chunks. A
failed attempt is preserved but does not advance the checkpoint.

## Output layout

```text
run/
  manifest.json
  checkpoint.json
  run.json
  home.json
  sensor-model.json
  chunks/
    0001/
      scenario.json
      canonical-plan.json
      simulation-bundle.json
      execution-trace.json
      simulation-report.json
      terminal-state.json
      observable-sensor-log.json
      oracle-mapping.json
  aggregate/
    execution-trace.json
    observable-sensor-log.json
    oracle-mapping.json
    simulation-report.json
```

Aggregate files are published as completed outputs only after every chunk
passes. Per-chunk artifacts remain available for diagnostics throughout the
run.

## Error handling

- Invalid sequence: fail before executing the first chunk.
- Invalid rebased scenario: preserve diagnostics and stop.
- Compilation or simulation failure: preserve the attempt and keep the last
  successful checkpoint.
- Digest mismatch on resume: fail without executing anything.
- Duplicate or non-monotonic aggregate events: fail finalization.
- Incompatible home/package/policy changes: fail before the affected chunk.

No fallback may silently reset state or run a chunk independently.

## CLI and UI

The headless entry point will be:

```powershell
smart-home-sim run-longitudinal manifest.json --output-dir generated/run
```

The UI will allow selecting multiple scenario JSON files, show their resolved
chronological order and validation status, and launch one job. The researcher
chooses the shared package and policies once. Progress is displayed per chunk,
with resume available after interruption.

For the current comparison, the UI will therefore launch two jobs: previous
month and guarded month.

## Testing strategy

Tests cover:

- manifest parsing, relative paths, and schema generation;
- order, gap, overlap, identity, timezone, and home compatibility failures;
- state handoff from one chunk to the next;
- stable home and sensor identities;
- global timestamp and event-sequence monotonicity;
- checkpoint advancement only after success;
- interruption and digest-verified resume;
- failure without publication of aggregate completed outputs;
- equivalence between uninterrupted and resumed runs;
- CLI multi-file/manifest behavior;
- a two-chunk end-to-end acceptance fixture.

The acceptance criterion is semantic equality between an uninterrupted run and
the same run resumed after the first chunk.
