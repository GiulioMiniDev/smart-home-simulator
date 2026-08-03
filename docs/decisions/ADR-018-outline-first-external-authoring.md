# ADR-018: Outline-first external authoring

- Status: accepted; contract, expander, schemas, prompt and habit ground truth have landed
- Date: 2026-08-03
- Supporting analysis: [`docs/plans/2026-08-03-compilazione-orizzonti-lunghi-diagnosi-e-partizione-design.md`](../plans/2026-08-03-compilazione-orizzonti-lunghi-diagnosi-e-partizione-design.md)
- Contract: [`hybrid_planning/outline.py`](../../src/smart_home_sim/hybrid_planning/outline.py) ·
  expander [`hybrid_planning/expander.py`](../../src/smart_home_sim/hybrid_planning/expander.py)
- Published: `schemas/horizon-outline-1.0.0.schema.json`,
  `schemas/horizon-authoring-bundle-1.0.0.schema.json`,
  `schemas/habit-ground-truth-1.0.0.schema.json`,
  [`prompts/generate-horizon-outline-1.0.0.md`](../../prompts/generate-horizon-outline-1.0.0.md)
- Example: [`examples/authoring/meredith.horizon-outline.json`](../../examples/authoring/meredith.horizon-outline.json)
- Tests: `tests/test_outline.py`, `tests/test_expander.py`, `tests/test_recurring_activities.py`
- Command: `smart-home-sim expand-outline <bundle> --output <bundle> [--ground-truth-output <path>]`
- In the application: `POST /api/homes/{home_id}/horizon-outline?seed=N` expands and imports in
  one step; the Resident context offers it beside the ordinary bundle picker

## Context

The external-LLM authoring flow asks one model response to produce a complete
`SimulationAuthoringBundle`, including every concrete day of the horizon. The first eight-month
case authored this way, `meredith-merrino-long-island-8-months-2026-2027`
(`generatorVersion 1.3.0`, `modelName GPT-5.6 Thinking`, `humanReviewed false`), passes every
gate — `valido: True, 0 errori, 0 warning` — and is nevertheless unusable as behavioural data.

### The horizon collapses into a weekly template

Comparing each day by the tuple `(intent, preferred start, preferred duration)` of its activities:

```
giorni totali:                244
firme giornaliere DISTINTE:     8

  Monday    -> template 1     (35 identical occurrences)
  Tuesday   -> template 2     (35)
  Wednesday -> template 3     (35)
  Thursday  -> template 4     (35)
  Friday    -> template 5     (35)
  Saturday  -> templates 6, 8 (34 + 1 truncated final day)
  Sunday    -> template 7     (34)
```

Every Monday is identical to every other Monday to the second; sleep is 435 minutes every night.
Slack is a universal constant: all 3 870 activities declare exactly 12 minutes between
`earliest` and `latest`.

The declared psychological state is inert. `initialState` carries `fatigue 0.45`, `hunger 0.2`,
`stress 0.3`, `socialNeed 0.4`, `medicationAvailableDoses 0`, but the scenario declares **0
preconditions and 0 effects**, and each of those names occurs **0 times** in the
`personalProcessPackage`. `runtimeEventCandidates` and `commitments` are both empty, so the only
runtime randomness source ([`simulation/service.py:628`](../../src/smart_home_sim/simulation/service.py))
has nothing to act on and the `seed` is inert too. Nothing in the horizon evolves.

### The failure scales with horizon length

The same measurement across every generated scenario in the repository:

```
 giorni  firme  rapporto  file
    244      8      0.03  meredith_merrino_8_months…            <- degenerate
     31     23      0.74  lucia_rossi_august_2026
      7      7      1.00  mario-7d
      7      7      1.00  tommaso_bianchi
```

Only the eight-month case is degenerate, and the ratio degrades monotonically with the number of
days one response must carry: 1.00 at a week, 0.74 at a month, 0.03 at eight months. This is not
a single bad generation. Single-response authoring has a working range of roughly one month, and
the case exceeded it eightfold.

### The prompt already forbids this, and nothing enforces it

Requirement 11 of [`generate-simulation-inputs-1.3.0.md:71`](../../prompts/generate-simulation-inputs-1.3.0.md),
present unchanged since `1.2.0`:

