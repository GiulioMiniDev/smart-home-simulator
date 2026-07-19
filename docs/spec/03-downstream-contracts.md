# Downstream contracts

These contracts define boundaries for future milestones without fixing their implementation.

## Canonical plan

Produced only from a valid and compilable scenario under contract `1.0.0`. It resolves time windows, dependencies, optional selection, resident conflicts, commitments, resources and daily contingency patches. It preserves links to every source activity and is frozen by ADR-003.

## Execution trace

Produced by the simulator from a canonical plan. It records actual start and end times, state changes, interruptions, substitutions and later spatial traces. It is the authoritative source for what happened.

## Observable sensor log

Produced by sensor models from the execution trace. It contains only device-observable fields. Resident, activity and causal identifiers belong in a separate oracle mapping.

## Dependency rule

Downstream modules may consume accepted upstream artifacts. Upstream modules must not import downstream implementations. In particular, validation must never import the compiler, simulator, geometry or sensors.
