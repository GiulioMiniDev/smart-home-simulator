# Downstream contracts

These contracts define boundaries for future milestones without fixing their implementation.

## Canonical plan

Produced only from a valid and compilable scenario under contract `1.0.0`. It resolves time windows, dependencies, optional selection, resident conflicts, commitments, resources and daily contingency patches. It preserves links to every source activity and is frozen by ADR-003.

## Personal ADL process package

Produced during external authoring and accepted only after deterministic structural,
graph and scenario-compatibility validation. It resolves every resident and activity
intent to one personal process model for the applicable context. It defines possible typed
action flow, not executed choices or timestamps, and is frozen by ADR-004.

## Simulation bundle

Milestone 4 must bind one accepted scenario, its canonical plan, one accepted personal
process package and one executable home model through versions and semantic digests. No
action may remain unresolved when the bundle is accepted.

## Execution trace

Produced by the complete simulator from a fully resolved simulation bundle. It records
actual activities, typed actions, start and end times, state changes, interruptions,
substitutions, movements and spatial trajectories. It is the authoritative source for
what happened.

## Observable sensor log

Produced by sensor models from the execution trace. It contains only device-observable fields. Resident, activity and causal identifiers belong in a separate oracle mapping.

## Dependency rule

Downstream modules may consume accepted upstream artifacts. Upstream modules must not
import downstream implementations. In particular, scenario and behavior validation must
never import the compiler, simulator, geometry or sensors.
