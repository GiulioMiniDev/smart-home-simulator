# Milestone 4 closure audit

- **Status:** complete and frozen
- **Contract version:** `1.0.0`
- **Closure date:** 2026-07-21
- **Decision record:** `ADR-009`

This audit is the terminal acceptance record for Milestone 4. Milestone 5 receives the
published simulation bundle and must not repair geometry, select substitute providers,
reinterpret symbolic roles or invent missing initial state.

## Definition-of-done evidence

| Requirement | Authoritative evidence |
| --- | --- |
| Every scenario location and resource resolves concretely | Bundle preflight plus `LOCATION_BINDING_INVALID` and `RESOURCE_BINDING_INVALID` failure tests |
| Every applicable process action has one executable binding | 766 resolved action instances covering all 27 frozen action types; unresolved providers reject the bundle |
| Every destination is reachable without crossing walls or obstacles | 441 ordered location-pair checks; deterministic topology and visibility-graph planner |
| Direction, access, clearance and traversability are enforced | Tests cover one-way links, mobility allow-lists, non-traversable regions and openings narrower than the resident diameter |
| Geometry and interaction approaches are valid | Polygon, overlap, obstacle containment, local-door adjacency, portal-width and full approach-radius validation |
| Entity state is executable | `openable` entities require boolean `initialState.open`; `switchable` entities require boolean `initialState.active` |
| Resident kinematics are complete | Walking speed, body radius, posture timings, metric path distance and duration are embedded in the bundle |
| Invalid inputs never publish a valid bundle | Structural, schema, digest, upstream-plan, behavior, home-reference and binding gates precede bundle creation |
| Contracts are independently consumable | Strict Pydantic models, three Draft 2020-12 schemas, matching SHA-256 checksum files and CLI commands |
| Output is reproducible | Two builds compare equal; the distributed golden bundle equals a fresh build; embedded artifact mutation fails digest validation |
| Visual evidence is model-faithful | Generated benchmark contains 7 domestic regions, 6 local doors, 4 routing obstacles, 9 bound physical resources, 6 domestic entities and 49 routes; stale digests, phantom IDs and missing symbols fail generation |
| Quality and performance gates pass | `make check`, coverage at least 95%, and the isolated deterministic M4 validation/routing/binding build under the 15-second target after one complete correctness warm-up |

## Golden acceptance environment

- 14 regions: 7 domestic and 7 external;
- 13 explicit connections: 6 local doors and 7 transport links;
- 4 metric obstacles and 14 interaction points with clearance;
- 13 concrete environment entities;
- 21 location bindings and 9 resource bindings;
- 766 resolved action instances and 441 route checks;
- home semantic SHA-256:
  `2e8b3257fe1c760c3b820443ff62d1824395ec40ce09e1fb5c65f616d3239ca6`.

The standalone visual acceptance benchmark is
`examples/visualizations/mario_monteverde.m4-benchmark.html`. Its displayed digest is
tested against the authoritative environment report so it cannot silently describe a
stale home model. It is rebuilt from the accepted artifacts by
`tools/build_environment_visualization.py`; no iframe, CDN, phantom entity or generic
resource placeholder remains. The nine visualized resources are exactly `bed_01`,
`shower_01`, `toilet_01`, `washing_machine_01`, `kitchen_sink_01`, `fridge_01`,
`kettle_01`, `stove_01` and `television_01`.

## Final gate

```bash
make check
```

The gate regenerates M3/M4 artifacts and schemas, verifies checksums, runs the complete
test suite and linting, validates all frozen inputs, rebuilds the golden bundle and runs
the environment benchmark. Any failure keeps Milestone 4 closed to downstream work.
