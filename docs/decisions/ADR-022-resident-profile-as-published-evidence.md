# ADR-022: The resident's profile is published evidence, derived from the realized trace

- Status: accepted and implemented
- Date: 2026-08-14
- Complements [ADR-018](ADR-018-outline-first-external-authoring.md), which published what the
  outline *declared* about the day; this publishes what the simulation actually produced.

## Context

The application has always been able to answer questions about events. The diary lists activities
one by one, the observable view lists readings one by one, the timeline plays them back. Every one
of these is per-event, and none of them answers the question a researcher asks first of a synthetic
resident: *what is this person like?*

That question has no per-event answer. It lives in the aggregate — at what hour she reliably
sleeps, how wide the spread on her wake-up is, which rooms hold her day, where the routine is rigid
and where it dissolves — and until now the only way to get at it was to export the activity log and
write a notebook. Every reader of a generated dataset wrote that notebook again, slightly
differently, and the resulting figures were not comparable between two runs of the same project.

`HabitGroundTruth` 1.1.0 is not this. It states the bands the outline declared and the mix the
*plan* produced in each, it exists only for outline-first horizons, and it is the answer sheet a
segmentation algorithm is scored against. It says what should have happened.

## Decision

Publish `resident_profile` 1.0.0: an aggregate of the **execution trace and nothing else**.

1. **Realized, not planned.** The profile reads `activityExecutions` and `movements`. It therefore
   describes the resident deviations and failures included, matching the sensor log exported beside
   it. A `dropped` activity occupies no part of the clock — it never ran — but is counted
   separately, because a plan that keeps missing is itself a fact about the person.

2. **It does not consult the declared bands.** Comparing the profile to `HabitGroundTruth` is an
   evaluation someone performs, with their own tolerance and their own scoring. Folding that
   comparison into the document would publish a verdict where the evidence belongs, and would make
   the profile unavailable for the many runs that have no outline behind them.

3. **The slot is the unit.** The day is cut into equal slots — fifteen minutes by default, the
   discretisation the habit-segmentation reference uses on CASAS Aruba — and every measurement is
   stated per slot, so the document renders as a heatmap without further arithmetic.

4. **Shares divide by observed time, not by the calendar.** Occupancy and the observed window are
   both measured by the same projection of real intervals onto the local wall clock. A horizon that
   opens at noon reports no morning rather than an empty one, and a share can never exceed one.

5. **Three shapes, one derivation.** The same document is served as JSON to the application, drawn
   as a standalone page with inline SVG, and flattened into a wide CSV matrix. The page carries no
   script and no external reference so it survives being committed beside a thesis chapter; the
   matrix exists so the figures can be redrawn elsewhere without a pivot.

6. **Computed at export time, not at run time.** The profile is not a projection of a stored
   artifact, so it takes its own path through the export and applies retroactively to every run
   already in a workspace. Nothing about the run pipeline or its digests changes.

## Consequences

`ExportFormat` gains `json` and `html`, and the export manifest becomes 1.1.0. The two new formats
cannot be *requested*: they are the shapes the profile has, and a request naming them is rejected.
Manifests written as 1.0.0 are still read, because they describe exports that are still on disk and
a workspace that could no longer list its older datasets would have lost them.

The profile is a second readable view of the same trace, so it can disagree with the diary only by
being wrong. It is derived on demand and cached against the trace digest; it is never persisted as
a run artifact, which is what keeps replay verification untouched.

Nothing here calibrates or scores. Whether a synthetic resident's rhythm resembles a real one
remains the empirical question assigned to M9; this document only makes the synthetic rhythm
visible enough to ask it.
