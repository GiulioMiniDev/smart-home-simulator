# Milestone 7 implementation plan

**Date:** 2026-07-22  
**Design:** `docs/plans/2026-07-22-milestone-7-application-design.md`  
**Target:** a complete, locally distributed M1-M7 application

## Delivery rules

- Preserve every frozen M1-M6.1 public contract and deterministic behavior.
- Keep the service layer usable without HTTP, React, or a browser.
- Publish artifacts only after authoritative validation and digest checks.
- Keep observable and oracle data in different models, endpoints, writers, and UI modes.
- Use relative workspace paths and atomic filesystem/SQLite operations.
- Do not update the roadmap to complete until all terminal gates pass.
- Do not include unrelated pre-existing worktree changes in any commit.

## 1. Baseline and architecture records

1. Run the existing quality gate and record the baseline.
2. Add ADR-016 for the local web architecture, persistence split, and framework independence.
3. Add the M7 specification with authorities, invariants, state machines, and acceptance matrix.
4. Extend project dependencies for FastAPI and Uvicorn and add a Node 20 frontend workspace.
5. Extend Makefile and CI targets without weakening the existing 95% Python gate.

Verification: existing tests, schema checks, and frozen golden artifacts remain unchanged.

## 2. Public application contracts

Add strict Pydantic contracts for:

- workspace manifest and portable workspace archive;
- home/resident/input/configuration/bundle revisions;
- application validation issues and graphical references;
- durable job, job event, progress, and cancellation status;
- artifact catalogue entries;
- export request, export manifest, format descriptors, and import report;
- replay verification, diary entries, indexed frames, and observable/oracle links.

Generate Draft 2020-12 schemas, checksums, structural tests, and deterministic examples. Register
stable error codes and exercise every code in the test matrix.

Verification: model/schema equivalence, metaschema validation, checksum verification, aliases,
strict parsing, deterministic serialization, and negative examples.

## 3. Transactional workspace service

Create `smart_home_sim.application` with:

- SQLite connection policy, WAL, foreign keys, busy timeout, and explicit transactions;
- forward-only migrations and pre-migration backups;
- tables and repositories for workspaces, homes, residents, revisions, bundles, jobs, events,
  artifacts, exports, replay sessions, validation issues, and settings;
- immutable object storage keyed by SHA-256;
- staging, fsync, atomic promotion, and transaction coordination;
- startup reconciliation and diagnostic/read-only recovery mode;
- logical deletion and historical-reference protection;
- portable archive import/export with traversal and digest checks.

Verification: transaction rollback, concurrent readers/writers, migration, crash simulation,
missing/orphan/corrupt files, relative-path confinement, duplicate content, and backup recovery.

## 4. Authoring, home, sensor, and bundle application services

Wrap the frozen services behind application commands:

- import an M3 authoring envelope or accepted scenario/package pair;
- save explicit drafts and map validation issues to fields/elements;
- publish only after M1, M2, and M3 gates;
- materialize a home and sensors using M6.1 policies;
- import, edit, validate, and publish home-model revisions;
- import, edit, validate, and publish sensor-model revisions;
- create resident associations and compatible multi-resident bundles;
- resolve and persist exact revision/digest/seed provenance.

Add deterministic editor command models for geometry and sensors, including undoable operations,
without creating a second home or sensor schema.

Verification: golden home round trip, all M6 sensor types, invalid geometry and routes, missing
capabilities, incompatible residents, policy revisions, and atomic failure.

## 5. Durable local job system

Implement a process-isolated local queue with:

- persisted `queued/running/completed/failed/cancelled/interrupted` states;
- sequenced job events and monotonic progress;
- stage observers for authoritative services and event observers for simulation work;
- cooperative cancellation plus bounded forced termination;
- staging ownership and cleanup;
- restart recovery and reconciliation;
- safe concurrency limits and independent seeds/state;
- structured, bounded logs and elapsed/count metrics.

Verification: cancel in every phase, frontend disconnect, backend crash, worker crash, concurrent
jobs, stale processes, event replay, no partial publication, and deterministic output equality
with direct M6.1 execution.

## 6. Streaming export and import

Implement separate streaming writers for:

- observable sensor log JSONL and CSV;
- oracle mapping JSONL and CSV;
- execution activities, actions, movements, state transitions, resources, runtime events, plan
  deviations, final state, and canonical plan;
- XES execution/activity and observable-event projections under documented mappings;
- export manifests with schemas, versions, filters, provenance, relations, sizes, and digests.

Implement manifest preview and verified reimport. Writers receive typed artifact-specific sources;
observable writers cannot import or accept oracle models.

Verification: golden exports, round trips, streaming/bounded memory, cancellation, invalid
manifest, digest mismatch, path traversal, large files, CSV escaping, XES validation, and oracle
leak scans.

## 7. Replay and ground-truth diary

Implement:

- authoritative M5 replay verification before indexing;
- a stable temporal index over activities, actions, movements, transitions, resources, runtime
  events, deviations, observations, and oracle links;
