# ADR-014: Freeze sensor projection and oracle separation 1.0.0

- **Status:** accepted
- **Date:** 2026-07-21

## Context

M6 must turn authoritative runtime truth into realistic device observations without
leaking labels that a physical sensor cannot measure. Error injection must remain
reproducible and must not consume or perturb any M5 random stream.

## Decision

Freeze four public contracts at `1.0.0`: sensor model, observable sensor log, oracle
mapping and projection report. Support PIR, contact and temperature sensors with
event-driven projection, per-device timing and error configuration, deterministic
per-sensor random streams, explicit false-positive provenance and atomic publication.
PIR coverage is geometric and produces held ON/OFF pulses; contacts can derive state from
entity transitions or door-action pulses; temperature sources have delayed rise and decay
curves. The model seed must equal the authoritative trace seed.

Projection also requires the exact M4 simulation bundle. Sensor region/entity catalogs,
positions and PIR coverage are validated against its embedded home model; the report
records the authoritative home ID, version and digest. This makes the synthetic floor plan
selected by the researcher executable input rather than unchecked sensor metadata.

The observable contract intentionally has no resident, activity, action, movement,
transition, trace or cause fields. These joins exist only in the oracle mapping and share
the opaque observation ID. A projection refuses a source-bundle mismatch or a trace whose
semantic digest no longer matches its content.

## Consequences

- Adding sensors cannot change M5 behavior or another sensor's noise sequence.
- Researchers can distribute the observable log without accidentally distributing the
  ground-truth labels.
- Supervised evaluation can join labels explicitly through the oracle artifact.
- Candidate accounting and content-addressed identifiers expose loss or artifact tampering.
- Invalid placement outside the configured home regions is rejected before projection.
- New device types require a new declared contract version rather than free-form records.
- CSV, JSONL and XES dataset export remain an M7 projection of these frozen artifacts.
