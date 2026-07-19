# Plan compiler 1.0.0

## Responsibility

The compiler turns one scenario accepted by validator `1.0.0` into a deterministic canonical plan. It materializes timing and selection decisions; it does not execute activities, evaluate live facts, sample runtime events, move residents through geometry or emit sensor observations.

The public outputs are:

- `canonical-plan-1.0.0.schema.json`, produced only on success;
- `compilation-report-1.0.0.schema.json`, produced for every attempt.

Both preserve the source scenario identifier and use a SHA-256 digest of its normalized semantic representation. Whitespace and JSON object ordering therefore do not affect provenance.

## Time and constraint model

All instants are converted to signed integer microseconds from the scenario start. A decimal minute value must be exactly representable at that resolution. Local timestamps are converted through UTC and rendered again in the declared IANA time zone, so offset and daylight-saving transitions remain explicit.

The OR-Tools CP-SAT model enforces:

- start and end windows, duration ranges and boundary truncation;
- `all` and `any` dependencies with minimum and maximum lag;
- exact linked commitments and non-overlap with other commitments;
- non-overlap for actors and resident participants, respecting `canOverlapForActor`;
- cumulative resource capacity;
- mandatory presence and optional selection.

External people are not scheduled residents. Preconditions and effects are preserved for the simulator; they are not evaluated against future state by the compiler.

## Deterministic materialization policy

The frozen policy `priority-preference-1.0.0` applies these decisions in order:

1. prove the maximum total priority of feasible optional activities;
2. while preserving that score, prove the maximum optional activity count;
3. remove equal-score ambiguity by attempting optional activities in ascending stable identifier order;
4. in source order, retain each preferred duration, start and end that remains globally feasible;
5. solve the remaining degrees of freedom with stable earliest/minimum decision strategies.

Every accepted CP-SAT call must return `OPTIMAL`. Selection objectives are global optima; preference retention is deliberately a deterministic feasible policy, not a claim that the sum of all deviations is globally minimal. Reported deviation totals describe the resulting plan and support later evaluation.

Reproducibility additionally fixes OR-Tools to `9.15.6755`, one search worker, seed zero, integer time and a deterministic-time bound. A solver that cannot prove the required result causes compilation failure rather than a best-effort artifact.

## Contingencies

`always` activities form the main plan. Conditional and fallback activities are compiled as named daily contingency patches.

For a fallback, the target is removed and the selected main activities of that date are re-solved together with the branch. The patch contains:

- `activities`: selected branch activities;
- `rescheduledActivities`: main activities whose timing or selected dependency changes;
- `omittedActivities`: optional branch or main activities unavailable in that alternate day.

This is necessary when a replacement changes downstream timing. Unchanged activities are inherited from the main day. Each contingency is proven feasible independently. Simultaneous contingencies are not pre-composed; Milestone 3 must revalidate the active day before execution and either apply a compatible patch or invoke the declared local-repair policy.

An optional fallback target omitted from the main plan yields an inactive empty patch and warning `CONTINGENCY_TARGET_NOT_SCHEDULED`. Unsupported dependencies between unrelated branches are rejected during preflight.

## Failure contract

The compiler never emits a partial canonical plan. Its report distinguishes invalid input, preflight errors, main-plan infeasibility, contingency infeasibility, solver/model failure, numeric-range failure and invalid generated output. Issue codes and severities are frozen with compiler contract `1.0.0`.

## Acceptance case

`examples/valid/mario_week.json` contains seven days and 173 source activities. Its golden compilation has 169 main activities, three contingency patches, four branch activities and three explicit reschedulings. The five work commitments begin at 08:15: the earlier 08:00 fixture was admissible to the structural validator but physically infeasible after the minimum morning routine and commute were combined. This fixture correction changes no scenario-contract rule.
