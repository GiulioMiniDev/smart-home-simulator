# Scenario contract 1.0.0

## Purpose and authority

The scenario describes intended life before execution. It may be authored by a human, a rule generator or an external LLM. It must never contain executed timestamps, trajectories, sensor readings or hidden simulator outcomes.

Only documents with the exact `schemaVersion` value `1.0.0` are accepted. Unknown properties are rejected at every typed level; producer-specific data must be placed deliberately in an `extensions` or `attributes` object.

## Top-level sections

| Section | Meaning |
|---|---|
| `simulationWindow`, `timeZone`, `seed` | temporal and reproducibility boundary |
| `provenance` | author, generator/model, prompt version and review status |
| `modelReferences` | versioned activity, home and optional sensor models |
| `materializationPolicy` | daily revalidation and permitted repair ordering |
| `residents`, `externalPeople` | simulated people versus social participants |
| `locations`, `resources` | logical places and capacity-bearing objects |
| `initialState` | authoritative state at simulation start |
| `commitments` | mandatory or optional calendar intervals |
| `days.activities` | intended activities and their constraints |
| `runtimeEventCandidates` | seeded disturbances that may occur during execution |
| `declaredConstraints` | named constraints interpreted by downstream catalogs |
| `requestedOutputs` | requested products, without producing them |

## Identity and references

- Resident, external-person, location, resource, commitment, activity and runtime-event identifiers are unique in their respective namespaces.
- Resident and external-person identifiers may not collide.
- Activity identifiers are unique across the whole scenario, enabling cross-day dependencies.
- An activity actor is always a resident. Participants may be residents or declared external people.
- External people are not simulated residents and therefore do not acquire state, location or schedule-conflict checks.
- Composite locations may contain logical locations recursively, but cannot reference themselves or form cycles.
- Every reference is resolved before the scenario is accepted.

## Timing model

All timestamps are timezone-aware ISO 8601 values and their UTC offsets must agree with the declared IANA `timeZone`, including daylight-saving transitions.

An activity has:

- a `startWindow` with earliest, preferred and latest timestamps; or
- at least one dependency group; or
- fallback activation tied to another activity.

Its end is represented by either a duration range or an explicit end window. A duration range has minimum, preferred and maximum minutes. Dependency groups support `all` and `any` predecessor semantics plus minimum and optional maximum lag.

Activities must remain inside the simulation window. `allowBoundaryTruncation` is the explicit exception for an activity, such as the final night's sleep, that starts inside the requested window. Despite the legacy field name, the runtime does not cut such an activity: it completes it, extends the execution trace, and projects the completion tail to sensors. Evaluation reports must distinguish that tail from the requested analysis window.

The contract does not choose exact times inside flexible windows. That is the responsibility of the plan compiler.

## Activation, fallback and commitments

Activation modes are:

- `always`;
- `conditional`, with a structured fact condition;
- `fallback`, with a target activity and a declared trigger.

Fallback references must resolve, remain on the same day and use the same actor. Fallback chains may not target other fallbacks or form cycles.

Commitments have exact intervals, locations and participants. A linked activity must be able to start at the commitment time, include its location and not introduce undeclared participants.

## State and runtime events

Initial resident state is recorded exactly at `simulationWindow.start`. Earlier observations used to derive it can be preserved as provenance or a fact, but are not authoritative timestamps.

Conditions use a fact, an operator and, where required, a value. Activity effects are declarative state updates. Runtime-event effects are a closed set: delay a start, extend a duration, interrupt an actor, invalidate a fact or set a fact. Probabilities and amount ranges are validated, but events are not sampled in this milestone.

## Versioning and distributed artifacts

The authoritative machine-readable input contract is `schemas/scenario-1.0.0.schema.json`. It is JSON Schema Draft 2020-12 and is tested for byte-independent semantic equality with the Pydantic model output.

Contract `1.0.0` is frozen by ADR-002. Future requirements must produce a parallel version and migration path; they must not silently change what `1.0.0` means.
