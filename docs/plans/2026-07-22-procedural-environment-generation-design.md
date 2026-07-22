# Procedural environment generation and configuration

## Status

Approved on 2026-07-22.

## Problem

The current `compact-grid` materializer turns scenario locations into equal rectangular regions
ordered in two rows. Domestic rooms are connected according to JSON order, external sites are
drawn in the same metric space, no obstacles are generated, and unresolved domestic capabilities
are assigned to generic environment-service entities. The application couples home generation,
sensor deployment, and the first simulation run, so the researcher cannot inspect and configure
the generated environment before execution.

The React plan renderer also lost the physical resource symbol system from the M4 acceptance
viewer. It draws every entity as the same provider node and does not distinguish physical
resources, routing obstacles, logical providers, and external topology.

## Goals

- Generate a credible, fully furnished home from accepted scenario and behavior inputs.
- Make generation scenario-aware, deterministic for a seed, and meaningfully different across
  seeds.
- Place valid and useful sensors by default.
- Let the researcher edit and validate the generated home and sensors before simulation.
- Publish the home and sensor models as one compatible environment revision.
- Run the simulation against the exact published artifacts without regenerating them.
- Preserve the frozen `HomeModel` and `SensorModel` runtime contracts.

## Non-goals

- Photorealistic interior design or decorative 3D rendering.
- Arbitrary diagonal or free-form architecture.
- A heavyweight general constraint solver in the first implementation.
- LLM calls during environment generation or simulation.
- Treating display-only coordinates as routing geometry.

## Product flow

The authoritative workflow becomes:

```text
import accepted authoring
  -> generate environment draft
  -> inspect and edit home, furnishings, resources, and sensors
  -> validate and publish the compatible environment pair
  -> run the simulation with the published home and sensor artifacts
```

Generation never starts a simulation. The old `Generate home, sensors and first run` action is
removed.

The primary action is `Generate environment`. It works with recommended defaults and exposes an
optional compact configuration panel:

- archetype: `auto`, `apartment`, or `house`;
- size: `compact`, `standard`, or `spacious`;
- furnishing density: `essential`, `complete`, or `dense`, with `complete` as default;
- sensor preset: `minimal`, `room_coverage`, or `dense`;
- seed and `New seed` action.

`New variant` replaces the current draft. If the draft contains unpublished manual changes, the
application asks for inline confirmation next to the command. A failed generation never replaces
the current draft.

## Architecture

Use a deterministic staged procedural pipeline rather than extending `compact-grid` in place.
Each stage has a versioned input/output boundary and uses a named random stream derived from the
root seed. This keeps unrelated changes stable. Changing the sensor preset must not change the
floor plan, and changing one room furnishing kit must not reshuffle other rooms.

Example stream names include:

```text
layout:program
layout:packing
layout:doors
furnishing:<region-id>
resources:binding
sensors:pir
sensors:contact
sensors:temperature
```

The pipeline stages are:

1. scenario requirement analysis;
2. domestic program and adjacency graph;
3. orthogonal floor-plan construction;
4. doors, connections, and local navigation;
5. complete room furnishing;
6. operational resource and capability binding;
7. interaction-point and clearance validation;
8. sensor deployment;
9. authoritative validation and bounded deterministic retries.

The pipeline emits the existing authoritative home and sensor models plus a generation report.
The report records the root seed, policy version, catalog versions, named stream scheme,
archetype, accepted attempt, rejected-attempt diagnostics, counts, and artifact digests.

## Scenario requirement analysis

The analyzer reads scenario locations and resources, scheduled activity locations, process-model
actions, action-catalog capability requirements, and literal semantic roles. It produces a
normalized environment program containing:

- required domestic room roles;
- optional room roles allowed by the selected size and archetype;
- external locations and transport relationships;
- required operational resources;
- required entity capabilities and semantic roles;
- sensor-relevant state transitions and environmental sources.

Input order must not influence topology. IDs are sorted only where stable deterministic ordering
is needed after semantic grouping.

