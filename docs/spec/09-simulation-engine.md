# Complete simulation engine

## Boundary

The M5 engine consumes one validated `simulation_bundle` and produces either an
authoritative `execution_trace` plus a successful `simulation_report`, or only a failed
report. A failed run never publishes a partial trace as valid. Sensor generation, public
dataset export and visual replay are downstream responsibilities.

## Authoritative time and randomness

SimPy owns event ordering. The project exposes time as aware datetimes and stores exact
integer microsecond offsets internally. No global fixed-frequency tick exists. Movement
is a bounded event episode and its waypoint timestamps derive from metric path length and
resident kinematics.

Every stochastic concern uses a separate named stream. The sub-seed is SHA-256 of:

```text
bundle seed : sha256-named-streams-1.0.0 : stream name
```

Runtime-event occurrence, occurrence time and each sampled amount use distinct names.

## Process execution

One applicable personal process model is already resolved by M4 for each activity. M5:

1. evaluates live activity preconditions;
2. acquires the actor and every required resource as one atomic allocation;
3. traverses the graph from its unique start node;
4. selects the first satisfied conditioned edge or the declared default;
5. bounds loop back-edges by `maxIterations`;
6. executes parallel branches concurrently and rejoins them;
7. checks catalog and node preconditions before every action;
8. applies catalog, node and activity effects only after successful completion;
9. releases every resource in reverse acquisition order.

Unknown facts are false. The corrected acceptance scenario declares initial sources and
producers for every fact it evaluates. There are no implicit action aliases, idempotent
exceptions or ignored handlers.

## Runtime events and repair

Triggered events are evaluated when their trigger activity actually starts. Other events
use a sampled instant inside their eligible window. Delay and extension amounts are in
minutes as defined by the scenario contract and become exact microseconds. Interruptions
suspend the active activity, preserve its child action processes, record their cause and
resume after the sampled interval.

Actor contention shifts later work in virtual time and is recorded as local repair. A
declared contingency replaces an activity when its materialization-time condition is
known false. Optional live-precondition failures are dropped with an explicit deviation;
mandatory failures terminate the run.

## Spatial and resource invariants

Every movement starts at the resident's authoritative position and uses the M4 route
planner. Trace validation independently verifies that waypoints remain inside their home
regions, avoid obstacle interiors and have monotonic timestamps. A project-owned
coordinator grants complete multi-resource sets atomically, queues requests by priority
and stable request order, and may pre-empt only lower-priority allocations. A pre-empted
activity releases its whole set, suspends its live child actions, waits to reacquire the
same set atomically and then resumes. Every requested, acquired, pre-empted and released
capacity change is traced. Resources must return to full availability at the end; no
resident may retain one.

## Trace and replay

The trace separates planned and actual intervals and links actions, movements, state
changes, resources, events and deviations through stable identifiers. The semantic digest
covers all authoritative runtime arrays and final state. Replay is successful only when a
fresh execution of the original bundle yields the same digest.

The JSON Schemas are Draft 2020-12 documents with checksum sidecars. CLI publication uses
temporary sibling files and atomic rename for completed outputs.
