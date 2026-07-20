# Simulation engine blueprint

- **Status:** design note for future implementation
- **Date:** 2026-07-20
- **Scope:** Milestones 3–9

## Recommended decision

Use a hybrid, multi-resolution simulation architecture with:

- **SimPy** as the authoritative virtual clock and discrete-event engine;
- domain-owned Python models and hierarchical state machines for residents and the home;
- **NetworkX** for room and doorway topology;
- **Shapely** for planar geometry, obstacles and sensor coverage;
- a small project-owned kinematic layer for timestamped human trajectories;
- **Pymunk** only when actual 2D rigid-body physics is required;
- independent sensor models that project the authoritative execution trace into an
  observable log.

This is a proposed implementation direction, not a frozen contract or an implemented
feature. The relevant choices must be converted into ADRs before Milestone 4 freezes the
executable environment and Milestone 5 implements the complete engine.

The important choice is architectural rather than merely technological: no single
library should own planning, simulated time, human behaviour, spatial geometry, physical
interactions and sensor observations.

## Intended end state

The completed project should be able to:

1. compile a structured scenario into a feasible canonical plan;
2. execute that plan in virtual time while evaluating live preconditions;
3. sample reproducible runtime disturbances, delays and interruptions;
4. maintain the state of every resident, resource and environmental fact;
5. move residents through a topological and geometric home model;
6. generate timestamped spatial trajectories only when movement occurs;
7. execute atomic interactions with doors, furniture and appliances;
8. derive noisy device observations from ground truth;
9. export observable logs separately from oracle and causal information;
10. simulate weeks, years and Monte Carlo replications faster than real time.

## Responsibility split

| Layer | Recommended implementation | Responsibility |
|---|---|---|
| Plan compilation | existing OR-Tools CP-SAT compiler | decide intended activity placement and feasible resource usage |
| Virtual time | SimPy | order events, wait, interrupt, pre-empt and coordinate shared resources |
| Resident behaviour | project-owned Python domain classes | decide state transitions and reactions to events |
| Topology | NetworkX | represent rooms, doors, connectivity and weighted routes |
| Geometry | Shapely | represent polygons, walls, obstacles and sensor coverage |
| Motion | project-owned kinematic integrator | convert routes into timestamped positions, speed and posture |
| Rigid-body physics | optional Pymunk adapter | resolve physical contacts or movable objects when needed |
| Sensors | project-owned observation models | convert ground truth into device-observable events |
| Export and replay | streaming project-owned writers | persist trace, oracle mapping and sensor log without conflating them |

The expected artifact flow is:

```text
profile, habits, calendar and action vocabulary
    -> scenario JSON + personal ADL process-model package
    -> validation reports + canonical plan
    -> executable home model and fully resolved simulation bundle
    -> complete SimPy execution of activities, actions, movement and world state
    -> authoritative spatial, semantic and causal execution trace
    -> observable sensor log + separate oracle ground truth
```

Every artifact consumed by the engine is complete and valid before simulation starts.
Sensor models project the authoritative trace without changing it. Geometry and sensor
code must not become dependencies of scenario validation or plan compilation.

## Time model

### Global discrete-event time

SimPy should be the only authoritative simulation clock. It advances directly from one
scheduled event to the next instead of executing every intermediate millisecond.

Examples of global events include:

- planned or actual activity start and end;
- movement start and arrival;
- acquisition and release of a shared resource;
- precondition evaluation;
- interruption, delay or duration extension;
- fallback or contingency activation;
- door or appliance interaction;
- state and sensor transitions.

Eight hours of sleep must normally be represented by an event at sleep start and an event
at wake-up, not by hundreds of thousands of empty updates.

### Local continuous time

A fixed time step is allowed only inside a bounded episode that needs it, such as a
resident moving between rooms or interacting physically with an object.

Suggested initial policies are:

- 4–10 Hz for ordinary indoor trajectories;
- up to 20–30 Hz for a short physical interaction when lower frequency is insufficient;
- no motion updates while the resident is stationary;
- analytic intersection between trajectory segments and sensor regions whenever possible;
- adaptive sampling or interpolation for export and visual replay.

The simulation clock remains SimPy time. A motion or physics adapter consumes a bounded
virtual-time interval, emits trace segments or relevant transitions, and returns control
to the event engine.

### Why a global physics tick must be avoided

A full year at 10 Hz contains:

```text
365 * 24 * 60 * 60 * 10 = 315,360,000 ticks
```

At 60 Hz it contains approximately 1.89 billion ticks. Most of them would describe a
resident who is sleeping, sitting or otherwise stationary. This cost provides little
additional fidelity and makes output volume more problematic than event scheduling.

If a resident moves indoors for one hour per day, sampling only movement at 10 Hz gives:

```text
365 * 60 * 60 * 10 = 13,140,000 positions
```

Even this number should not automatically become 13 million output records. A compact
piecewise trajectory plus sensor boundary crossings is preferable when it preserves the
required semantics.

## Resident and world state

Human state is a behavioural and semantic model, not a responsibility of the rigid-body
engine. A resident should have explicit, inspectable state dimensions such as:

