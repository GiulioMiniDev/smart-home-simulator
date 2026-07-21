# ADR-015: Scenario-first deterministic environment materialization

- **Status:** accepted direction; implementation pending in M7
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

A second deterministic service will derive a `sensor_model 1.0.0` from the resolved
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

## Open design work before implementation

M7 must resolve and record, before coding the generators:

1. the home-policy contract, layout algorithm, template vocabulary and handling of
   external locations;
2. deterministic entity/capability synthesis and conflict handling when requirements are
   incomplete or incompatible;
3. whether reusable physical-home definition and scenario-specific location/resource
   bindings become separate versioned artifacts or remain a generated composite;
4. sensor-policy parameters for density, coverage, doors, object contacts, temperature
   cadence and researcher overrides;
5. stable identity, versioning, digest and regeneration rules for generated homes;
6. multi-resident merging when accepted scenarios share one physical environment;
7. CLI/service-layer contracts and transactional workspace publication.

No unresolved item permits a nondeterministic fallback or an output presented as valid
without passing the existing authoritative gates.
