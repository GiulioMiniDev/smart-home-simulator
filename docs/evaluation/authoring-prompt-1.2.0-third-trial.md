# Third external-LLM authoring trial — prompt 1.2.0

- Date: 2026-07-27
- Case: Filiberto Marcantoni, 25, studio apartment in Milan, seven complete days
  (2026-07-27 to 2026-08-02)
- Generating model: GPT-5.6 Thinking, one pass plus one researcher-driven correction pass
- Response path at evaluation time:
  `filiberto_simulation_authoring_bundle_corrected.json`

## Generated scope

- 7 day plans;
- 72 scenario activities;
- 15 personal process models;
- 15 process bindings.

## Result of the submitted bundle

- scenario errors: 0;
- scenario warnings: 0;
- compilation errors: 0;
- behavior errors: 0;
- authoring preflight errors: 4, all `DETERMINISTIC_PRECONDITION_FAILED`;
- published artifacts: 0.

Every rule prompt `1.2.0` teaches was satisfied. The rejection came from the gate that runs
only after behavior validation passes: `validate_deterministic_preconditions` replays all
seven days through one persistent per-resident state.

| Model | Node | Failing precondition | Activities |
|---|---|---|---|
| `pm_commute_home` | `leave_home` | `resident.at_home eq true` | `20260727`, `20260729`, `20260731` |
| `pm_weekly_meal_preparation` | `put_item("prepared_food_container")` | `resident.carrying.prepared_food_container eq true` | `20260802` |

## Diagnostic isolation

Three in-memory variants were validated, none published:

- **A** — delete the `leave_home` node from `pm_commute_home`. The four preflight errors are
  replaced by one `PROCESS_COMPONENT_MISMATCH`: the frozen `travel` component requires
  `leave_home -> travel_to`. Deleting the node is not a repair.
- **B** — insert `enter_home` before the required `leave_home`. The three `commute_home`
  failures disappear and only the `put_item` failure remains.
- **C** — B plus a `take_item("prepared_food_container")` before the `store_food` sequence.
  Result: `VALID`, `0 error(s), 0 warning(s)`, canonical scenario digest
  `20de532aea9f3357bdb4deadbf72b5c8dfffab1753c0bc8b31a03c91a3a88b17`, canonical package digest
  `9de96b79fc1e24679994dbe119e9cc83a30d17ec6d29d41211a4b4f207bc9a4e`.

A fourth variant confirmed the same replay leaks across days in the other direction: an
unbalanced extra `open("food_storage")` in the breakfast model made the lunch model's `open`
deterministically false on all seven days, seven errors from one unclosed container.

## Conclusion

The two failure classes were the sole remaining contract failures in the third trial, and
neither was mentioned by prompt `1.2.0`. ADR-017 records the resulting prompt `1.3.0`, which
adds the replayed precondition and effect table, the chronological state ledger and the
mandatory `travel` bridge. Researcher-supplied trial paths remain mutable and are not
dependencies of the automated test suite.