> Stable routines must retain plausible day-to-day variation. Do not copy identical preferred
> timestamps and preferred durations across comparable days unless they are fixed commitments.
> Use chronotype, fatigue, hunger, prior-day state and calendar context to vary preferences by a
> few minutes while remaining inside declared windows.

Every other rule in that list is backed by a deterministic gate — resource/location coherence and
reference resolution by the validator, non-overlap by the compiler, `DAY_OUTSIDE_SIMULATION` and
`DUPLICATE_DAY` by the rules (`DUPLICATE_DAY` compares dates, not day content). Requirement 11 is
the only one left to the model's good faith, and it is the one that broke, silently, while the
bundle reported zero issues.

ADR-017 is the precedent that explains why. Its additions to `1.3.0` held because they described
a relation `validate_deterministic_preconditions` already enforced; its own consequence records
this: "The prompt explains a semantic relation already enforced by the authoring preflight." A
prompt rule with no validator behind it is a wish, not a contract.

### 98% of the artifact is redundancy

```
totale file              3 220 006 byte
  scenario.days          3 163 406 byte  (98.2%)
  scenario (resto)           4 818 byte  ( 0.1%)
  personalProcessPackage    51 666 byte  ( 1.6%)

un solo giorno              13 076 byte
8 giorni distinti          104 608 byte   <- the structure actually present
ridondanza               3 058 798 byte   (95.0% of the file)
```

The `personalProcessPackage` (24 process models, 24 bindings) is per-intent and does **not** grow
with the horizon. Only `days` does, and 95% of it is literal repetition.

### The machinery to do this properly already exists

- **Recurring activities**: `BehavioralProfile 1.0.0`
  ([`hybrid_planning/recurring_activities.py`](../../src/smart_home_sim/hybrid_planning/recurring_activities.py))
  already models them with kind, cadence, weekdays, windows and `mining_difficulty`;
  `build_cadence_calendar(profile: BehavioralProfile, …)` already consumes it unchanged.
- **Dynamics**: [`hybrid_planning/drives.py`](../../src/smart_home_sim/hybrid_planning/drives.py)
  (landed 2026-07-25, a week before this bundle was authored) threads sleep debt, hunger, social
  need and fatigue across the horizon, deterministically and with autocorrelation. Run over the
  identical 244 days it yields 145 distinct wake times (04:34–10:25), 134 distinct sleep
  durations (366–630 min, σ 49.8), 63 disturbed nights, 29 debt naps and 91 unplanned social
  contacts — against 8 distinct signatures in the authored bundle.
- **Fitting**: the CP-SAT compiler *is* a placement engine — non-overlap per resident, resource
  cumulative capacity, dependencies, all resolved inside declared windows. It currently places
  nothing, because the model hands it a fully determined schedule with 12-minute windows.
  `day_generation._free_slot` and `_shift` provide collision-free placement below it.
- **Intent**: [`hybrid_planning/day_generation.py`](../../src/smart_home_sim/hybrid_planning/day_generation.py)
  already states the layering — the deterministic substrate exists so that "the LLM day layer will
  later enrich and vary these days".

The capability was present. The external-LLM path simply does not reach it.

## Decision

Keep external-LLM authoring as the creative core, and move the horizon's concrete days out of the
model's output. The external model authors a **horizon outline**: habits, their cadences and
windows, and the narrative arc of the period — phases, one-off events, seasonal drift — at the
level of structure, not of timestamps. A human confirms the outline. A **deterministic expander**
then rolls it into the concrete days, computing sleep debt, hunger, social need and fatigue, and
placing occurrences.

```
outline  ->  [deterministic expander]  ->  SimulationAuthoringBundle  ->  existing pipeline
  new              new                          unchanged                    unchanged
```

Binding constraints:

1. **The outline carries no timestamps**, with the single exception of genuinely fixed
   commitments (fixed working hours). Anything else is cadence and window. Allowing absolute
   times reintroduces pinning at a smaller file size.
2. **The expander is seeded**: outline + seed always yields the identical bundle. This restores a
   reproducibility contract the external path does not currently have — the same prompt and model
   do not reproduce a file today.
