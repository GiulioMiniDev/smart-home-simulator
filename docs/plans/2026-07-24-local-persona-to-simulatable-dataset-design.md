# Local persona-to-simulatable-dataset generation design

## Goal

Add an optional, fully local front-end to Phase 1 of the pipeline. Today a researcher hand-authors
a plan with an external LLM, feeds the JSON to the program, and the program validates, compiles, and
simulates it. This design lets the researcher instead generate everything locally through LM Studio:
first an invented **persona**, then that persona's **habits**, then the machinery that lets the
persona act, and finally many **days** that are varied and creative yet coherent with the frozen
habits — for a horizon of one month, three months, six months, or one year, ready to be simulated.

The distinguishing requirement is the last clause. Accepted output must be **genuinely simulatable**,
not merely plausible on paper. Every day the front-end emits must pass the same gates as a manual
input, including an authoritative simulation, so that the downstream dataset is trustworthy ground
truth for habit mining (the thesis objective, whose final metrics remain reserved for Milestone 9).

The manual "bring your own JSON" path is unchanged. This subsystem is an optional producer that emits
the same canonical artifacts the manual path produces.

## Relationship to existing designs

This design composes and advances two accepted designs and does not restate their contents:

- `2026-07-22-behavioral-profile-habit-ground-truth-design.md` — the frozen behavioral profile, the
  `habit-ledger.json`, the per-chunk habit budget, the plan gates, and the three ground-truth layers
  (`intended-habits`, `planned-habit-trace`, `realized-habit-trace`). All of that is reused verbatim.
- `2026-07-22-hybrid-local-planning-design.md` — weekly chunked planning, the deterministic
  materializer from proposal to scenario, bounded explicit repair, immutable provenance, and the
  one-way dependency rule (simulation/environment/sensor packages must not import the planner).

It adds three things those designs did not cover, and changes one policy:

1. **Persona invention front-end** — the persona and habits can be *invented* locally from a short
   brief, not only supplied from an existing bundle.
2. **Per-persona process package authoring** — each invented persona gets its own executable
   machinery (home + personal process package), authored locally rather than borrowed.
3. **Authoritative simulation gate** — generation runs the real simulation engine as a correctness
   oracle and only accepts days that execute.

**Policy change (deliberate, justified):** the two prior designs state the subsystem "does not invoke
simulation." That was correct for a plan-only vertical slice, but it is the root cause of "a plan
compiles yet does not simulate": plan gates check intent ordering, not spatial trajectory, so a plan
can pass every plan gate and still fail at `enter_home` because the resident was teleported. Since the
goal here is *simulatable* output, the generator now invokes the simulation engine as a gate. This
does not weaken isolation: the dependency direction is unchanged (the generator may import validation,
compilation, environment, and simulation *services*, exactly as it already imports the validator and
compiler; those packages still must not import the generator), simulation runs only inside an isolated
authoring workspace, and it never mutates existing simulation runs.

## Roles and the separation line

The whole architecture follows one cut, which is also the answer to "do not overlap the LLM's role
with the simulator's role":

- **The LLM proposes intent only** — who the person is, which habits they have, and the rough ordering
  of what they do in a day. It never chooses exact timestamps, durations, trajectories, physical
  state, environment facts, sensor events, or ground-truth labels.
- **Deterministic software is authoritative over everything else** — exact timing, movement, feasibility,
  frequency budgets, causal and spatial continuity, sensors, provenance, and ground truth.

A direct consequence, and the reason the LLM output can be small: the strict rules live in code, not in
the prompt. Simplifying the model's output reduces both its error surface and the number of rules it
must be told. Prompts stay short and rely on the model's common sense; correctness is enforced by
deterministic validation, an authoritative simulation, and small targeted repairs — never by prompt
verbosity or silent patches.

## Architecture and dependencies