- execution: `idle`, `moving`, `performing_activity`, `interrupted`;
- activity: sleeping, cooking, eating, working and other domain intents;
- posture: standing, walking, sitting, lying;
- spatial state: current room, position, destination and active route;
- physiological state: fatigue, hunger, sleepiness or other calibrated variables;
- semantic facts: medication availability, pending tasks and scenario-defined facts;
- ownership of or waiting for resources;
- current activity, participants and interruption cause.

A hierarchical state machine is preferable to one large enumeration because these
dimensions can vary independently. State changes should be emitted into the execution
trace with their causes and timestamps.

SimPy determines **when** a transition occurs. Domain policy determines **whether and how**
the state changes. The plan is an intention; the execution trace remains authoritative for
what actually happened.

## Spatial model

### Topological layer

Represent rooms, doorways and relevant external places as a weighted graph. NetworkX can
provide reachability and shortest paths through Dijkstra or A*. Edge weights may express
distance, expected traversal time, accessibility or temporary closure.

The topological layer supports useful simulation before a detailed floor plan exists. It
also prevents the geometric layer from deciding semantic questions such as which room a
door connects.

### Geometric layer

Represent the home in metric 2D coordinates with:

- room polygons;
- walls and doorway apertures;
- static obstacles and traversable regions;
- named interaction points or zones;
- sensor positions, orientation and coverage regions.

Shapely should answer planar questions such as containment, intersection, distance and
buffering. It is not a clock, behaviour engine or rigid-body simulator.

### Navigation and trajectories

A route should be produced in two stages:

1. choose a semantic route through the room/door graph;
2. choose a collision-free geometric path inside the relevant polygons.

The kinematic layer then assigns speed, optional acceleration and timestamps. Human speed
should be sampled from seeded, configurable distributions and may depend on resident,
activity, fatigue, urgency and mobility profile.

For one resident, simple collision-free navigation is normally sufficient. Multi-resident
avoidance can be added later without changing the authoritative trace contract.

## How much physics is appropriate

A rigid-body engine should not be the foundation of human behaviour. Treating residents as
discs with mass, friction and impulses does not by itself produce realistic domestic
behaviour.

For smart-home datasets, the most important physical constraints are usually:

- residents cannot cross walls or closed doors;
- speed and travel time are plausible;
- a resident occupies exactly one valid spatial state;
- objects can be contacted only when spatially reachable;
- doors and appliances change state through explicit interactions;
- sensor coverage is evaluated against position and geometry.

Use Pymunk only if an experiment genuinely requires rigid-body collision, a movable object,
a physical door response or local contact resolution. Hide it behind a project-owned
adapter so it can be disabled or replaced without changing scenario, plan or trace
contracts.

## Sensor projection

Sensor models consume ground truth and produce observations. They must not control the
resident or contaminate observable records with activity and resident identifiers.

Examples include:

- PIR activation from entry into a coverage polygon, with hold time and refractory period;
- contact sensors from door, cabinet or appliance state transitions;
- smart plugs from explicit appliance actions and power profiles;
- humidity or temperature from activity-driven response curves;
- configurable latency, dropout, false positives, false negatives and clock jitter.

Prefer event-driven sensor evaluation. A contact sensor needs an object transition, not a
poll at every simulation tick. A PIR can often be computed from the intersection between a
trajectory segment and its coverage boundary. Dense sampling is a fallback for models that
cannot be evaluated analytically.

## Reproducibility

All stochastic behaviour must derive from the scenario seed. Independent random streams
should be derived for at least:

- runtime-event occurrence;
- duration and delay amounts;
- resident motion and speed;
- behavioural variation;
- each sensor's noise process.

Adding a new sensor must not change which runtime contingencies occur. Named or deterministically
derived sub-seeds prevent this accidental coupling.

The execution metadata should record engine and model versions, seed derivation policy,
time resolution, spatial model version and sensor model versions.

## Performance estimate for one simulated year

The acceptance week currently contains 173 activities. Repeating that density gives
approximately:

```text
173 * 52 = 8,996 activities per year
```

Even with 10–20 internal events per activity, the logical engine processes fewer than
200,000 primary events before optional spatial and sensor detail.

### Local microbenchmark

On 2026-07-20, a deliberately minimal benchmark on the current Apple M1 MacBook Air with
8 GB RAM, Python 3.12.13 and SimPy 4.1.1 processed one million sequential timeout events in
approximately 0.585 seconds, or about 1.71 million events per second.

This is not an end-to-end simulator benchmark. Real domain logic, geometry, random sampling,
validation and output serialization will dominate a completed implementation. It does show
that the duration of the virtual calendar is not intrinsically expensive.

### Expected ranges

| Fidelity level | Expected wall-clock time for one resident-year |
|---|---:|
| Activities, states and runtime events without geometry | 1–10 seconds |
| Room topology and logical sensors | 10–60 seconds |
| 2D plan, trajectories and geometric sensor projection | 30 seconds–5 minutes |
| Dense 10 Hz positions during movement | 2–15 minutes |
| Always-on 10–60 Hz global physics | tens of minutes to hours; reject this design |

