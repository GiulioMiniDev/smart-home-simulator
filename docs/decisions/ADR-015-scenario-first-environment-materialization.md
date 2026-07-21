# ADR-015: Scenario-first deterministic environment materialization

- **Status:** accepted and implemented in M6.1
- **Date:** 2026-07-21

## Context

The external-LLM authoring flow currently publishes a valid scenario and personal process
package, while M4 deliberately requires a separately authored executable home. This is
correct at the contract boundary but incomplete as a first-run product workflow. The
accepted `mario_rossi_2026_10_30_ingested` case demonstrates the gap: scenario, behavior
and compilation pass, but its LLM-selected home identifier has no corresponding home
artifact and its seventeen resources have no concrete bindings.

For the present research objective, the exact aesthetic layout is not primary input. It is
a controlled nuisance variable needed to make movement and sensor projection executable.
Sensor topology and placement remain important because they directly affect observable
PIR sequences and downstream comparisons.

## Decision

Adopt a scenario-first default workflow. After deterministic ingestion of scenario and
behavior, an application service will materialize an executable home from their declared
locations, resources, capabilities, mobility constraints and seed using an explicit,
versioned home-generation policy. It will produce the existing frozen `home_model 1.0.0`
plus a new versioned generation report; M4 remains the authoritative validation and
binding gate.

A second deterministic service derives a `sensor_model 1.0.0` from the resolved
simulation bundle and a separately versioned sensor-deployment policy. Initial policies
will distinguish at least minimal, room-coverage and dense deployments. Policy names must
not claim empirical similarity to CASAS until M9 calibration supports that claim.

The default user path becomes:

```text
external LLM response
    -> deterministic ingestion
    -> scenario + personal process package
    -> deterministic home materialization
    -> M4 bundle gate
    -> deterministic sensor deployment
    -> M5 simulation
    -> M6 observable log + separate oracle
```

Imported or manually designed homes and custom sensor models remain supported overrides.
Neither home nor sensor generation may call an LLM at runtime, silently repair an accepted
scenario, bypass M4/M6 validators or mutate the frozen public contracts.

The end-to-end acceptance case is
`generated/mario_rossi_2026_10_30_ingested`: starting only from its two ingested JSON
artifacts and explicit generation policies, the product must create a valid home, bind all
required resources, create a valid sensor deployment, simulate and publish the complete
M5/M6 artifact set without hand-editing JSON.

## Consequences

- A researcher can reach a first simulation without drawing a house or authoring a home
  contract manually.
- Scenario and process requirements, rather than unconstrained LLM invention, determine
  the minimum executable environment.
- Same accepted inputs, policy versions and seed must produce identical home and sensor
  artifacts and reports.
- Generated geometry and sensor deployment become explicit experimental provenance and
  must remain fixed when comparing runs.
- The M7 visual editors become optional review/customization surfaces, not prerequisites
  for first execution.
- M9 remains responsible for testing and calibrating statistical realism against real
  datasets; structural validity must not be described as empirical fidelity.

## Implemented resolution

M6.1 freezes `compact-grid 1.1.0`: primitive room locations form an adjacent metric row;
external/transit locations are disjoint regions joined by explicit transport links.
Composite locations bind to the ordered union of their primitive members. Scenario
resources retain their identifiers as concrete entities; generated regional service
entities provide only the remaining role-based capabilities. Every generated artifact is
then rejected or accepted by the unchanged M4 gate.

Sensor policy `1.1.0` exposes `minimal`, `room_coverage` and `dense`. PIR coverage is
contained in exact source-home regions; movement crossings and motor actions at resolved
interaction points produce held pulses with deterministic irregular retrigger intervals.
Contacts are derived from the concrete providers selected by M4, including a generated
entrance door. Temperature is sampled every fifteen minutes, quantized to 0.5 °C, follows
a deterministic daily component and incorporates active-source response deltas. Error
probabilities are explicit policy values and default to zero. CASAS Aruba is used only for
a scale sanity check; no preset claims completed empirical calibration.

`run-synthetic` publishes a workspace only after compilation, M4 binding, M5 execution
and M6 projection all succeed. The manifest hashes seventeen source, policy, report and
data artifacts. Existing output directories are refused and a failed staging directory
is removed. Stable identity is derived from frozen source identifiers, policy versions,
seed and canonical digests.

Reusable physical homes remain supported as M4 overrides. Separating a reusable physical
shell from scenario-specific bindings, and merging independently authored residents into
one physical home, remain explicit M7/M8 design work; neither is required for the complete
single-scenario M6.1 workflow.
