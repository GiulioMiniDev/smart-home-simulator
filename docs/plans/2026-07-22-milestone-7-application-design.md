# Milestone 7 application design

**Status:** approved  
**Date:** 2026-07-22  
**Scope:** local application, persistent workspace, export, and replay

## Goal

Deliver the complete Milestone 7 workflow through a desktop-first local web application.
A researcher must be able to create or import accepted M3 inputs, materialize and edit the
home and sensors, run and monitor simulations, inspect authoritative and observable results,
replay executions, and export reproducible datasets without using the CLI or manually editing
JSON.

The UI is a client of the same authoritative services and frozen contracts used by M1-M6.1.
It must not introduce alternative validation, repair, simulation, or sensor semantics.

## Chosen architecture

The application is a local web application:

- a FastAPI backend binds only to loopback;
- a React and TypeScript frontend is built with Vite and shipped as static application assets;
- SQLite stores transactional application metadata and relationships;
- large scientific artifacts remain immutable files addressed and verified by SHA-256;
- application services are versioned Python interfaces independent of HTTP and the UI;
- REST handles transactional commands and queries;
- Server-Sent Events deliver durable job progress and structured logs;
- worker processes isolate long-running simulation and export work;
- no cloud service, remote account, or internet connection is required.

This approach was selected over a Tauri shell, which would add Rust and desktop packaging
complexity without changing simulation semantics, and over a Python server-rendered UI, which
would make the graphical editors and synchronized replay surface substantially harder to build
and test.

## Workspace persistence

SQLite is the transactional index for the workspace. It does not store execution traces,
sensor logs, oracle mappings, or large exports as blobs.

The database records:

- workspace identity, format version, timestamps, and preferences;
- homes and their current and historical home-model revisions;
- residents and their associations with homes and M3 inputs;
- scenario and personal-process-package revisions, validation status, provenance, and digest;
- sensor-configuration revisions and validation status;
- resolved bundles and the exact revisions, policies, residents, and seed they consume;
- simulation jobs, durable status, progress, phase, process identity, timing, and outcome;
- sequenced structured job events used for SSE and restart recovery;
- artifact roles, formats, schema versions, relative paths, sizes, and SHA-256 digests;
- export requests, filters, formats, results, and manifests;
- saved replay sessions and verified source execution digests;
- normalized validation issues with JSON paths and graphical-element references;
- application settings and forward-only schema migrations.

The workspace layout is:

```text
workspace/
  workspace.sqlite3
  objects/<sha256>
  runs/<run-id>/
  exports/<export-id>/
  staging/
```

Only relative, validated paths are stored. Foreign keys and uniqueness constraints are
mandatory. Mutations use explicit transactions, WAL mode, controlled busy timeouts, and
filesystem staging. Files are verified and atomically promoted before the corresponding
SQLite transaction becomes visible. Startup reconciliation detects missing, corrupt, orphaned,
or digest-mismatched files. Jobs left running after a crash become `interrupted`. Referenced
entities use logical deletion so historical runs remain reproducible. A backup is taken before
database migration.

## Application services and data flow

The framework-independent application layer contains:

- `WorkspaceService` for creation, opening, migration, search, integrity, and recovery;
- `AuthoringService` for M3 import, progressive validation, and atomic publication;
- `HomeDesignService` for home revisions and authoritative environment validation;
- `SensorDesignService` for sensor revisions and authoritative sensor-model validation;
- `BundleService` for exact resolution of homes, residents, inputs, policies, and seeds;
- `RunService` for the queue, workers, progress, cancellation, and crash recovery;
- `ExportService` for streaming JSONL, CSV, and XES projections and manifests;
- `ReplayService` for integrity checks, semantic replay, indexing, and synchronized snapshots.

Every publishable change follows:

```text
UI draft
  -> structural validation
  -> authoritative semantic validation
  -> filesystem staging
  -> digest and relationship verification
  -> atomic file publication
  -> SQLite transaction commit
```

A failure discards staging and rolls back the transaction. Drafts can be persisted explicitly
but can never be used for a bundle or run. Editing a scenario, process package, home, sensor
configuration, or policy creates a new immutable revision. Existing runs never change.

A home may organize multiple residents. Each bundle declares its precise resident set and input
revisions; the application never merges unrelated scenarios implicitly.

Worker progress is based on completed backend phases and engine events, not timers. Optional
observer callbacks expose validation, compilation, materialization, binding, simulation time,
activities, counts, sensor projection, and publication without changing deterministic results.
Cancellation terminates work safely and discards staging, so cancelled jobs cannot expose
partial scientific artifacts.

## Export

Export writers consume persisted artifacts incrementally:

- JSONL emits one canonical record per line;
- CSV provides stable columns for each artifact family;
- XES projects cases, activities, and events under an explicit mapping;
- every export includes a manifest with roles, schemas, versions, digests, seed, sources, and
  filters.

Observable and oracle exports use distinct types and writer paths. Observable writers never
receive oracle objects, which prevents accidental oracle leakage by construction. Large outputs
are streamed to staging and published atomically. Round-trip tests verify all fields owned by
each format.

## Replay and the ground-truth diary

Replay first verifies the bundle, trace, manifest, and digests, then invokes the authoritative M5
semantic replay check. Only verified executions can be presented as replayable.

