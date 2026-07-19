# Downstream contracts

These contracts define boundaries for future milestones without fixing their implementation.

## Canonical plan

Produced only from a valid scenario. It will resolve time windows, dependencies and resource assignments into a deterministic daily representation. It must preserve links to original activity identifiers.

## Execution trace

Produced by the simulator from a canonical plan. It records actual start and end times, state changes, interruptions, substitutions and later spatial traces. It is the authoritative source for what happened.

## Observable sensor log

Produced by sensor models from the execution trace. It contains only device-observable fields. Resident, activity and causal identifiers belong in a separate oracle mapping.

## Dependency rule

Downstream modules may consume accepted upstream artifacts. Upstream modules must not import downstream implementations. In particular, validation must never import the compiler, simulator, geometry or sensors.

