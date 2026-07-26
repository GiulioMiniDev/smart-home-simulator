# Local generation pipeline

## Boundary

The local generation pipeline is an **optional producer** of the same canonical artifacts the
manual authoring path produces. It turns one free-text brief into a simulatable batch manifest
using a local LM Studio model, without granting that model authority over feasibility, timing,
geometry, execution, sensors or ground truth.

```text
brief
    -> persona -> behavioral profile (habits) -> planning world
    -> personal process package -> cadence calendar -> day plans
    -> per-day scenarios, plans and bundles + batch manifest
    -> planned habit trace
```

Generation **never simulates**. It ends at the batch manifest; running `simulate-batch` on that
manifest is a separate, explicit researcher step. The manual "bring your own JSON" path is
unchanged and remains fully supported.

Dependencies are one-way: the simulation, environment and sensor packages must not import
`hybrid_planning` or the LM Studio adapter. An already accepted artifact replays and simulates
without LM Studio running.

## Relationship to the frozen contracts

Everything this subsystem emits is an ordinary M3 artifact. A generated personal process package
is gated by the same behavior validator that manual packages pass, and every generated day is
compiled by the frozen `1.0.0` compiler before it enters the manifest. No contract is relaxed,
extended or version-bumped to accommodate a model response.

The LLM contributes **variation**, never validity: a candidate is accepted only when the artifact
containing it still passes the deterministic gate, otherwise the deterministic substrate is kept.

## Stages

`run_generation` chains seven ordered stages and writes every artifact under one output directory.

| # | Stage | LLM | Output |
|---:|---|---|---|
| 1 | Persona invention | yes | `persona.json` |
| 2 | Habit authoring | yes | `behavioral-profile.json` |
| 3 | Planning world | no | `planning-world.json` |
| 4 | Process package authoring | optional | `personal-process-package.json` |
| 5 | Cadence calendar | no | `cadence-calendar.json` |
| 6 | Day arrangement | optional | in-memory day plans |
| 7 | Horizon merge | no | `batch-manifest.json`, `planned-habit-trace.json`, `horizon-scenario.json`, per-day `scenarios/`, `plans/`, `bundles/` |

### 1. Persona

A frozen resident record (`persona_id`, name, age, occupation, household, health, city, timezone).
Age is bounded to 0–120. The persona is immutable for the rest of the horizon.

### 2. Habits — the frozen habit ground truth

The model proposes a habit list over closed vocabularies (kind, frequency, time band); deterministic
code expands each proposal into a schedulable habit and gates the assembled profile on a portfolio
balance: at least 8 habits, of which at least 3 `anchor`, 2 `contextual`, 2 `optional` and 1 `rare`.
An unbalanced portfolio triggers a bounded directive repair (default at most 2 attempts) stating the
exact current-versus-required counts, because a small model otherwise under-produces the rarer
kinds. The accepted profile is the frozen ground truth the cadence calendar expands.

### 3. Planning world — deterministic

The reusable, window-agnostic environment for one persona: locations, resources, the resident and
the initial placement. The apartment is currently a **fixed comprehensive standard template** with
the persona injected as resident; distinctiveness lives in the habits, days and process package, not
in the ADL home. The `PlanningWorld` contract deliberately leaves room for a later per-persona
world without changing its consumers.

### 4. Process package authoring

The deterministic substrate retargets the bundled reference process models — proven simulatable in
the standard apartment — to the persona, assembles a `PersonalProcessPackage` and gates it with the
behavior validator against a **probe scenario** carrying one activity per intent at its default
location. The optional LLM layer sits on top: for each intent the model proposes a process model
grounded on the already-valid retargeted reference, and the candidate is swapped in only if the
whole package still passes the gate.

The executable home is materialised **after** the package, because entity capabilities are derived
from the package's actions; the home therefore cannot precede it.

### 5. Cadence calendar — deterministic

Rolls each habit's cadence rule over the horizon into a seeded per-day schedule of due habits, each
with a target time drawn inside its window. Same profile plus same seed plus same horizon always
yields an identical calendar. This is the *planned* habit-mining ground truth: known before any day
is generated.

### 6. Day arrangement

By default the days come from a deterministic substrate. With `--use-llm-days` the model arranges
each week; a generated day is kept **only when it still compiles**, otherwise the substrate day for
that date is used. A day that cannot be compiled either way is reported in `failed_days` rather than
silently dropped.

### 7. Horizon merge — deterministic

