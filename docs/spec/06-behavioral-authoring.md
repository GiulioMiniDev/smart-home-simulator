# Behavioral authoring and personal ADL process models 1.0.0

## Responsibility and boundary

Milestone 3 defines and validates what a resident can do and how that resident habitually
performs each activity. It does not execute time, bind actions to a concrete geometric
home, generate trajectories or produce sensor measurements.

The authoring flow is external to the simulator runtime:

```text
researcher + external LLM
    -> one simulation authoring bundle
    -> atomic ingestion into scenario JSON + personal process package
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
| Simulation authoring bundle | Pure-JSON transport envelope for one external-LLM response |
| Authoring ingestion report | Whole-response validation and canonical artifact digests |

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
weather, weekday and season. It declares 18 variables across the four scopes.

The precedence rule above describes the **runtime** semantics of an accepted scenario and is
unchanged. It does not describe how the days of a generated horizon are shaped upstream: the local
generation pipeline carries `fatigue`, `hunger`, `social_need` and a generator-internal sleep debt
across the days it emits, so that wake time, night length, naps and nocturnal events drift and
recover instead of repeating. Those dynamics run entirely **before** simulation, in the generator,
and reach the engine only as ordinary scenario content. No new variable scope and no new precedence
rule is introduced. See `13-local-generation-pipeline.md`.

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

## Catalog instance versions

The schemas above are frozen at `1.0.0`. The **catalog instances** validated by them are versioned
independently and have moved on; the schema version and the catalog-content version are not the same
number.

| Catalog | Instances | Content |
|---|---|---|
| Activity | `1.0.0`, `1.1.0`, `1.2.0` | 92 intents in `1.0.0`/`1.1.0`; **90** in `1.2.0`; 54 ordered semantic components throughout |
| Action | `1.0.0`, `1.1.0` | 27 typed atomic actions — same vocabulary in both |
| Variable | `1.0.0` only | 18 variables across four scopes |
| Reference process models | `1.1.0`, `1.2.0` | 24 models extracted from the proven `mario_rossi` package |

Each instance is derived from its predecessor by a migration script wired into `make check`
(`tools/migrate_behavior_1_1.py`, `tools/migrate_behavior_1_2.py`), so a version can be regenerated
and cannot silently drift from the code that consumes it.

### 1.0.0 to 1.1.0 — object-carrying semantics

The `1.1.0` instances do **not** extend the vocabulary. Both activity catalogs declare the same 92
intents and the same 54 components, and both action catalogs declare the same 27 action types. What
`1.1.0` changes is object-carrying semantics:

- component `travel` drops `leave_home` from its required action types, keeping only `travel_to`;
  crossing the home boundary is modeled separately by the `leave_home`/`enter_home` actions;
- `dress` gains the effect `resident.carrying.used_clothing`;
- `shop` gains the effect `resident.carrying.purchases`;
- `prepare_food` gains an `outputRole` parameter and the effect `resident.carrying.{outputRole}`.

An artifact pinned to `1.0.0` therefore keeps the original, laxer carrying semantics; one pinned to
`1.1.0` must account for what the resident is holding. This is the groundwork for Milestone 10
(object containment), not a vocabulary extension.

### 1.1.0 to 1.2.0 — a persona-neutral vocabulary

Catalog `1.1.0` inherited its vocabulary from the Mario Rossi acceptance case, which left seven
intents naming private individuals. **An intent id is the ground-truth label published in the
dataset**, so a generated persona with no sister had to reuse `call_sister_lucia` to express
"phones a relative", and the label then asserted something untrue about the simulated resident.
That is a defect in the validity of the produced data, not a naming preference.

| `1.1.0` | `1.2.0` |
|---|---|
| `call_mother`, `call_sister_lucia`, `call_friend_paolo` | `phone_call` |
| `aperitivo_with_paolo` | `social_drink_out` |
| `prepare_to_visit_mother` | `prepare_to_visit_relative` |
| `travel_to_mothers_home` | `travel_to_relatives_home` |
| `visit_mother_and_have_dinner` | `visit_relative_and_have_dinner` |

The three phone intents were already byte-identical in semantics — same `phone_call` component,
same `relevantVariableIds` — so collapsing them loses no expressive power and takes the catalog
from 92 to 90 intents. Identity of the person involved belongs in the scenario, which already
models it through `externalPeople` and an activity's `participantIds`.

The reference process models are neutralized in the same pass: their prose no longer names a
resident, nor attributes to every persona the knee osteoarthritis of the original one.

Consumers select an instance explicitly and older artifacts are untouched: the local generation
pipeline pins `1.2.0`, while anything pinned to `1.0.0` or `1.1.0` keeps validating and replaying
exactly as before. The remaining hyper-specific intents (`prepare_quick_pasta_and_salad`,
`iron_work_shirts`, `long_sunday_walk`) are a separate concern: they are narrow, but they do not
assert anything false about a resident.

`--activity-catalog-version` and `--action-catalog-version` select the instance; the CLI default
remains `1.0.0`, so an existing command keeps its previous behaviour. The local generation pipeline
requires `1.1.0`.

That pipeline draws from a deliberately **reduced alphabet**: roughly 24 sensor-distinct intents,
each an exact activity-catalog `1.1.0` intent that also has a reference process model, grouped in
twelve categories (sleep/wake, hygiene, medication, meal, cooking, chores, laundry, exercise,
outdoor, errand, leisure, social). The restriction is a measurement decision, not a modelling
limit: a fixed sensor layout could not distinguish a finer vocabulary, and habit mining needs one
comparable label space across residents. Per-persona diversity comes from which intents recur, when,
and in what sequences. See `13-local-generation-pipeline.md`.

The end-to-end transport schema is `simulation-authoring-bundle-1.0.0.schema.json`. The
current ingestion report is `authoring-ingestion-report-1.1.0.schema.json`; historical
report `1.0.0` remains frozen. They compose rather than modify the frozen scenario and
personal-process contracts.

Rejected external-LLM bundles may be wrapped in the self-contained
`authoring-repair-request-1.0.0.schema.json` contract. The request preserves the original
text, diagnostics and authoritative contracts; it never edits or publishes the rejected
bundle. A complete externally repaired bundle must pass the same ingestion gates from the
beginning.

The preferred researcher-facing prompt is the single self-contained
`generate-simulation-inputs-1.3.0.md`; prompts `1.0.0`, `1.1.0`, `1.2.0` and the focused
scenario and process templates remain available as contract documentation. JSON is authoritative.
Mermaid may be generated later as a visual projection but is neither accepted input nor a
runtime dependency in version `1.0.0`.