```text
brief ──▶ generate-persona ──▶ persona (frozen)
                                   │
                                   ▼
                          generate-habits ──▶ behavioral profile (frozen = intended-habits)
                                   │
              ┌────────────────────┼───────────────────────────┐
              ▼                                                  ▼
     generate-home (deterministic)                   author-process-package (LLM, gated)
              └───────────────┬──────────────────────────────────┘
                              ▼
                   persona's executable machinery (home + personal process package, frozen)
                              │
     cadence calendar (deterministic) ──▶ per-day due-habit budget  ── = planned ground truth
                              │
                              ▼
        generate-days (LLM, fresh per week) ──▶ light day skeletons
                              │
                              ▼
    materialize ▶ validate ▶ compile ▶ bind bundle ▶ SIMULATE (authoritative gate)
                              │                            │
                        pass ─┘                     fail ─▶ targeted per-day repair / fallback
                              ▼
      stitch chunks ▶ project sensors ▶ observable dataset + realized-habit-trace
```

Every stage that the LLM touches emits a small proposal that deterministic software normalizes,
validates, and freezes before the next stage may read it. Frozen artifacts are addressed by digest and
cannot change silently downstream.

## Pipeline stages

**A. Persona and habits (LLM, once, frozen).** `generate-persona` invents a realistic resident from a
short natural-language brief: age, sex, occupation, household, health conditions, city, timezone, and
a few lifestyle notes, plus a small set of routine anchors. `generate-habits` expands the persona into
the full behavioral profile. Deterministic validation enforces the portfolio balance (anchor,
contextual, optional-preference, rare) already required by the profile contract; a bounded, directive
repair states current-versus-required counts so a small local model can correct the mix. The number of
invented persona anchors is not free: because each routine anchor canonicalizes to an anchor habit and
the portfolio must satisfy the minimum kind counts, persona anchors are capped so the profile can still
balance on a small model. Persona and profile are designed together, then frozen.

**A2. Executable machinery (deterministic home + LLM-authored package, once, frozen).** The persona's
home is generated deterministically from the scenario and the covered activities (the existing
`generate-home` path). The personal process package — how each accepted intent is physically performed
— is authored locally per intent, grounded on a same-intent reference package so ADL mechanics stay
solid, with per-model semantic checks (action types in vocabulary, location references within the
home, components covered, start-to-end graph without dead nodes), a bounded repair loop, and a
deterministic fallback that adapts the reference model. The assembled package is accepted only after
`validate-behavior` and bundle binding, then frozen.

**B. Cadence calendar (deterministic, no LLM).** Software expands each habit's cadence rule over the
chosen horizon into a per-day table of due habits with target time windows and seeded within-window
jitter. This is the existing per-chunk habit budget, extended to the full horizon. It is computed
before any day is generated, so the **planned ground truth is known deterministically in advance** and
is exactly what the program scheduled, not what the LLM happened to remember.

**C. Days (LLM, fresh per week).** For each weekly chunk the model receives the frozen persona summary,
that week's due-habit budget per day, the vocabulary of activities the package can execute, a compact
summary of recent accepted days, and one line of style guidance. It returns seven light day skeletons:
a day type, an optional note, and an ordered timeline of activities with rough times. Each week is
generated fresh (roughly fifty-two calls for a year) to maximize semantic variety; the model arranges
a plausible day around the due habits and adds creative filler, but does not track cadence across weeks
— the calendar already did.

**D. Authoritative simulation gate (deterministic).** Each day is materialized into a scenario,
validated, compiled, bound into a bundle with the frozen home and package, and executed by the real
simulation engine. A spatial-coherence heuristic rejects home activities scheduled while the resident
is away. A day that fails to compile or simulate receives a small, targeted repair request naming only
that day's specific violation (for example, "breakfast is placed in the kitchen while you are at the
office; reorder or relocate"); after a bounded number of repairs a deterministic fallback applies, and
if that also fails the chunk fails explicitly. Only days that actually execute are accepted.

**E. Assembly (deterministic).** Accepted chunks are stitched with correct longitudinal state handoff:
each intermediate chunk hands its terminal asleep state to the next; only the final chunk of the
horizon may truncate its terminal overnight sleep at the observation boundary, which is always safe
because there is no successor to resume into. The stitched run is projected to sensors, producing the
observable dataset alongside the `realized-habit-trace` derived from what actually executed.

