# Authoring preflight and failed-run diagnostics

Status: approved on 2026-07-22.

## Scope

This change implements only two safeguards:

1. A deterministic authoring preflight that rejects process sequences whose action preconditions are provably false before a home or run is created.
2. Structured failed-run diagnostics persisted in job events and presented in the run UI without requesting unavailable execution evidence.

Repairing the Lucia source bundle and changing either authoring prompt are explicitly out of scope.

## Deterministic preflight

The preflight belongs to the authoritative authoring validation service so the web application, CLI, and future callers receive the same result. It runs only after scenario compilation and behavior compatibility validation succeed.

The validator symbolically executes the selected process model for each canonical activity in chronological order. It tracks deterministic facts used by the action catalog, including resident presence/location, carried resource roles, and resolvable entity state. Facts have three states: known value, known absence, or unknown. A precondition becomes an error only when it is definitively false; unknown facts remain admissible so runtime-dependent behavior is not rejected prematurely.

Every rejection uses a stable `DETERMINISTIC_PRECONDITION_FAILED` code and includes the activity, process model, action node, action type, fact, operator, expected value, and inferred actual state. Paths identify the offending process node inside `personalProcessPackage`.

## Structured failures

Materialization gates raise a typed failure carrying the phase and normalized issues from the failed report. The worker appends these issues as durable `issue` job events before marking the job failed. Existing SQLite event storage is sufficient, so no schema migration is required. Unexpected exceptions retain the current generic fallback.

The job detail API already returns persisted events; no additional endpoint is needed.

## Failed-run UI

Diary, timeline, observations, and replay are execution evidence and are requested only for completed jobs. Failed, cancelled, interrupted, queued, and running jobs do not call those endpoints.

For a failed job, the Summary tab displays a diagnostic panel built from structured issue events, with the job error as a fallback. The panel explains that execution evidence was not published and shows phase, code, message, path, and available diagnostic details.

## Verification

Tests cover deterministic double-departure and carrying-role mismatches, preservation of unknown facts, durable structured failure events, API delivery, and the absence of evidence requests for failed jobs. The existing Python, frontend, build, and browser suites remain the acceptance gate.
