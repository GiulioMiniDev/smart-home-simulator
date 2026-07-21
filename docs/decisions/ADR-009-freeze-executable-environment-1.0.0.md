# ADR-009: Freeze executable environment and simulation bundle 1.0.0

- **Status:** accepted
- **Date:** 2026-07-21

## Context

Milestone 5 must receive a world in which every behavioral action already has spatial and
capability meaning. Deferring geometry, path feasibility, concrete objects or symbolic-role
selection to runtime would make failures seed- and branch-dependent and would prevent a
simulation bundle from being independently valid.

## Decision

Freeze the Milestone 4 contracts and behavior at `1.0.0`:

- metric polygonal home regions, obstacles, interaction points and explicit connections;
- concrete entities, state, access constraints, operation-aware capabilities and scenario
  location/resource mappings;
- Shapely visibility-graph paths within regions and NetworkX shortest paths between them;
- resident kinematics resolved from the scenario profile and home defaults;
- deterministic action binding by capability, literal role, spatial affinity and stable
  identifier tie-break;
- a self-contained simulation bundle with four embedded upstream artifacts, semantic
  digests, seed, kinematics and resolved actions;
- three Draft 2020-12 schemas, checksum files, CLI gates, golden home, golden weekly bundle,
  benchmark and stable environment issue-code registry.

The urban transport duration default is 8 m/s. Pedestrian collision clearance equals the
resident body radius. A later contract version is required to change either policy.

## Consequences

- Milestone 5 may execute the bundle but may not silently select objects, repair topology
  or reinterpret symbolic roles.
- Invalid bundles fail before clock creation and never produce a partial valid artifact.
- External locations participate in the same connected topology through explicit transit
  links; sensor geometry remains deferred to Milestone 6.
- The frozen M1-M3 schemas and source examples are not modified.
- Interactive rendering and rigid-body physics remain outside the authoritative engine.
