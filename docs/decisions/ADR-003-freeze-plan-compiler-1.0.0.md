# ADR-003: Freeze canonical plan and compiler contracts 1.0.0

- **Status:** accepted
- **Date:** 2026-07-19

## Context

The simulator needs a reproducible schedule rather than the flexible intentions contained in a scenario. Compilation also exposes contradictions that validation intentionally cannot decide, and conditional replacements may require bounded downstream rescheduling.

## Decision

Use OR-Tools CP-SAT with integer microsecond time and the deterministic `priority-preference-1.0.0` policy described in the compiler specification. Freeze together:

- canonical plan semantics and `planVersion` `1.0.0`;
- compilation report semantics and `compilerVersion` `1.0.0`;
- their distributed Draft 2020-12 JSON Schemas and checksums;
- compiler issue codes and severities;
- OR-Tools `9.15.6755`, single-worker deterministic settings and CLI behavior;
- independent daily contingency-patch semantics.

No canonical plan is produced unless the main plan and every active contingency are feasible under the frozen policy.

## Consequences

- The downstream simulation engine, currently scheduled for Milestone 5, consumes exact planned intervals without resolving flexible windows again.
- The meaning of `OPTIMAL` is precise: globally optimal optional selection plus proven-feasible deterministic preference locking, not global minimum deviation.
- A solver upgrade or changed tie-break policy requires an explicit compiler-version decision and regenerated golden plans.
- Simultaneous runtime contingencies remain a simulator revalidation concern.
- The scenario and validation contracts remain unchanged and frozen at `1.0.0`.