3. **The expander sits upstream of the existing ingestion gate.** Its output is an ordinary
   `SimulationAuthoringBundle`, entering the unchanged flow. No frozen contract is touched. The
   application runs the expander behind one endpoint so a long horizon does not require leaving it
   for a terminal, and the measured bands ride into the workspace inside `scenario.extensions`,
   which is what lets an exported dataset carry the segmentation target alongside the sensor log.
4. **The confirmed outline is the ground truth.** The external path produces none today; the
   confirmed habit set, carrying `mining_difficulty` per habit, becomes it.
5. **Windows are the band the author declared**, not a constant and not a function of jitter.
   Jitter says how irregular a habit is and moves its *preferred* moment; the band says where the
   author finds it acceptable and is what the compiler is handed. Deriving both from jitter, as
   this decision first stated, left a five-hour event fifteen minutes of room and made its day
   infeasible.

### Resolved while designing the contract

Four questions were open when the decision was taken; all four are now settled and implemented.

1. **Displacement is carried per habit, not per event.** `HabitDisplacement` pairs a habit with
   `skip` or `reschedule`, defaulting to `skip`. A single event routinely wants both: a week of
   flu postpones the shopping and simply cancels the runs. A per-event policy would misdescribe
   half of it, and expressing the mixture as two overlapping events would be a workaround rather
   than a model.
2. **Drives and jitter have distinct roles.** The drives supply the slow, autocorrelated shift —
   a short night moves the whole following morning — and `HabitCadence.jitter_minutes` bounds the
   fast day-to-day wobble around it, per habit. This is what lets an anchor be punctual while an
   optional habit wanders, the property `mining_difficulty` already presumes and that a single
   global spread cannot express. The previously dead field is thereby given its meaning.
3. **The external model still authors the process package.** It is per-intent and so O(1) in the
   horizon — 51 666 bytes in the eight-month bundle, unchanged at five years — so it does not
   reintroduce the scale problem, and it is the semantic part where a large model earns its place.
   `HorizonAuthoringBundle` is the envelope carrying outline and package together, kept apart for
   the same reason `SimulationAuthoringBundle` separates scenario from package: a human confirms
   the outline, while the package is already gated by behavior validation and the deterministic
   replay.
4. **The outline declares its own world.** `OutlineWorld` carries locations, resources, external
   people, the synthetic home reference and the starting placement. ADR-015 materializes the
   executable home from declared locations, so those declarations must come from the author rather
   than from a generator that never read the brief. It is O(1) in the horizon like everything else.

The narrative arc — phases, dated events, displacement — had no contract before this and is the
substantive new work; `runtimeEventCandidates` was the closest existing shape and was unused.

### Learned while building the expander

Three things the decision as written got wrong or left out, all corrected in the implementation.

- **Windows come from the band, not the jitter** (constraint 5 above, now restated). The two are
  different quantities and collapsing them is what broke Christmas.
- **The compiler's frozen probe budget is not enough for a contended horizon.** With real windows
  to place inside, some feasibility probes exhaust `MAX_DETERMINISTIC_TIME` and answer `UNKNOWN`,
  which aborts a sound compilation with `SOLVER_NOT_OPTIMAL`. Probes now carry their own budget;
  this is safe for the same reason their solver parameters are, since only their status is read.
- **The compiler's fallback branch was too coarse.** On the first non-singleton conflict core it
  abandoned the batch and decided all remaining requests one at a time. It now bisects for the end
  of the feasible prefix, and the core itself bounds the search — on the reference horizon from
  3 424 candidates down to 90.

### Terminology aligned with the habit-mining literature

The contract originally called its central object a `Habit`. That is not what the word means in
the work this dataset is meant to serve. Leotta, Mecella and Sora define a habit as "a sequence or
interleaving of activities that happen in specific contextual conditions", the focus being the
routine rather than the goal; the habit-segmentation paper operationalises the same idea by
discretising the timestamp axis, each bin being a time range in which an identifiable process
runs. Their Aruba bin `05:15-07:00` is roughly 80% the *sleeping activity*.

So a habit is a band of the day and activities live inside it. What this contract called a habit
was an activity plus a recurrence rule — and, worse, a generative input wearing the name of a
discovered output. A reader arriving from that literature would have opened the profile expecting
bands and found cadences.