## LLM output contracts (deliberately small)

Three small proposals, never one large document. Deterministic normalizers expand each into the richer
frozen contract, filling defaults the model is not asked to provide (cooldowns, jitter bounds, exact
durations, sensor mappings). Field names below are illustrative.

Persona:

```json
{ "name": "Elena", "age": 72, "sex": "F", "timezone": "Europe/Rome",
  "occupation": "retired (former teacher)", "household": "lives alone",
  "health": ["arthritis", "hypertension"], "city": "Bologna",
  "notes": "early riser, routine-driven, rarely goes out in the evening",
  "routine_anchors": ["morning coffee", "evening blood-pressure pill", "afternoon rest"] }
```

Habit proposal (normalized into the full behavioral-profile habit specifications, then validated):

```json
{ "habits": [
  { "id": "morning_coffee", "label": "coffee on waking", "cadence": "daily",
    "window": "07:00-08:00", "kind": "anchor" },
  { "id": "meds_evening", "label": "blood-pressure pill", "cadence": "daily",
    "window": "20:00-20:30", "kind": "anchor" },
  { "id": "grocery", "label": "groceries", "cadence": "weekly:Tue,Fri",
    "window": "10:00-12:00", "kind": "contextual" },
  { "id": "grandkids", "label": "grandchildren visit", "cadence": "biweekly",
    "window": "15:00-18:00", "kind": "optional" },
  { "id": "checkup", "label": "medical check-up", "cadence": "monthly",
    "window": "morning", "kind": "rare" } ] }
```

Day skeleton (one per day, produced in weekly batches):

```json
{ "date": "2026-03-10", "day_type": "weekday", "note": "rainy, stays in",
  "timeline": [
    { "activity": "wake_up",         "around": "06:50" },
    { "activity": "morning_coffee",  "around": "07:10", "habit": "morning_coffee" },
    { "activity": "grocery_shopping","around": "10:30", "habit": "grocery" },
    { "activity": "lunch",           "around": "12:30" },
    { "activity": "take_medication", "around": "20:00", "habit": "meds_evening" },
    { "activity": "sleep",           "around": "22:30" } ] }
```

`activity` must come from the vocabulary of activities the frozen package can execute, so the model can
never request an activity with no machinery. `around` is a rough band; the compiler owns exact timing
and duration. `habit` is a back-link used to mark the planned trace and to cross-check the calendar; it
is advisory, because the authoritative label of which habit was expressed comes from the deterministic
calendar and the realized simulation, not from the model.

## LM Studio integration

Calls whose target contract is small and flat may use constrained structured output. Calls whose
target is a large, deeply nested contract (the process model, the full behavioral profile) use
**free-form JSON plus deterministic post-validation and repair**, not constrained `json_schema`
decoding: on a small local model the constrained grammar over a large schema is prohibitively slow,
while free-form output with a repair loop reaches the same correctness far faster. The client tolerates
fenced and prose-wrapped output by extracting the first balanced JSON object before validation. Default
model and endpoint are configurable; the researcher's local models include small quantized 7–9B
instruct/coder variants reachable at the local LM Studio endpoint.

## CLI surface

Headless commands backed by reusable services, composable and individually resumable:

- `generate-persona` — brief to frozen persona and routine anchors.
- `generate-habits` — persona to frozen behavioral profile (reuses `generate-behavioral-profile`).
- `author-process-package` — persona plus home to gated, frozen personal process package.
- `generate-days` — one weekly chunk of gated, simulatable days against the frozen artifacts.
- `generate-horizon` — orchestrates B–E over a chosen horizon (`--months 1|3|6|12`), reusing the
  frozen persona, profile, package, and home for every weekly chunk and resuming from the last
  accepted chunk.

Each command persists immutable provenance and can run unattended. A future UI is a wizard over the
same services: invent identity, inspect or approve, freeze, generate the horizon, inspect gates and
repairs. Human approval stays optional; validation and the simulation gate stay mandatory.

