# Executable home and binding contract 1.0.0

## Authority and scope

Milestone 4 turns the symbolic locations, resources and capability roles of the frozen
scenario and behavioral contracts into one executable metric environment. It does not
advance simulation time, choose process branches, mutate state or emit sensor readings.

The public artifacts are `home_model`, `environment_validation_report` and
`simulation_bundle`, all at schema version `1.0.0`. JSON field names use camel case and
all models remain strict-by-default. A bundle is published only after every upstream gate,
spatial check, route check and action binding succeeds; failure produces only a complete
report.

## Spatial model

Coordinates are local Cartesian metres with `x` east and `y` north. Every traversable
room, outdoor area and external site has a simple polygon. Obstacles are polygons strictly
contained by one region. Interaction points identify valid resident approach positions.
Connections join two regions with distinct endpoint portals:

- `doorway` and `passage` links are traversed by walking;
- `transit` links have an explicit metric distance and use the frozen urban transport
  speed of 8 m/s for M4 duration calculation;
- direction, width and optional mobility-profile access are explicit.

Local links must connect touching regions and their portal separation cannot exceed the
declared opening width. A resident may traverse a connection only when both endpoint
regions are traversable, the mobility profile is allowed, the direction is valid and the
opening is at least twice the resident body radius. Interaction points reserve their full
approach radius inside obstacle-free region space.

Regions may touch but their interiors may not overlap. Obstacles and a resident's body
radius are removed from the free space before routing. All locations in the scenario,
including composites, bind to one or more concrete regions and one deterministic anchor.

## Navigation and kinematics

The route planner first runs weighted Dijkstra over the region/connection graph. Within
each visited region it constructs a deterministic visibility graph from the start, target
and free-space vertices, then runs weighted Dijkstra again. A segment is accepted only
when the eroded free-space polygon covers it, so returned pedestrian paths do not cross a
wall or buffered obstacle.

Walking speed comes from `resident.profile.mobility.walkingSpeedMetersPerSecond`, bounded
by the home's declared minimum. Body radius and posture-transition durations come from the
home model. A route contains ordered waypoints, traversal modes, metric distance and a
duration in seconds and can therefore be timestamped by Milestone 5 without inventing
kinematics.

## Capability and action binding

Each environment entity declares a concrete region, required interaction point, initial
state, access constraints and typed capabilities. A capability can expose literal roles
and must expose a non-empty closed set of supported operations; an empty list is never a
wildcard. For each activity and action node, the binder:

1. resolves literal, variable, actor, intent, activity-location and activity-resource
   expressions;
2. resolves the unique applicable personal process model accepted by Milestone 3;
3. filters providers by capability, role, operation and resident access;
4. prefers providers inside the activity's concrete regions, then breaks ties by entity
   identifier;
5. records the provider, interaction point and destination region in the bundle.

Initial state is executable rather than decorative: every `openable` entity declares a
boolean `open` value and every `switchable` entity declares a boolean `active` value.
Capability roles, supported operations, access lists and multi-region bindings reject
duplicates. Resident allow-lists are checked against the scenario before publication.

Resident posture control and concrete location targets are first-class providers rather
than fake household objects. Missing or ambiguous inputs never trigger a fallback.

## Bundle integrity

The bundle embeds the accepted scenario, canonical plan, personal process package and home
model. It also contains exactly four semantic SHA-256 digests, the source seed, resolved
resident kinematics and every resolved action binding. Contract validation re-computes the
digests and rejects mismatched scenario, plan, package or home identities.

The Mario acceptance bundle contains 766 bound action instances for all 173 scenario
activities. The environment gate checks all 21 location bindings pairwise for its resident,
for 441 deterministic route checks.

The golden apartment uses a central hallway connecting bedroom, bathroom, entrance,
kitchen and living room, with the balcony reachable only from the living room. Four metric
obstacles exercise clearance and visibility-graph detours. The versioned interactive
acceptance benchmark in `examples/visualizations/` renders the same room, opening,
obstacle, interaction-point and path coordinates plus all nine bound scenario resources
with a closed SVG symbol catalog. Resource display positions are explicitly visual metadata
and do not change collision geometry. The generator rejects stale digests, unknown IDs,
missing resource placements and unrepresented resource types. It exposes all 49 ordered
internal-room paths and all six domestic capability providers without inventing environment
entities. This is inspection evidence for the contract, not a product UI or a runtime
rendering dependency.

## Reproducibility and performance

Shapely is pinned to `2.1.2` and NetworkX to `3.6.1`. `make benchmark-environment` first
builds the complete weekly bundle and exercises every upstream gate, including
deterministic M2 recompilation. It then times a second equal build in the same process,
reusing only the M2 digest cache, and requires the M4-owned validation, route and binding
workload to complete within fifteen seconds. The benchmark reports warm-up and measured
durations separately and fails if the two bundles differ. M2 compilation is independently
executed by the `make check` compile target. This is a Milestone 4 binding benchmark, not a
Milestone 5 execution target.