Two consequences, both applied:

- **the rename.** `Habit` → `RecurringActivity`, `HabitCadence` → `ActivityCadence`,
  `HabitOccurrence` → `ActivityOccurrence`, `HabitOverride`/`HabitDisplacement` →
  `ActivityOverride`/`ActivityDisplacement`, `PlannedHabitTrace` → `PlannedActivityTrace`,
  `habitId` → `recurringActivityId`, the `habit:` activity label → `activity:`, and
  `planned-habit-trace.json` → `planned-activity-trace.json`. Done before any real dataset
  existed, so it cost a mechanical refactor rather than a data migration.
- **the missing concept.** `HabitSegment` now declares the bands, and the expander publishes
  `habit_ground_truth 1.0.0`: for each band, the minutes each intent occupies and its share across
  the horizon, with the remainder reported as unaccounted — the same "other" column their table
  prints. That is the answer sheet for a segmentation algorithm, which sees only a sensor log and
  must recover both where the day divides and what runs in each division. Bands may not overlap,
  and the night band is the one thing in the contract allowed to cross midnight.

### The days contain more than the outline declares

Found by the first ingestion of a real expanded horizon, which was rejected with **628
`MISSING_PROCESS_BINDING` errors for five missing process models**. The drive layer puts intents
into a day that no outline mentions: a wake and a night every day, and a debt nap, a nocturnal
bathroom trip or an unplanned reach-out whenever the state calls for one. The prompt had told the
model not to declare waking or sleeping as activities, so it reasonably wrote no process models
for them, and it never knew about the other three at all.

`RHYTHM_EMITTED_INTENTS` now names that set once, in the module that emits it. The prompt renders
it — a package must implement those intents alongside the declared ones — and the expander refuses
a package that does not, before any day exists. One message instead of 628, and the two cannot
drift because both read the same constant.

A fourth lesson belongs to the expander rather than the decision: a day whose preferred times overlap
forces the compiler to reject and re-place 18% of every value it is given. The expander now makes
each day coherent before handing it over, which is both cheaper and truer — a person does not plan
two things over each other. Residual collisions are left to the compiler, which is what it is for.

## Consequences

- The artifact the model must produce drops to roughly 2% of current size and stops growing with
  the horizon, since the only horizon-proportional part is removed. One year or five change the
  outline's event list, not its structure.
- Day-to-day variation stops being a request and becomes a property of construction. Requirement
  11 becomes unnecessary rather than unenforced, which is the only reliable way to retire an
  unverifiable prompt rule.
- Sleep debt is deliberately **not** delegated to the model. It is a 244-step numerical recurrence
  with saturation and partial recovery; it is invisible in the output, so a wrong integration is
  indistinguishable from a right one by inspection; and it must be seed-reproducible. Asking for
  it in the prompt would create a second requirement 11.
- The failure mode changes character. A weak outline yields a valid, varied, dull dataset —
  visible by reading two pages before generation — instead of a silently degenerate one
  discovered by measuring 3 870 activities afterwards. The risk moves from invisible and
  irreversible to evident and cheap.
- Human review, absent today (`humanReviewed: false`), becomes structural: the outline is small
  enough to actually be read, and confirmation is a step in the flow.
- `HabitCadence.jitter_minutes`, declared but consumed nowhere in `src/`, now has a defined role
  (fast per-habit wobble) and must be wired by the expander.
- The reference example states the same eight months as the bundle that motivated this ADR in
  11 848 bytes against 3 220 006 — a factor of 272 — while carrying an arc the original never had:
  two seasonal phases, Christmas away, a week of flu, two weekends away.
- Prompts `1.0.0`–`1.3.0` stay frozen and buildable, so trials recorded against them remain
  reproducible. The bundle analysed here is retained as an experimental artifact: the ratios
  1.00 / 0.74 / 0.03 measure the working range of single-response authoring and are a result, not
  waste.
- No JSON Schema, catalog, validator, compiler or runtime contract changes. ADR-002, ADR-003 and
  ADR-011 are untouched.
- A validator that rejects a degenerate horizon remains worth adding independently. It is not
  required by this decision — the expander cannot emit identical days — but it is the only thing
  that would protect any authoring path that bypasses the expander.
