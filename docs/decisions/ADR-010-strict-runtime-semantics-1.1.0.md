# ADR-010: Strict upstream runtime semantics 1.1.0

- **Status:** accepted
- **Date:** 2026-07-21

## Context

The first strict M5 execution exposed contradictions that structural M3/M4 validation
could not observe: travel models repeated `leave_home` after the resident had already
left, two item transformations had no declared producer, and several scenario facts used
by live preconditions had neither initial values nor activity effects. Accepting those
cases through runtime no-ops or implicit aliases would move authoring semantics into the
engine and contradict the frozen action preconditions.

## Decision

Keep every `1.0.0` artifact immutable and publish a parallel, reproducible correction:

- scenario `mario_rossi_week_2026_10_12__runtime_1.1.0` declares all otherwise external
  initial facts and the activity effects that produce ingredients, laundry completion,
  clean clothing and prepared meals;
- activity catalog `1.1.0` separates generic travel from crossing the home boundary;
- action catalog `1.1.0` gives `prepare_food`, `shop` and `dress` their missing typed
  state effects;
- personal process package `1.1.0` removes redundant boundary actions, models domestic
  walks and recycling as complete round trips, declares item transformations and tracks
  medication inventory;
- the canonical plan and M4 bundle are regenerated from those new artifacts with new
  identifiers and digests;
- M5 evaluates every precondition strictly. Missing facts are false and mandatory
  failures terminate under the failure contract. There is no compatibility mode.

The structural JSON Schemas remain `1.0.0`: the correction uses fields already allowed by
the frozen contracts. Catalog and package content versions identify the new semantics.

## Consequences

- The original scenario, catalogs, process package and M4 bundle remain reproducible and
  continue to demonstrate their original milestone contracts.
- The old bundle is intentionally rejected by strict M5 execution, proving that the
  engine does not silently repair upstream semantics.
- M5 acceptance uses only the corrected runtime scenario and package.
- Future semantic corrections require another explicit content version and migration;
  runtime exception tables are prohibited.