## Domestic program and topology

The program generator selects an archetype compatible with the scenario and policy. `auto` uses
scenario attributes when available and otherwise chooses deterministically from valid archetypes.

Adjacency rules encode domestic conventions rather than JSON order. Examples include:

- entrance connected to a hall or circulation space;
- kitchen adjacent to the living or dining area;
- bathroom reachable from circulation and near the sleeping zone;
- bedroom separated from the entrance where footprint permits;
- utility functions placed near kitchen or bathroom service zones;
- balcony or garden connected to an appropriate domestic region.

All domestic regions must be reachable from the entrance. External locations remain part of the
authoritative environment topology for travel, but the application renders them in a separate
topological projection rather than as rooms in the domestic metric plan.

## Orthogonal floor-plan construction

The layout stage packs rectangular rooms and limited L-shaped rooms into a credible orthogonal
footprint. Variation comes from topology, dimensions, orientation, circulation, furnishing
variants, and seed, not random diagonal walls.

Candidate plans must satisfy:

- non-overlapping interiors;
- legal shared boundaries for local doors and passages;
- minimum room dimensions and circulation width;
- entrance reachability;
- sufficient wall and floor area for required furnishings;
- a valid obstacle-free route to every required interaction point.

Generation tries a bounded number of deterministic candidates. A candidate is rejected with
structured diagnostics, not silently repaired after publication.

## Furnishing catalog

Add a versioned catalog of physical environment elements. Each catalog entry declares:

- stable type and visual symbol ID;
- compatible room roles;
- size range, footprint, and clearance envelope;
- placement preference such as wall, corner, or free-standing;
- whether the footprint blocks routing;
- entity capabilities and semantic roles;
- interaction-point rules;
- compatible or recommended sensor types;
- optional furnishing groups and mutual-exclusion rules.

The default `complete` density gives every room a plausible full furnishing kit. Examples include
bed, bedside tables, wardrobe, washbasin, toilet, shower, kitchen counters, sink, refrigerator,
stove, table, chairs, sofa, storage, and media furniture where the program permits them.

Every generated physical element is authoritative. An interactive or stateful element becomes a
specific home entity. A routing-blocking element also receives obstacle geometry. Non-operational
furniture may have no capabilities, but it remains an explicit entity or obstacle and has a known
visual symbol. No domestic requirement may be satisfied by `generated_environment_service`.

## Operational binding

Required roles are resolved against specific catalog elements. For example:

- `shower` resolves to a shower fixture;
- `vacuum_cleaner` resolves to a movable vacuum entity;
- `food_preparation_area` resolves to a suitable counter or table;
- `consumption_area` resolves to a table with usable seating;
- `home_exit` resolves to the entrance door.

Scenario resources receive normal resource bindings. Generated physical providers not declared as
scenario resources can still satisfy action capability bindings through explicit home entities.
If no catalog element can satisfy a required role, generation fails with a structured missing-role
issue.

## Interaction points and routing

Interaction points are placed from catalog rules after footprints are final. Each point must be
inside its region, outside obstacles, reachable with the configured resident clearance, and close
enough to the object it operates. Door approaches and furnishing clearances are reserved before
optional furniture is placed.

The generator validates reachability from the entrance to every domestic room and required
interaction point. Furniture placement is rejected if it blocks the only route or makes an
operational resource unusable.

## Sensor deployment

Sensors are deployed after the home and furniture are stable. Sensor streams are independent from
layout and furnishing streams.

- PIR sensors are placed for useful room coverage, outside obstacles, with coverage contained in
  assigned regions.
- Contact sensors attach to semantically appropriate entities such as entrance doors,
  refrigerators, cabinets, and appliances with observable state transitions.
- Temperature sensors are assigned to valid regions and reference relevant heat-source entities.
- Dense presets may add redundant observations, but never invalid or semantically meaningless
  devices.

The generated sensor model must pass the existing sensor and home compatibility gates before it is
offered as a valid draft.

## Application services and data flow

Split the current materialization operation into three explicit workflows:

