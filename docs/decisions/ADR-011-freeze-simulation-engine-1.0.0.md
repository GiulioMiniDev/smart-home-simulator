# ADR-011: Freeze simulation engine and execution trace 1.0.0

- **Status:** accepted
- **Date:** 2026-07-21

## Context

Milestone 5 must turn a fully resolved bundle into authoritative ground truth without
conflating plans, runtime reality or future sensor observations. The execution must be
deterministic, spatially valid, causally inspectable and complete for the entire frozen
action vocabulary.

## Decision

Freeze the M5 engine and public artifacts at `1.0.0`:

- SimPy `4.1.1` is the sole authoritative discrete-event clock;
- time is represented internally as integer microseconds from the simulation origin;
- independent PRNG streams derive from SHA-256 of the bundle seed, policy version and
  stream name;
- project-owned code interprets choices, bounded loops, parallel splits/joins, action
  preconditions/effects, atomic multi-resource acquisition, priority pre-emption,
  interruption-safe release/reacquisition and local shifts;
- the M4 navigation layer generates collision-free metric trajectories only while a
  movement action executes;
- the execution trace records activities, actions, movements, resources, runtime events,
  state transitions, causal links, deviations, daily summaries and final world state;
- a semantic digest excludes serialization accidents but covers all authoritative
  execution facts;
- deterministic replay re-executes the bundle and compares semantic digests;
- any input, execution or invariant failure returns a report and no valid trace.

The three public contracts are `execution-trace-1.0.0`, `simulation-report-1.0.0` and
`replay-report-1.0.0`.

## Consequences

- Same bundle and seed produce the same semantic digest.
- Adding future sensors cannot alter runtime-event, behavior or motion streams.
- Sensor observations remain a projection of this trace and are deferred to M6.
- Public export and an interactive replay surface remain deferred to M7; internal replay
  is already a mandatory M5 acceptance gate.
- Pymunk and a global physics tick are not dependencies of the frozen fidelity level.