For each calendar day: build a one-day scenario, compile it, and bind it into a bundle against a
single shared home materialised once from the probe scenario. Writes the per-day bundles, the batch
manifest referencing them, and the planned habit trace.

## Homeostatic drive rhythms

Without this layer every day was generated in isolation from a fixed scaffold: the resident woke at
the same minute for the whole horizon, every night had the same length and no nocturnal event ever
occurred. A recogniser trained on that log learns a clock, not a person.

The drive layer threads four slow variables — sleep debt, hunger, social need and fatigue — from one
day to the next and turns them into the concrete shape of each day: bedtime, night length, wake
time, naps and nocturnal bathroom trips. Because the variables persist, the resulting variability is
**autocorrelated**: a short night makes the next morning later and a nap more likely, the way a real
routine drifts and recovers, rather than the independent per-day noise plain random jitter gives.

Constants are derived from the frozen persona: age sets the nightly sleep target (National Sleep
Foundation consensus bands collapsed to one value per age group) and the nocturia baseline, and the
conditions the persona already carries shift those same two dials rather than introducing a separate
disease model. Sleep debt is capped at roughly one lost night, beyond which the behavioural effect
saturates, and a long night repays only part of the accumulated debt.

This layer is enabled by default and is fully deterministic: the same persona, seed and calendar
always yield the same rhythms, so the reproducibility contract is preserved.

### Interaction with the variable catalog

`variable-catalog-1.0.0.json` already declared `resident.fatigue`, `resident.hunger`,
`resident.stress` and `resident.social_need`, but only with `scope: initial_state` — persona colour
passed to the model and validated for referential integrity, never state that evolved across days.
The drive layer is what makes them dynamic. It additionally carries `sleep_debt_minutes`, which is
**not** a catalog variable: it is generator-internal state that shapes the emitted days, not a
value a process model may reference. See `06-behavioral-authoring.md`.

## Ground truth separation

The planned trace (`planned-habit-trace.json`) records which habit is due when, derived
deterministically from the frozen cadence calendar with no LLM and no simulation. The *realized*
trace — what actually occurred — is recovered later from the simulation's oracle mapping. Keeping
them as separate artifacts is what lets mining precision and recall be scored without leaking labels
into the sensor data.

## LM Studio adapter

A local OpenAI-style chat-completions client (`POST {base_url}/v1/chat/completions`, default
`http://127.0.0.1:1234`, default model `qwen2.5-coder-7b-instruct`). It favours free-form JSON output
plus deterministic post-validation over constrained decoding. The transport is injectable, so every
generator is exercised in tests without a live endpoint.

This is the **only** network call in the project, it is local-only, and it is confined to this
subsystem. Validation, compilation, simulation and sensor projection contain none.

Each CLI generation command accepts `--exchange-output` to persist the request, response, content,
duration, finish reason and token usage as an immutable provenance record, so a run can be inspected
and reproduced without re-calling the model.

## Failure contract

Provider absence, timeout and invalid responses produce explicit typed errors — `LMStudioError`,
`PersonaGenerationError`, `HabitsGenerationError`, `PackageAuthoringError`, `CadenceError`,
`HorizonError` — with distinct CLI exit codes (`2` for a transport failure, `1` for a generation
failure). No partial artifact is published as valid.

## Entry points

CLI, one stage per command plus the end-to-end driver:

```text
generate-persona          brief            -> persona.json
generate-habits           persona          -> behavioral-profile.json
build-planning-world      persona          -> planning-world.json
author-process-package    persona + world  -> personal-process-package.json
build-cadence-calendar    profile          -> cadence-calendar.json
generate-days             world + calendar -> day plans
generate-horizon          world + package + calendar -> batch manifest
generate-dataset          brief            -> the whole chain above
```

The local application exposes the same pipeline as a durable workspace job
(`POST /api/generation`, `GET /api/generations`, `POST /api/generation/{job_id}/publish`). The job
runs in a subprocess with progress and cancellation, writes every artifact under its run directory
and then publishes them as the **input** of a new home. Simulating that horizon is taken from the
home like any other run.

## Milestone status

This subsystem implements the substance of Milestone 8.1. Two of its declared completion criteria
are **not** met and depend on milestones that have not started:

- rolling horizon fed by the previous horizon's *actual* simulated state — requires M8;
- the controlled comparison between manual plan, probabilistic generator and local LLM at equal
  profile — reserved for M9.

M8.1 must not be declared complete or frozen until both land. See `ROADMAP.md`.
