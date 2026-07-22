# Application workspace, export and replay

## Boundary and authorities

The M7 application is an orchestration and inspection surface over the frozen M1-M6.1
contracts. Domain JSON, validation reports, bundles, traces, observable logs and oracle
mappings remain authoritative. UI drafts are never executable until the corresponding
application service has passed the existing validators and atomically published a revision.

## Workspace invariants

- SQLite format `1.0.0` uses foreign keys, WAL, `synchronous=FULL` and explicit transactions.
- Database paths are relative to the workspace root; every resolved path must remain below it.
- Each artifact row records role, media type, optional schema, size and SHA-256.
- Homes group residents, revisions, runs and exports; historical revisions remain immutable.
- Job events have a per-job increasing sequence and are replayable after UI reconnection.
- Validation issues retain code, severity, stage, JSON path, details and optional graphical
  reference. The current authoritative result replaces the previous home issue set.
- Replay sessions persist verified digest, position and filters. Verification invokes M5
  semantic replay before recording a digest.
- Integrity failure enables diagnostic mode. Read and recovery operations remain available;
  new homes, artifacts, revisions, jobs and settings are refused.

## Durable job state

`queued -> running -> completed|failed|cancelled|interrupted` is the only terminal flow.
Progress is emitted by completed backend phases, not timers. Cancellation first requests
cooperative termination and then enforces a bounded stop. A cancelled, failed or interrupted
job cannot publish staging as a valid run. A backend restart converts persisted `running`
jobs to `interrupted` and appends a durable event.

## Diary and observable/oracle traversal

The diary reads the persisted execution trace. Each activity contains planned/actual time,
resident, intent, status, executed actions, movement and deviation IDs, process/node/action
identifiers, trace ID and semantic digest. It is a readable index, never a second truth source.

The observable endpoint returns only device ID/type, timestamp, measurement, value, unit and
quality. Oracle information is joined only when `includeOracle=true`, through the separately
persisted oracle mapping. Noise and false positives remain labelled and receive no invented
resident or activity cause.

## Export and archive rules

JSONL, CSV and XES writers iterate source records and write staging files incrementally.
Roles are separate for observable data, oracle, activities, actions, movements, transitions,
resources, runtime events, deviations and final state. The manifest records source bundle and
trace digests, seed, count, size, format, media type and SHA-256 for every file. Publication is
an atomic directory rename followed by catalogue registration. Any exception removes staging
and the target directory.

Workspace export uses the SQLite backup API and packages only the database, object catalogue,
runs, exports and manifest. Import verifies archive structure before extraction, opens the
candidate workspace, reconciles every catalogue entry and only then renames it into place.

## Local API security

The server binds to loopback and rejects non-loopback clients. Except for session bootstrap,
every API request requires the ephemeral workspace token. Upload and archive inputs have
explicit limits. No endpoint accepts a host filesystem path. SPA fallback serves only files
under the packaged static root.

## Acceptance matrix

The release gate includes Python coverage at 95%, frontend statement/line coverage at 95%
and branch coverage at 90%, Ruff, ESLint, TypeScript, component tests, Playwright against the
real backend on desktop/mobile, axe WCAG checks, workspace/archive corruption cases, job
cancellation, replay digest equality, oracle-leak tests, streaming export round trips, a
10,000-artifact/1,000-run benchmark and wheel/sdist launch verification.
