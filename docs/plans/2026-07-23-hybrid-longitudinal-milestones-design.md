# Hybrid longitudinal planning milestones

## Goal

Scale the isolated local-LLM authoring prototype from one accepted week to one, three and
six months of plans for the same resident. Each milestone must preserve a detailed frozen
behavioral profile, produce recognizable habits with plausible variation and exceptions,
and stop after deterministic plan validation and compilation. Simulation execution,
environment materialization, sensor projection and observable dataset generation remain
outside this work.

The milestones are sequential quality gates, not merely three duration switches. A longer
run starts only after the preceding horizon is accepted.

## Non-negotiable boundaries

- The LLM proposes semantics: routines, optional activities, exceptional events,
  time-of-day bands, ordering and causal relationships.
- Deterministic software owns contracts, exact timing, feasibility, validation,
  compilation, checkpoints and acceptance.
- The behavioral profile is generated once, validated, frozen and reused across all
  chunks and milestones for the resident.
- The hidden reference
  `generated/tommaso_bianchi/tommaso_bianchi.json` is never included in prompts, repair
  requests or planning memory. It is opened only by an explicit post-generation
  comparator.
- Plans and planning checkpoints never claim to be executed state or ground truth.
- The hybrid subsystem remains optional. Simulation and replay packages must not import
  it or require LM Studio.

## Architecture

```text
frozen behavioral profile + calendar + milestone manifest
                            |
                            v
                longitudinal orchestrator
                            |
              +-------------+-------------+
              |                           |
       next weekly case            prior checkpoint
              |                           |
              +-------------+-------------+
                            v
                  existing hybrid planner
                            |
                 validate and compile only
                            |
                            v
          accepted chunk + updated planning memory
                            |
              milestone quality evaluation
```

The orchestrator slices a requested local-date interval into chunks of at most seven days.
It invokes the existing single-chunk planner, accepts only fully validated chunks and
writes an atomic checkpoint after each acceptance. It does not concatenate prompts or send
the full history to LM Studio.

## Persistent planning memory

The checkpoint is compact, versioned and deterministic. It contains:

- resident and frozen-profile identity plus profile digest;
- completed interval and next local date;
- accepted chunk identities and artifact digests;
- recent normalized day summaries in a bounded rolling window;
- habit occurrences, misses, recurrence gaps and last occurrence;
- recent exceptional events and cooldowns;
- open commitments whose effects cross a chunk boundary;
- rolling intent, sequence and day-signature statistics;
- model, prompt, parameters and seed provenance.

The LLM receives only the subset needed for the next chunk. Full exchanges stay in local
artifact storage for audit but are not copied into subsequent prompts. Checkpoint writes
use a temporary sibling followed by atomic replacement, so interruption cannot publish a
partially advanced run.

Resumption verifies the manifest, profile digest, accepted artifact digests, completed
interval and configuration fingerprint. A mismatch fails explicitly; it never silently
starts a different resident or history in the same run directory.

## Behavioral coherence

Habits are not treated as repeated identical days. Each generated day has two conceptual
layers:

1. **Habit skeleton:** profile-supported anchors and recurring sequences that make the
   resident recognizable.
2. **Variable shell:** optional activities, timing bands, locations, social context,
   exceptions and causal events that make days non-identical.

The software, not the LLM, maintains habit budgets and recurrence history. Before a chunk
is accepted it checks:

- required anchors and their allowed day types;
- probabilistic habit opportunity counts over the elapsed horizon;
- minimum and maximum recurrence gaps;
- causal consistency, including travel only when a destination activity requires it;
- cross-day commitments and cooldowns;
- exact and near-duplicate normalized day signatures;
- excessive repetition of optional sequences;
- plausible differences between workdays, weekends and exceptional days.

The diversity gate must not reject stable habits merely because they recur. Exact
duplicates and variable-shell repetition are evaluated separately from the habit skeleton.
Warnings are retained even when a chunk passes.

## Milestone 1: one month

Purpose: prove that chunking, frozen-profile reuse, memory, interruption and behavioral
quality survive beyond the seven-day prototype.

Deliverables:

- a headless longitudinal command accepting start date, duration in months, chunk size,
  frozen profile, seed, LM Studio configuration and output directory;
- four or five accepted weekly chunks covering exactly one calendar month;
- atomic checkpoint and deterministic resume;
- rolling habit ledger, causal-coherence report and diversity report;
- a milestone summary that references chunk artifacts without duplicating them;
- an optional hidden-baseline comparison invoked only after finalization.

Acceptance gates:

