# ADR-017: State-continuous authoring prompt 1.3.0

- Status: accepted
- Date: 2026-07-27

## Context

A third real external-LLM trial used prompt `1.2.0` on a new case (`Filiberto Marcantoni`,
Milan, seven days). The bundle was correct on every axis the prompt teaches: provenance was
complete, the scenario validated, the plan compiled, every activity resolved to exactly one
binding, every component sequence was present and no argument mismatched its
`referenceKind`. Ingestion still rejected it with four
`DETERMINISTIC_PRECONDITION_FAILED` errors.

Behavior validation is not the last gate. When it passes,
`validate_deterministic_preconditions` replays every activity of every day, ordered by
scheduled start, through one persistent per-resident state, asserting each action's catalog
preconditions and applying its catalog effects. The state survives activity and day
boundaries. Two failure classes appeared:

1. `pm_commute_home` contained the `leave_home` that the frozen `travel` component requires,
   but the resident was already outside, so `resident.at_home eq true` was provably false on
   every working day. Deleting the node is not a repair: an in-memory variant that removed it
   produced `PROCESS_COMPONENT_MISMATCH` instead. Only the bridge
   `move_to_capability(home_entrance) -> enter_home -> leave_home -> travel_to -> enter_home`
   satisfies the component contract and the state contract at once.
2. `pm_weekly_meal_preparation` ended with `put_item("prepared_food_container")` for a role no
   `take_item` had ever granted, so `resident.carrying.prepared_food_container eq true` was
   provably false.

Applying exactly those two repairs to the trial bundle produced `0 error(s), 0 warning(s)`.
Prompt `1.2.0` never mentions preconditions, effects, persistent state or the bridge. The
simplified prompt `1.2.3-simplified` already teaches all of it in its chronological-ledger
section; the advanced prompt, which the application recommends, did not.

## Decision

Preserve prompts `1.0.0`, `1.1.0` and `1.2.0` and introduce `1.3.0` as the preferred advanced
prompt. `1.3.0` is `1.2.0` plus one generated section, `Mandatory action state continuity`,
covering:

- the replay itself, its ordering, and that state is not reset between activities or days;
- the full precondition and effect table, rendered from `action-catalog-1.0.0.json` by
  `tools/build_authoring_artifacts.py` rather than retyped;
- which facts start unknown (`entity.*`, `capability.*`) and which start from
  `scenario.initialState` (`resident.*`);
- the chronological ledger the model must build privately before answering;
- alternation of `leave_home`/`enter_home`, `take_item` before every `put_item` on the same
  role, and balanced `open`/`close` and `activate`/`deactivate` pairs on the same target;
- the mandatory bridge for a `travel` component performed away from home, with the explicit
  statement that removing `leave_home` trades one rejection for another.

Two matching bullets join the final consistency checklist. The application serves `1.3.0` as
its complete prompt.

## Consequences

- No JSON Schema, catalog, validator, compiler or runtime contract changes.
- The prompt explains a semantic relation already enforced by the authoring preflight.
- `1.2.0` stays frozen and buildable, so the trials recorded against it stay reproducible.
- The precondition table is generated, so a catalog that gains a precondition cannot ship with
  the prompt silently omitting it; `tests/test_authoring_ingestion.py` asserts the table
  against the catalog.
- The third trial remains an experimental artifact, not an automatically repaired input.