## Storage, provenance, and isolation

Each run is immutable and isolated under a dedicated authoring directory, extended from the existing
layout with the persona, package-authoring, and simulation-gate artifacts:

```text
generated/hybrid-planning/<run-id>/
  run.json
  persona.json
  behavioral-profile.json          # frozen, digest-addressed (intended-habits)
  home.json
  personal-process-package.json    # frozen, gated
  cadence-calendar.json            # planned ground truth for the whole horizon
  chunks/<chunk-start>/
    day-budgets/                   # per-day due habits
    proposed-days/                 # raw LLM skeletons
    scenarios/  plans/  bundles/
    simulation/                    # authoritative traces + gate reports
    planned-habit-trace.json
    repairs/                       # every targeted repair request and outcome
    memory-checkpoint.json
  dataset/
    observable-sensor-log.json
    realized-habit-trace.json
```

Raw prompts, requests, responses, model identity, parameters, seeds, timestamps, digests, and repair
history are retained for every LLM call. Any comparison baseline is opened only after acceptance and is
never placed in a prompt. Simulation, replay, environment, and sensor packages continue not to import
this subsystem.

## Ground truth and evaluation

The three ground-truth layers from the profile design are preserved and kept out of the observable
dataset: `intended-habits` (the frozen contract), `planned-habit-trace` (habits the accepted plan
represents, driven by the deterministic calendar), and `realized-habit-trace` (habits that actually
occurred, produced by the authoritative simulation). Because the calendar computes planned occurrences
before generation and the simulation reports realized occurrences after execution, precision/recall
evaluation of habit mining is possible without leaking any label into the sensor data.

## Failure handling

Provider absence, timeout, malformed output, contract failure, portfolio imbalance, package-authoring
rejection, infeasible or unsimulatable days, exhausted repairs, and digest mismatch are distinct,
recoverable outcomes with stable codes. A failed chunk preserves all artifacts, exposes no partial
accepted dataset, and can be resumed without regenerating accepted chunks. No accepted artifact is ever
silently patched.

## Incremental build scope

Value is delivered in three increments; each produces genuinely simulatable output, not a mock.

1. **Vertical spine over one month**, using an existing reference package and home as scaffolding, to
   prove the new and riskiest parts: weekly `generate-days`, the authoritative simulation gate, and the
   targeted repair loop end to end.
2. **Per-persona machinery**: `generate-persona`, `generate-habits`, deterministic `generate-home`, and
   `author-process-package`, replacing the scaffold with gated per-persona artifacts.
3. **Horizon scaling** to three, six, and twelve months via `generate-horizon`: repeated weekly chunks,
   longitudinal state handoff, batch simulation, and the final-chunk truncation rule.

## Verification

Tests cover: invalid, contradictory, and imbalanced personas and profiles; free-form-output repair;
package authoring semantic checks, repair, and fallback; the simulation gate accepting only executable
days and rejecting spatial teleports; targeted single-day repair; multi-chunk ledger and state
continuity; frozen-digest checks and no-silent-change; resume after a failed chunk; correct terminal
truncation only on the final chunk; no baseline leakage into prompts; and a golden persona case run end
to end. New code holds the repository's 95 percent coverage requirement. A live LM Studio acceptance run
proves that an invented persona yields a frozen profile, a gated package, and a full month of days that
all pass validation, compilation, and authoritative simulation, producing an observable dataset paired
with intended, planned, and realized habit traces.

## Non-goals and open questions

Non-goals: changing any frozen downstream contract; giving the LLM authority over timing, physics, or
sensors; replacing the manual input path; and the final habit-mining empirical metrics (Milestone 9).

Open questions to resolve before or during increment 1: the default LM Studio model and generation
parameters; the first acceptance persona and horizon; whether `generate-home` needs any persona-driven
extension to cover invented activity sets; and the repair and fallback budgets that best balance
acceptance rate against generation time on the researcher's local hardware.
```
