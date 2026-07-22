# Simplified authoring prompt 1.2.2

Status: approved on 2026-07-22.

## Objective

Replace the unreliable simplified prompt with a self-contained prompt that preserves the requested case and simulation duration while producing a complete `simulation_authoring_bundle` accepted by authoring validation and deterministic preflight.

The advanced prompt remains unchanged. The Lucia source bundle is not repaired as part of this work.

## Corrections

The new prompt will align every required document field, catalog reference, action signature, allowed value, and date rule with the authoritative version 1.0 contracts. It will remove contradictory guidance from version 1.2.1, including the inclusive simulation-end rule and incorrect resource-fact encoding.

The prompt will require an explicit chronological state ledger before output. The ledger is not returned, but must track resident location and `at_home`, carried item roles, and paired entity state. It will enforce these invariants:

- `leave_home` only while at home and `enter_home` only while away;
- every `put_item(role)` is preceded by a still-active `take_item(role)`, including across activities;
- `open/close` and `activate/deactivate` use identical targets in a balanced order;
- purchase acquisition and storage use the same carrying role;
- process bindings cover every used `(residentId, intent)` pair exactly once;
- process graphs contain each component's required action sequence in order.

## Integrated guide

The guide will identify the corrected prompt as `1.2.2-simplified` and explain that it preserves the requested duration but still requires application validation. The advanced prompt and Advanced split-document importer remain available.

## Verification

Static tests will assert versioning, required fields, exact state-invariant instructions, and removal of known contradictory rules. A two-day case will be generated or assembled from the prompt's prescribed output pattern, ingested through the public authoring service, fully materialized, and checked for execution trace and sensor artifacts. Frontend tests, Python tests, build, and browser tests remain required.

No commit will be created without explicit user authorization.