These are engineering estimates, not guarantees. They must be replaced by repeatable
benchmarks as the milestones are implemented.

### Performance target

Adopt the following provisional end-to-end target:

> Simulate one year for one resident in a home with approximately 10–20 sensors in less
> than five minutes on a normal laptop, while producing ground truth and an observable
> sensor log.

A configuration without dense geometric trajectories should complete in less than one
minute. The engine should stream large outputs instead of retaining a full year in memory.

Likely bottlenecks are:

- serializing millions of records;
- non-vectorized point-in-polygon and intersection checks;
- unnecessarily dense trajectory output;
- evaluating every sensor at every movement sample;
- global rather than local physics updates;
- attempting to compile the whole year as one CP-SAT problem.

## Annual and longitudinal execution

Do not assume that an entire year should be compiled as one global CP-SAT model. Roughly
9,000 activities and their constraints may make compilation more expensive than execution,
and the year must react to state accumulated during earlier periods.

Use a rolling horizon, initially weekly:

1. load persistent state at the start of the week;
2. validate and compile the next weekly horizon;
3. execute it through SimPy;
4. persist the authoritative final state;
5. use that state to materialize or revalidate the following horizon.

Weekly boundaries are an operational default, not a semantic reset. Activities spanning a
boundary and persistent facts require an explicit handoff contract.

Independent yearly or Monte Carlo replications can run in separate processes. Do not try to
parallelize a single authoritative SimPy event queue unless measurements prove it necessary.

## Milestone implementation

`ROADMAP.md` is authoritative for scope and definitions of done. The dependency order is:

1. **Milestone 3 — behavioural authoring and personal ADL process models:** freeze the
   activity and variable catalogs, typed action vocabulary, process-model contracts,
   external-LLM prompts and deterministic validators;
2. **Milestone 4 — executable home environment and binding:** deliver topology, metric
   geometry, objects, capabilities, deterministic navigation and a fully resolved
   simulation bundle;
3. **Milestone 5 — complete simulation engine:** execute the complete process models,
   movement, actions, resources, state, interruptions and contingencies and emit one
   authoritative spatial, semantic and causal trace; no abstract-only engine is accepted;
4. **Milestone 6 — sensors:** project the complete trace into observable logs and a
   separate oracle mapping;
5. **Milestone 7 — export and replay:** persist JSONL/CSV/XES artifacts and provide
   deterministic replay and debugging;
6. **Milestone 8 — longitudinal execution:** preserve state across horizons and run annual
   and Monte Carlo simulations without requiring a runtime LLM;
7. **Milestone 9 — calibration and experimental evaluation:** compare synthetic and real
   data through a versioned, reproducible protocol.

## Alternatives considered

### Mesa as the primary engine

Mesa is useful for agent-based models, agent management, spaces, visualization and data
collection. It is not recommended as the primary scheduler here because the project already
has precise planned timestamps, few residents, asynchronous interruptions and resource
constraints that map naturally to discrete-event processes. Introducing a second scheduler
would require an explicit clock-ownership policy.

Mesa may still be evaluated for visualization or experiments involving many autonomous
agents, provided it does not own authoritative simulation time.

### Godot as the primary engine

Godot provides 2D/3D navigation, path following, avoidance, physics and interactive
rendering. It is attractive for a visual demonstrator but is not recommended as the
authoritative scientific engine because it would complicate Python integration, batch
experiments, headless reproducibility and contract testing.

A future Godot application could consume replay artifacts as a viewer instead of producing
ground truth.

### Pymunk or another physics engine as the primary engine

A rigid-body engine solves collision dynamics but does not model activities, cognition,
preconditions, resources or long-duration event scheduling. It should remain an optional
local service rather than the simulation clock.

## Open decisions before implementation

The following questions remain deliberately open:

- exact execution-trace schema and event taxonomy;
- engine time unit and timestamp conversion policy;
- hierarchical state-machine representation;
- geometric path-planning algorithm and navigation mesh representation;
- default trajectory frequency and adaptive-sampling rules;
- criteria that justify enabling Pymunk;
- sensor coverage and noise calibration;
- state handoff across rolling-horizon boundaries;
- exact dependency versions, to be pinned only when each milestone begins;
- representative end-to-end benchmark fixture and permitted output sizes.

Resolve each item before freezing the first milestone that depends on it. Spikes and
benchmarks may inform a decision, but no partial prototype is accepted as the completed
implementation of a roadmap feature.

## External references

- [SimPy documentation](https://simpy.readthedocs.io/en/latest/index.html)
- [SimPy API reference](https://simpy.readthedocs.io/en/stable/api_reference/simpy.html)
- [NetworkX shortest-path documentation](https://networkx.org/documentation/stable/reference/algorithms/shortest_paths.html)
- [Shapely user manual](https://shapely.readthedocs.io/en/stable/manual.html)
- [Pymunk documentation](https://www.pymunk.org/en/latest/)
- [Mesa documentation](https://mesa.readthedocs.io/stable/index.html)
- [Godot NavigationAgent documentation](https://docs.godotengine.org/en/stable/tutorials/navigation/navigation_using_navigationagents.html)