- every date appears exactly once and there are no gaps or overlaps;
- every chunk validates and compiles without simulation execution;
- the same resident and profile digest are used throughout;
- interruption after any accepted chunk and resumption produce the same accepted plan
  digests as an uninterrupted run with the same cached exchanges;
- no hard habit, temporal, resource or causal error remains;
- no normalized full-day signature occurs on more than three consecutive days;
- each seven-day window contains at least one profile-supported optional or exceptional
  variation unless the profile explicitly forbids it;
- the baseline digest is absent from every stored request and response supplied to the
  model.

This milestone is a pipeline and coherence pilot. It is too short to claim that configured
probabilities are statistically calibrated.

## Milestone 2: three months

Purpose: establish that habit signals remain mineable while optional behavior and
exceptions vary over a medium horizon.

Additional deliverables:

- calendar-aware commitments and month-boundary handling;
- configurable event cooldowns and recurrence-gap enforcement;
- rolling 30-day diversity and habit-frequency summaries;
- comparison of configured behavioral-profile probabilities with observed planning
  opportunities and accepted occurrences;
- deterministic retry/resume across month boundaries.

Acceptance gates:

- all one-month gates continue to pass for the complete three-month interval;
- each declared habit has an opportunity, occurrence and miss series suitable for habit
  mining rather than only an aggregate count;
- observed habit rates are reported with opportunity counts and uncertainty, never
  presented as guaranteed calibration;
- exceptional events respect eligibility, cooldown and causal constraints;
- rolling reports expose drift, repetition and sparse-habit warnings;
- memory size remains bounded independently of elapsed days.

## Milestone 3: six months

Purpose: validate scalability and produce a plan corpus long enough for the subsequent
execution and habit-mining experiments.

Additional deliverables:

- seasonal and calendar context changes without changing immutable resident facts;
- explicit, bounded behavioral drift events when permitted by the frozen profile;
- benchmark data for calls, retries, tokens, wall time, disk use and checkpoint size;
- a resumable six-month manifest composed only of accepted immutable chunks;
- a research summary separating profile truth, planned habit annotations, compiler facts
  and any later observable data.

Acceptance gates:

- all three-month gates continue to pass for the complete six-month interval;
- checkpoint size and prompt context stay within configured bounds;
- restart cost is proportional to the unfinished chunk, not the elapsed horizon;
- each accepted chunk is replayable from stored exchanges without LM Studio;
- performance and disk growth are reported per day and per chunk;
- no plan artifact is mislabeled as executed ground truth or observable sensor data.

The six-month result remains a plan-only artifact. Executing it and producing sensor data
belongs to the longitudinal simulation milestone and requires an authoritative-state
handoff after every executed chunk.

## Failure and repair

Each chunk permits the existing bounded structured repair policy. Provider absence,
timeout, malformed output, profile mismatch, habit-gate failure, causal failure,
validation failure and compilation failure are distinct outcomes.

A failed chunk:

- does not advance the checkpoint;
- does not publish a partially accepted milestone;
- retains its local exchanges for diagnosis;
- can be retried explicitly with the same configuration or superseded by a new run;
- never falls back silently to random or rule-generated behavior.

Fallback to a rule-based or manual plan, if added later, must be selected explicitly and
recorded as a different authoring strategy.

## Artifact and Git policy

All runtime exchanges and generated plans live under:

```text
generated/hybrid-planning/<run-id>/
```

The directory is ignored by Git. Prompts, raw responses, repair attempts, digests,
checkpoints and accepted plans remain available locally for provenance without creating
hundreds of repository changes.

Repository-tracked evidence must be deliberately curated and copied outside the runtime
directory:

- small sanitized test fixtures under `tests/fixtures/`;
- aggregate evaluation reports under `docs/evaluation/`;
- specifications, designs and implementation plans under `docs/`.

The existing Tommaso baseline remains tracked in its current location. No broad
`generated/` ignore rule is introduced because the repository already contains curated
reference artifacts there.

## Verification strategy

Tests use deterministic fake LM Studio exchanges and temporary directories. The normal
suite must not require a loaded model or network access.

Verification is layered:

- unit tests for slicing, memory reduction, opportunity accounting, causal checks and
  quality metrics;
- service tests for checkpoint atomicity, failure isolation and resume validation;
- CLI tests for one-, three- and six-month manifests without performing live calls;
- a cached-exchange acceptance run for deterministic replay;
- one explicit live LM Studio pilot at the one-month milestone;
- repository-wide lint, tests and coverage before advancing each milestone.

Live three- and six-month generation starts only after review of the preceding milestone
report.