### GenerateEnvironment

Consumes accepted scenario and process-package artifacts plus generation policy and seed. It runs
the procedural home pipeline and sensor deployment and produces an environment draft and report.
It does not compile or execute a simulation.

### PublishEnvironment

Validates and publishes the home and sensor models atomically as one compatible environment
revision. The revision records both artifact IDs and the generation or manual-edit provenance.
Publishing neither queues nor runs a simulation.

### RunSimulation

Consumes scenario, process package, published home artifact, and published sensor artifact. It
builds the simulation bundle, executes it, projects sensors, and publishes results. It must reject
missing, stale, or incompatible environment artifacts and must never regenerate the home or
sensors.

## Editor design

The editor treats home and sensors as one compatible draft with shared undo/redo and dirty state.
The desktop layout uses the floor plan as the main surface, a compact toolbar, and one persistent
inspector. Narrow layouts place the inspector below an horizontally inspectable plan.

Layers are independently visible and keyboard operable:

- rooms and local connections;
- routing obstacles;
- physical furniture and resources;
- logical capability providers;
- interaction points;
- sensors and coverage;
- active validation references.

The external-location topology is displayed separately from domestic metric geometry. Selection
preserves object identity across canvas, structured lists, validation issues, and simulation
replay.

The toolbar supports adding and removing rooms, doors, furnishings, resources, and sensors. The
inspector exposes appropriate position, dimensions, rotation, type, room assignment, capability,
and sensor fields. Physical resources use the shared SVG symbol system. Missing symbols are
blocking errors rather than silent omissions.

`Publish environment` atomically validates the pair. `Run simulation` is disabled until a valid
environment revision is current and the editor has no unpublished changes.

## Error handling

- Failed generation leaves the existing draft unchanged.
- Exhausted layout attempts return structured candidate diagnostics.
- Missing semantic roles name the action, capability, and unresolved role.
- Geometry and routing issues reference the affected region, door, obstacle, or entity.
- Sensor issues reference and select the affected sensor.
- Blocking errors prevent publication and simulation.
- Non-blocking warnings remain visible in the environment report and editor.
- Runs reject environment artifacts that do not belong to the selected compatible revision.

## Acceptance criteria

- The same scenario, behavior package, policy, catalog versions, and seed produce identical bytes
  and digests.
- Different seeds produce meaningfully different topology, dimensions, orientation, or furnishing
  while preserving semantic requirements.
- Every domestic room is reachable from the entrance.
- Doors, routes, and interaction points do not intersect obstacle interiors.
- Every required operational role has a specific physical provider.
- No domestic provider uses `generated_environment_service`.
- Every physical object has a catalog symbol and every routing-blocking object has a coherent
  obstacle footprint.
- Generated PIR, contact, and temperature sensors satisfy their semantic and geometric contracts.
- A run records and uses the exact published home and sensor digests.
- Domestic geometry and external topology are visually distinct.

## Verification strategy

- Unit tests cover requirement extraction, adjacency, packing, furnishing, binding, clearance,
  sensor placement, and report construction.
- Property-based tests exercise many seeds and assert geometry, reachability, binding, and sensor
  invariants.
- Golden tests cover at least one apartment and one house with fixed seeds.
- Diversity tests prove that a seed set does not collapse to one topology or furnishing layout.
- Routing tests exercise narrow clearances and optional-furniture rejection.
- Visual regression tests cover desktop and narrow editor layouts and all layer states.
- An end-to-end Tommaso test imports the accepted authoring bundle, generates an environment,
  edits it, publishes it, runs it, and verifies artifact digests and replay.
- A regression test explicitly rejects the former two-row `compact-grid` domestic layout.
- Generation uses a bounded attempt and time budget and exposes rejected-attempt diagnostics.

## Migration

Existing imported manual home and sensor models remain supported. Existing completed runs remain
replayable because their embedded artifacts are immutable. The current `compact-grid` policy can
remain readable for provenance but is removed from the application default and cannot power the
new `Generate environment` action.