- paged diary projection with source activity/process/node/execution provenance;
- time-window frame queries for planimetry and inspectors;
- explicit observable-only queries;
- explicit oracle traversal from observation to simulated cause;
- saved replay position and filters.

Verification: semantic digest equality, exact diary provenance, simultaneous events, false
positives/noise, multiple residents, pagination, random seeks, weekly/monthly artifacts, and no
oracle data in observable responses.

## 8. Local HTTP application

Add a FastAPI app and launcher with:

- loopback-only startup and an ephemeral per-session token;
- workspace, revision, job, event, export, replay, search, settings, and help endpoints;
- strict request/response models and consistent structured errors;
- SSE resume through event sequence IDs and heartbeat/disconnect handling;
- safe upload limits and archive/JSON parsing;
- static production frontend serving and history fallback;
- health, readiness, and graceful shutdown behavior;
- no arbitrary filesystem endpoint.

Verification: API integration, OpenAPI snapshot, auth failures, hostile Origin/path/input tests,
SSE reconnect, lifecycle, and distribution launch.

## 9. Frontend foundation and design system

Create a React/TypeScript/Vite application with:

- accessible application shell, routing, data/query layer, error boundary, and SSE client;
- light/dark tokens, typography, spacing, elevation, status, chart, and planimetry palettes;
- reusable buttons, fields, dialogs, drawers, tabs, tables, command/search, notifications,
  skeletons, empty/error states, breadcrumbs, and inspectors;
- keyboard/focus primitives and reduced-motion support;
- responsive desktop/tablet layouts and density controls;
- integrated contextual help.

Verification: component tests, Storybook-free deterministic fixtures, axe, keyboard behavior,
theme contrast, responsive snapshots, error and loading states, and 95% frontend coverage.

## 10. Workspace, dashboard, and guided authoring UI

Implement:

- create/open/import/recover workspace flows;
- first-run quick path and integrated guide;
- dashboard for recent homes, active jobs, issues, and summary metrics;
- global search and filters;
- home-centric organization of residents, revisions, bundles, runs, and exports;
- M3 import and progressive validation;
- resident and multi-resident association management;
- materialization policy and seed configuration;
- revision history, provenance, and comparisons.

Verification: empty/new/large/corrupt workspaces, complete keyboard journey, validation focus,
multi-resident grouping, restart persistence, and no manual JSON requirement.

## 11. Home and sensor editors

Implement a shared SVG scene with:

- pan, zoom, grid, snap, fit, selection, multiselect, undo/redo, and keyboard movement;
- rooms/outdoors, polygons, doors/passages, obstacles, interaction points, objects, resources,
  capabilities, initial state, and access constraints;
- authoritative validation overlays, issue list synchronization, connectivity, and route preview;
- accessible tree/table alternative and property inspector;
- PIR, contact, and temperature placement/configuration;
- orientation/coverage, timing, error model, failure windows, and preset-as-revision actions.

Verification: golden home lossless round trip, invalid geometry/topology/routes, every M6 sensor
field, keyboard-only editing, undo/redo invariants, theme/responsive visual regression, and
immediate validation feedback.

## 12. Simulation center, diary, replay, and exports UI

Implement:

- queue/current/recent views grouped by home;
- real phase, progress, counts, elapsed time, events, warnings, cancellation, and recovery;
- run comparison by residents, revisions, policies, seed, warnings, and artifact digests;
- run detail with reports, artifacts, ground-truth diary, observable log, and oracle link drilldown;
- synchronized replay timeline, planimetry, residents, trajectories, sensors, and state inspector;
- clearly separated Observable and Oracle modes;
- export builder, manifest preview, progress, cancellation, download/location, and verified import.

Verification: real-worker Playwright tests, SSE reconnect, restart, diary provenance, sensor-cause
navigation, false-positive labels, replay digest, cancellation, and all export formats.

## 13. Terminal acceptance and release

1. Add realistic golden workspace and exports without committing avoidable large duplicates.
2. Run Python formatting, lint, type checks, tests, and 95% coverage.
3. Run frontend formatting, lint, type checks, unit/component tests, and 95% coverage.
4. Run Playwright end to end with real backend/workers.
5. Run keyboard, axe, contrast, and visual-regression gates.
6. Run workspace, editor, replay, progress, and streaming-memory benchmarks.
7. Build the Python wheel/sdist and production frontend; install and launch from the built wheel.
8. Verify Windows, macOS, and Linux CI definitions with Python 3.12 and Node 20.
9. Complete installation, usage, integrated help, export mapping, recovery, and contributor docs.
10. Add the terminal M7 closure audit with an evidence matrix.
11. Update README and ROADMAP to completed/frozen only when every item above passes.

## Required terminal evidence

- Exact command outputs and versions for every quality gate.
- Frozen public schemas and matching checksums.
- Deterministic golden input/output digests.
- End-to-end UI evidence for import through export and replay.
- Accessibility and visual-regression results.
- Benchmark results and peak-memory evidence for streaming export.
- A clean diff limited to M7 work plus any explicitly preserved pre-existing user changes.

