# ADR-019: Canonicalisation cost and the compilation budget

- Status: accepted and implemented
- Date: 2026-08-03
- Supersedes nothing; amends the compiler frozen by
  [ADR-003](ADR-003-freeze-plan-compiler-1.0.0.md)
- Supporting analysis: [`docs/plans/2026-08-03-compilazione-orizzonti-lunghi-diagnosi-e-partizione-design.md`](../plans/2026-08-03-compilazione-orizzonti-lunghi-diagnosi-e-partizione-design.md)

## Context

ADR-003 froze `priority-preference-1.0.0`: after the lexicographic stages, the compiler fixes each
preferred value in a deterministic order, asking CP-SAT once per (activity, field) whether that
value is still feasible. The policy is correct and the determinism is the point of it. Its cost,
however, is quadratic — one full solve per preference, on a model whose size is itself linear in
the number of activities — and no scenario before 2026-08-03 was large enough to show it.

An eight-month horizon was. With 3 870 activities the canonicalisation needed **7 740 solves of a
34 835-variable model at ~6.2 s each: roughly thirteen hours**. Three separate facts made this
worse than slow:

- **it was invisible.** `MAX_DETERMINISTIC_TIME = 2.0` bounds a single solve. The measured
  deterministic time per probe was 0.89, so the cap never fired; there is no budget on their
  number, no progress reporting, and the ingestion endpoint is a synchronous `def`, so the HTTP
  request simply never returned. No error, no partial result, nothing to read.
- **the work was not search.** A solver log on one probe reports `conflicts: 0` with
  `walltime: 6.19` — the time goes to re-presolving and re-linearising a 10 532 × 19 278 LP that
  the answer never needed. The API has no incremental solve, so every probe pays it again.
- **it could fail after all that.** On a contended horizon some probes exhaust the frozen
  deterministic budget and return `UNKNOWN`, which `solve()` turns into `not_optimal` and aborts
  the whole compilation. Thirteen hours could end in no plan.

## Decision

Three changes to `ScheduleSolver`, plus one new failure the compiler can report.

**1. Feasibility probes get their own solver parameters.** Only `status` is read from the 7 740
probes — their assignments are discarded and the plan comes from the final solve — so these
parameters cannot reach the canonical plan. Probes run with `linearization_level = 0`,
`cp_model_probing_level = 0` and `FEASIBILITY_DETERMINISTIC_TIME = 30.0`. The first two remove
work the answer does not use (17.8 s → 2.2 s per probe); the third stops a contended horizon from
answering `UNKNOWN` and losing an otherwise sound compilation. The lexicographic stages and the
final solve keep the frozen parameters, because those do determine the plan.

**2. Preferences are decided in batches against conflict cores.** All remaining targets are
asserted at once. A satisfiable batch settles every one of them, and the sequential policy
provably agrees: if the conjunction is feasible then each step of the loop, facing strictly fewer
active constraints, would have accepted its own target. An unsatisfiable batch yields a conflict
core; a **singleton** core proves that target infeasible on its own, so the loop rejects it too
whatever it had already fixed, and it is dropped. A larger core leaves the order undecided and
falls to a bisection for the end of the feasible prefix, bounded by the core itself.

**3. A budget on the whole canonicalisation.** `MAX_FEASIBILITY_PROBES = 20 000` counts probes
across the solve and raises `CompilationBudgetError`, reported as the new compilation issue
`COMPILATION_BUDGET_EXCEEDED` with the probe count, the budget, and the scenario's day and
activity counts. This is the part that addresses the defect as experienced: not a wrong plan but
an absent answer.

## Consequences

- **`compilerVersion` stays `1.0.0`.** ADR-003 requires an explicit version decision; this is it,
  and the decision is not to bump. The reason is evidence rather than convenience: recompiling the
  golden week under the new implementation leaves **169 of 169 activities with identical scheduled
  starts and ends**, and the only field of the plan that differs is the `compiler` metadata block
  itself. The tie-break policy is untouched and every plan it has ever produced is reproduced.

  A bump was implemented and then reverted, which is worth recording because the reason is
  structural. `compilerVersion` is carried inside the canonical plan, so changing it changes the
  plan digest, which changes the simulation bundle digest, which invalidates the
  `sourceBundleSha256` pinned in the hand-authored reference sensor model — 26 tests failed on
  that chain alone. The digest linkage did exactly what it exists to do; satisfying it would have
  meant hand-editing a frozen reference artifact to record a change that alters no schedule. If a
  future change does alter an outcome, the bump becomes mandatory and that regeneration is the
  price; this one does not.
- **Equivalence is argued, not sampled.** The SAT branch follows by induction; the singleton-core
  branch by the target being individually infeasible, which no ordering can change. Two
  independent measurements agree: on 14 days of the eight-month case the new path reproduces the
  old plan on **222 of 222 activities**, start and end identical, with the same four rejections;
  and the golden week recompiles to **169 of 169 identical activities**.
- Measured on the eight-month case: **~13 h → 274 s** end to end for a pinned horizon, and
  **34 min** for a horizon with real windows to place — where the previous implementation failed
  outright with `SOLVER_NOT_OPTIMAL`. On 14 days, 36.10 s → 0.99 s.
- `COMPILATION_ISSUE_CODES` gains one member, which propagates into the published enums of
  `compilation-report 1.0.0`, `authoring-ingestion-report 1.1.0` and
  `authoring-repair-request 1.0.0`. Those schemas are regenerated with new checksums. The addition
  is backward compatible for readers that treat the enum as open, and it is the reason a reader
  that treats it as closed must be rebuilt.
- No scenario, plan, behaviour, environment or runtime contract changes.
- The bisection branch is covered directly. `test_a_non_singleton_conflict_core_falls_to_bisection_and_keeps_the_policy`
  builds two mandatory activities of the same resident wanting the same hour with room to move:
  each fits its preferred moment alone, the pair never does, so the core names both and the batch
  path cannot decide between them. The test asserts the branch is entered and that the *earlier*
  activity keeps its preferred moment while the later yields — which is what the frozen order
  means, and the one thing a conflict core cannot tell you. The same branch is also exercised in
  the large by the outline-first horizons of
  [ADR-018](ADR-018-outline-first-external-authoring.md), whose wide windows produce real
  contention across 243 days.
