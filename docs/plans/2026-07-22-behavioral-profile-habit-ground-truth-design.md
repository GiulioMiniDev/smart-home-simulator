# Behavioral profile and habit ground truth design

## Objective

Generate a detailed synthetic behavioral identity once, freeze it for a longitudinal run,
and constrain every later hybrid plan to preserve that identity. The resulting annual data
must contain habits with enough statistical support and controlled variation to be useful
for habit-mining experiments, rather than merely producing individually plausible days.

The local LLM supplies semantic originality. Deterministic software remains authoritative
over contracts, feasibility, frequency budgets, causal continuity, timestamps, state,
sensors, provenance, and ground truth.

## Architectural choice

Use a hybrid behavioral contract rather than a prompt-only solution or a fully procedural
generator.

- Prompt-only generation cannot guarantee support, cooldowns, or longitudinal identity.
- A fully procedural generator provides strong guarantees but tends to create mechanical
  traces and limits semantic variety.
- A validated behavioral contract gives deterministic longitudinal guarantees while the
  LLM proposes plausible optional activities, exceptions, and narrative variation inside
  explicit bounds.

The behavioral profile is separate from the personal process package. The behavioral
profile defines when, how often, and under which conditions an intent occurs. Personal
process models define how an accepted intent is performed. The simulator continues to
materialize exact time, movement, state, environment, and sensor observations.

## Behavioral profile

The LLM generates a structured `behavioral-profile.json` once from the supplied resident,
calendar, locations, resources, and activity catalog. The document has three layers:

1. Supplied immutable facts, such as age, occupation, city, health conditions, household,
   and known relationships. Generated content may not contradict them.
2. Synthetic characteristics, such as habitual wake time, social preferences, domestic
   style, exercise propensity, food routines, and tolerance for exceptions.
3. Formal habit specifications that software can schedule, validate, and later compare
   with mined results.

Habit specifications are classified as anchor, contextual, optional preference, or rare
event. Each habit records at least:

- stable identifier, intent, rationale, and category;
- minimum, typical, and maximum cadence over a declared period;
- applicable and preferred days;
- preferred time band and permitted temporal jitter;
- execution and exception probabilities;
- cooldown;
- allowed location;
- required predecessor and successor intents;
- contextual conditions and incompatible habits;
- seasonal behavior and explicit, versioned drift;
- expected mining difficulty.

The LLM proposes the profile through structured output. Deterministic validation rejects
unknown identifiers, contradictions, impossible cadence, overloaded representative
periods, incomplete causal chains, and insufficient mineable habits. Repair is explicit
and limited to two attempts. An accepted profile is frozen and addressed by its digest.
It cannot change silently during plan generation. Intentional evolution creates a new
profile version with an effective date.

Human approval is optional. Validation is mandatory. This permits unattended batch runs
while allowing a future UI to inspect and approve the synthetic identity.

## Longitudinal planning flow

Profile creation and plan generation are separate operations:

1. `generate-behavioral-profile` creates, validates, freezes, and persists one profile.
2. `generate-hybrid-plan --behavioral-profile ...` plans a bounded chunk against that
   frozen profile.
3. An annual orchestrator will reuse the same profile for sequential weekly chunks.

A compact `habit-ledger.json` crosses chunk boundaries. It stores occurrence counts, last
occurrence, active cooldowns, outstanding cadence debt, consumed exceptions, seasonal or
drift phase, and the behavioral-profile digest. Before each chunk, deterministic software
derives a habit budget containing required, due, optional, and currently forbidden habits.
The LLM receives this budget rather than unrestricted freedom.

The first implementation remains a seven-day vertical slice, but the profile, ledger, and
gate contracts must not assume that the run ends after one week. A failed chunk preserves
all artifacts and can be resumed without regenerating accepted prior chunks.

## Plan gates and repair

Every proposed chunk must pass measurable gates:

- profile fidelity;
- habit support relative to elapsed periods and ledger state;
- temporal regularity with controlled jitter;
- complete travel and dependency chains;
- traceability from weekly goals to daily activities;
- cadence maximums, cooldowns, and rarity;
- daily completeness for the applicable persona and day type;
- controlled novelty in optional activities;
- deterministic schedulability.

Violations have stable codes and precise evidence. A repair prompt requests the smallest
semantic correction and includes only the behavioral contract, current proposal, ledger,
and violations. No silent patching is allowed. After two unsuccessful repairs, the chunk
fails explicitly.

## Habit-mining ground truth

Ground truth is stored separately from observable data and is never exposed as a mining
result. Three layers are distinguished:

- `intended-habits.json`: the frozen behavioral contract;
- `planned-habit-trace.json`: habits represented in an accepted plan;
- `realized-habit-trace.json`: habits that actually occurred, produced only after future
  simulation execution.

Evaluation records expected and planned or realized support, temporal-window adherence,
regularity, jitter, sequence fidelity, exceptions, drift, habitual-to-noise ratio, and
expected detection difficulty. This permits precision and recall evaluation of habit
mining without leaking labels into the generated sensor dataset.

## Interfaces and isolation

The initial interface is headless CLI backed by reusable service functions. LM Studio must
be reachable with the configured model loaded, but no human or Codex supervision is
required. A future UI will act as a wizard over the same services: generate identity,
inspect or approve it, freeze it, generate chunks, and inspect gates and repairs.

The subsystem remains isolated from simulation execution. It may validate and compile an
accepted plan, but it does not invoke simulation, materialize sensors, or mutate existing
simulation runs. A comparison baseline is opened only after plan acceptance and is never
included in an LLM prompt.

## Failure handling and provenance

Every profile and plan call persists immutable request, response, parsed proposal, model
configuration, seed, digest, and repair history. Provider absence, timeout, malformed
structured output, invalid profile, digest mismatch, exhausted repair, or unschedulable
plan produces an explicit failed manifest. Previously accepted artifacts remain intact.

## Initial implementation scope

The next vertical slice will:

1. add behavioral-profile, habit-ledger, budget, gate, and planned-trace contracts;
2. generate and freeze Tommaso's behavioral profile through LM Studio;
3. expose the profile-generation CLI command;
4. require a frozen profile in the improved hybrid planning path;
5. enforce cadence, daily completeness, causal continuity, and goal traceability;
6. perform targeted automatic repair and fail after the configured limit;
7. regenerate Tommaso's week and compare it with the previous hybrid result and the hidden
   baseline.

Annual 52-week orchestration and its UI are subsequent increments. The contracts and
ledger are annual-ready from this slice.

## Verification

Tests cover invalid and contradictory profiles, structured-output repair, causal chains,
frequency and cooldown accounting, multi-chunk ledger continuity, frozen-profile digest
checks, resume behavior, goal traceability, no baseline leakage, and a Tommaso golden
case. New code retains the repository's 95 percent coverage requirement. A live LM Studio
acceptance run proves that the generated profile and plan pass all gates without executing
the simulation.
