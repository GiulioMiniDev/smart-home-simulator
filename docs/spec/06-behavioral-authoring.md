# Behavioral authoring and personal ADL process models 1.0.0

## Responsibility and boundary

Milestone 3 defines and validates what a resident can do and how that resident habitually
performs each activity. It does not execute time, bind actions to a concrete geometric
home, generate trajectories or produce sensor measurements.

The authoring flow is external to the simulator runtime:

```text
researcher + external LLM
    -> scenario JSON + personal process package
    -> deterministic scenario and behavior validators
    -> accepted immutable authoring artifacts
```

No provider SDK or network call belongs to validation, compilation or simulation. An LLM
output has exactly the same authority and validation requirements as a manually authored
file.

## Authoritative artifacts

| Artifact | Purpose |
|---|---|
| Activity catalog | Canonical project-specific activity intents and semantics |
| Variable catalog | Typed personal, state, day and derived-calendar variables |
| Action catalog | Closed vocabulary of typed atomic actions and parameters |
| Personal process package | Resident-specific process graphs and bindings to intents |
| Behavior validation report | Deterministic structural, graph and compatibility result |

Dataset labels may be recorded in `externalMappings` for analysis. They never determine
runtime identity or replace the project activity `intent`.

Every activity-catalog entry declares ordered semantic `components`. This is the
authoritative decomposition of compound project intents: for example, preparing and
eating breakfast contains both `prepare_food` and `consume_meal`. Every bound process
model declares `implementedComponents`, and validation requires exact equality. A model
therefore cannot satisfy coverage merely by carrying the right intent label. The catalog
also defines the required typed action multiset for each component; the validator checks
that the bound graph actually contains its ordered action sequence and exposes an explicit
movement action. Each intent also lists the personal, state, day and calendar variables
that may legitimately affect its personal models.

## Process graph semantics

A process model contains nodes and directed edges. Node kinds are `start`, `end`,
`action`, `choice`, `parallel_split`, `parallel_join` and `loop`.

- one and only one start node exists;
- at least one end node exists;
- all nodes are reachable from start and can reach an end;
- action nodes use an action from the frozen action catalog;
- choice branches have one default and conditions on all other branches;
- parallelism is explicit through split and join nodes;
- a cycle is valid only when it passes through a loop node with finite `maxIterations`;
- arguments are typed value expressions, not embedded executable text.

Every action node has a positive `durationWeight` and may additionally impose an absolute
`duration` range. During execution, concrete movement and capability-operation times from
the Milestone 4 binding are reserved first; the remaining compiled activity interval is
distributed deterministically among unresolved nodes in proportion to their weights and
subject to any declared range. This preserves the canonical activity envelope without
leaving the later engine to invent an allocation rule.

The graph is an executable contract for Milestone 5. It is not an execution trace: it
contains possible paths, while the trace will record the one path actually executed.

## Personal binding resolution

Each binding associates a resident and scenario `intent` with one process model. Optional
applicability predicates use variables from the variable catalog. Resolution is
deterministic:

1. select bindings with the activity actor and intent;
2. evaluate applicability against the resident and day context;
3. prefer exactly one applicable non-fallback binding;
4. otherwise require exactly one applicable fallback binding;
5. reject missing or ambiguous resolution.

Every activity in the source scenario, including conditional and fallback activities,
must resolve during compatibility validation.

## Variable resolution

Variable identifiers are globally unique and each fixes one scope and one source path;
there is no cross-scope name fallback. Resident-profile and initial-resident-state values
are resolved per resident, day values per date, and calendar values are derived from the
scenario date (`weekday`, Monday = 0) and month (`season`). Required variables must resolve
for every applicable resident or day. Optional missing variables make their condition
false except for `not_exists`.

At simulation start the scenario initial state is authoritative. After the clock starts,
the current executed state supersedes that initial value for state-scoped variables;
profile, day and derived-calendar values remain immutable. This is the only precedence
rule and prevents an authoring artifact from silently shadowing runtime state.

The distributed catalog covers personal demographics and mobility, household and health
profile, fatigue/hunger/stress/social state, food and medication state, workday/holiday,
weather, weekday and season.

## Value expressions

Action arguments may be literal values or obtain their value from a declared variable,
the activity location/resource list, the activity intent or the actor. The validator
checks parameter names, static types, allowed values and references already owned by the
scenario. Environment-entity and capability roles remain symbolic until Milestone 4,
which must bind every one of them before simulation.

The action catalog also declares, for every action, typed parameters, required
capabilities and default precondition/effect templates. Templates use parameter
placeholders and are resolved only after Milestone 4 has selected concrete entities.
Node-level preconditions and effects may specialize the personal process but cannot
replace the catalog contract. “Atomic” here means one indivisible transition or sustained
interval in the execution trace; a sustained semantic action such as `consume` or
`perform_work` is surrounded by the movement, posture and object interactions needed at
the selected sensor granularity and may not encode a conjunction of ADLs.

## Distributed contracts

The public Draft 2020-12 schemas are:

- `activity-catalog-1.0.0.schema.json`;
- `variable-catalog-1.0.0.schema.json`;
- `action-catalog-1.0.0.schema.json`;
- `personal-process-package-1.0.0.schema.json`;
- `behavior-validation-report-1.0.0.schema.json`.

The official prompt templates are versioned in `prompts/`. JSON is authoritative. Mermaid
may be generated later as a visual projection but is neither accepted input nor a runtime
dependency in version `1.0.0`.