The run detail includes an authoritative activity diary derived directly from the execution
trace. Each entry exposes:

- planned and actual times;
- resident, intent, and outcome;
- executed atomic actions;
- regions, movements, and trajectories;
- resources and state transitions;
- plan deviations and causes;
- source activity ID, activity execution ID, process model ID, node IDs, action execution IDs,
  source bundle, seed, and trace digest.

The diary is a human-readable projection, never a second source of truth. Every row links back to
the original trace records.

The observable view shows sensor records without identity or activity fields. Selecting a record
can explicitly traverse the separate oracle mapping to its simulated movement, state transition,
or action and then to resident and activity identifiers. False positives, noise, dropout, and
failure effects are labelled rather than assigned invented behavioral causes.

The replay debugger synchronizes:

- a timeline of activities, actions, movements, and observations;
- the 2D home with residents, trajectories, objects, and sensors;
- an inspector for state, resources, causality, and current records.

Observable and Oracle are visibly distinct modes, communicated with text and structure as well
as color.

## User interface

The application is a modern research workstation with a coherent shell, light and dark themes,
responsive desktop-first layouts, and complete empty, loading, success, and error states.

Primary navigation contains Dashboard, Homes, Residents, Simulations, Exports, and Help. The top
bar exposes the current workspace, global search, worker state, notifications, and theme. Homes
group residents, scenarios, process models, planimetry, sensors, bundles, runs, comparisons, and
exports.

The first-run journey is:

```text
create or open workspace
  -> import M3 authoring or create inputs
  -> validate scenario and behavior
  -> generate home and sensors
  -> review or customize
  -> run simulation
  -> inspect diary and replay
  -> export dataset
```

The home editor is an SVG 2D canvas with zoom, pan, grid, snapping, selection, undo/redo, and a
structured inspector. It edits rooms, outdoor regions, doors, passages, obstacles, interaction
points, objects, capabilities, initial state, and access constraints. Validation overlays locate
topological and geometric errors. A route mode previews authoritative connectivity and paths.

The sensor editor reuses the plan and supports PIR, contact, and temperature sensors, placement,
orientation, coverage, timing, cooldown, jitter, noise, dropout, false events, and failure
windows. M6.1 presets create explicit revisions and never silently overwrite custom work.

The simulation center shows the durable queue, real phases, progress, elapsed time, seed,
residents, warnings, artifacts, cancellation, and configuration comparison. Run details expose
the ground-truth diary, observable log, oracle links, reports, artifacts, replay, and export.

No ordinary workflow requires opening or manually editing JSON.

## Errors, accessibility, resilience, and local security

Errors remain structured with code, phase, severity, JSON path, details, and optional visual
element references. Selecting an error focuses the corresponding form or graphical object.
Technical detail remains available without replacing the plain-language explanation.

Entity and job states are explicit. Refreshing or closing the UI does not stop the backend.
Restart reconstructs state from SQLite events. Backend failure triggers reconciliation before new
work. Corrupt workspaces open in a diagnostic recovery mode instead of being silently accepted.

Accessibility requirements include:

- complete keyboard navigation and visible focus;
- semantic landmarks, labels, and live status announcements;
- WCAG AA contrast in both themes;
- text, shape, and icon status indicators that do not depend on color;
- structured, keyboard-editable alternatives to the canvas, timelines, and charts;
- reduced-motion support and adjustable density.

The API binds only to loopback and uses a per-session token. All paths are normalized and confined
to the workspace. Imports enforce size, nesting, encoding, duplicate-key, archive traversal, and
schema limits. No endpoint can read or write an arbitrary host path through client input.

## Verification and closure

The backend suite covers services, database migrations, transactions, concurrency, locks,
rollback, crash recovery, authoritative contracts, API security, cancellation, digests,
idempotency, and determinism with at least 95% Python coverage.

The frontend suite covers components, editors, undo/redo, validation mapping, diary and oracle
navigation, keyboard operation, axe checks, light and dark visual regression, and responsive
layouts with at least 95% TypeScript coverage.

Playwright acceptance tests use the real backend and workers to:

1. create a workspace;
2. import and validate accepted M3 authoring;
3. generate home and sensors;
4. edit and publish a revision;
5. start and monitor a simulation;
6. close and reopen the UI during work;
7. inspect the ground-truth diary and observations;
8. replay and match the semantic digest;
9. export JSONL, CSV, and XES;
10. reimport and verify manifest, digests, and round trips;
11. cancel a second run and prove that no partial artifacts were published.

Additional acceptance cases cover the golden home without semantic loss, a compatible
multi-resident environment, intentionally corrupt files and digests, observable-data oracle-leak
prevention, portable relative paths, and forced frontend/backend termination.

Benchmarks cover a dashboard with at least 10,000 artifacts and 1,000 runs, workspace open and
search, the golden home and sensor editors, weekly and monthly replay, streaming export with
bounded memory growth, and progress-event latency.

The terminal gate includes formatting, lint, type checking, schema and checksum verification,
Python and frontend tests, end-to-end tests, accessibility, visual regression, benchmarks, and a
distribution build. Milestone artifacts include the technology ADR, M7 specification, public
schemas and checksums, golden examples and exports, integrated help, installation documentation,
and a closure audit. `ROADMAP.md` changes to completed and frozen only after every gate passes.

