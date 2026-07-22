# Hybrid local planning design

## Goal

Add an isolated authoring subsystem that uses a local LM Studio model to propose coherent,
varied plans without giving the model authority over exact timing, feasibility, execution,
environment state, sensors or ground truth.

The first experiment uses Tommaso Bianchi and the seven-day window from 10 through 16
August 2026. The existing `generated/tommaso_bianchi/tommaso_bianchi.json` is hidden from
the model and is read only after generation, as the comparison baseline. The experiment
stops after plan generation and deterministic compilation; it does not execute a
simulation.

## Architecture

The hybrid planner is an optional authoring subsystem with one-way dependencies:

```text
profile + calendar -> hybrid planner -> LM Studio
                           |
                           +-> validator/compiler -> accepted scenario and canonical plan

accepted plan + hidden baseline -> post-generation comparison
```

The hybrid planner may call the existing validation and compilation services. Simulation,
replay, environment and sensor packages must not import the hybrid planner or the LM Studio
adapter. Already accepted artifacts remain replayable and simulatable without LM Studio.

## Planning protocol

Planning is hierarchical and chunked by week:

1. A weekly call defines the narrative structure: workdays, commitments, exceptional
   events, domestic and social activities, intended variation and causal relationships.
2. Seven short daily calls refine the days in sequence. Each call receives the stable
   profile, the weekly brief, the relevant calendar and a bounded summary of accepted
   earlier days.
3. The model chooses intents, optionality, rough time-of-day bands, ordering and reasons.
   It does not choose exact timestamps, trajectories, sensor events or environment facts.
4. A deterministic materializer converts the proposal to a scenario compatible with the
   existing contracts, then the existing validator and compiler decide whether the plan is
   feasible.
5. Invalid or insufficiently varied proposals can receive an explicit bounded repair
   request. There are no silent patches.

The first vertical slice covers one week but uses a duration and chunk interface suitable
for repeated weekly generation.

## Longitudinal memory

An annual run must not place the whole history in the model context. The planner maintains
a compact, versioned checkpoint containing:

- stable profile and calendar references;
- recent accepted-day summaries;
- activity frequencies and last occurrence;
- normalized day signatures and repetition statistics;
- open commitments and recent exceptional events;
- prompt, response, model and parameter digests.

Every accepted chunk writes a checkpoint, allowing interruption and resumption. Before
execution is integrated, the checkpoint describes planning history only. A later rolling
horizon can add an explicit authoritative-state handoff derived from actual simulation;
planned state must never be mislabeled as executed state.

## Storage and provenance

Each run is immutable and isolated under a dedicated authoring directory:

```text
generated/hybrid-planning/<run-id>/
  run.json
  profile-snapshot.json
  chunks/<chunk-start>/
    weekly-brief/
    days/
    proposed-scenario.json
    canonical-plan.json
    validation-report.json
    memory-checkpoint.json
  comparison/
```

Raw prompts, requests, responses, model identity, generation parameters, seeds, timestamps,
digests and repair attempts are retained. The baseline is not copied into prompts or model
memory. The comparator opens it only after the generated plan has been finalized.

## Originality and comparison

Originality means plausible semantic variation rather than random timestamp jitter. The
planner records, at minimum:

- selected-intent overlap between days;
- repeated ordered intent sequences;
- activity frequency and recurrence gaps;
- distinct optional and exceptional activities;
- workday/weekend structural differences;
- time-band variation before deterministic materialization.

The post-generation comparison uses the same resident and seven-day interval. It reports
structural validity, compilation outcome, activity counts, intent distributions, day
similarity and sequence repetition for both plans. These are descriptive prototype
measures, not the final empirical metrics reserved for Milestone 9.

## Failure behavior

Provider absence, timeout, malformed JSON, contract failure, infeasibility and failed
diversity checks are distinct recoverable outcomes. A failed chunk does not expose a
partial accepted plan or modify simulation data. The stored raw exchange remains available
for diagnosis and an explicit retry.

## First acceptance experiment

- Person: Tommaso Bianchi, using the profile facts, locations, resources and available
  intents from the existing authoring bundle without exposing its daily schedule.
- Window: `2026-08-10T00:00:00+02:00` through
  `2026-08-17T00:00:00+02:00` in `Europe/Madrid`.
- Provider: local OpenAI-compatible LM Studio endpoint.
- Output: proposed scenario, validated canonical plan, immutable exchanges, planning
  checkpoint and a post-generation comparison report.
- Explicitly excluded: simulation execution, environment materialization, sensor
  projection and observable data generation.
