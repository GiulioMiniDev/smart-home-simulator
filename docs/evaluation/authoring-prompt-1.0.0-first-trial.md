# First external-LLM authoring trial — prompt 1.0.0

- Date: 2026-07-20
- Model identification reported by output: `GPT-5 Codex`
- Case: Mario Rossi, three complete days in Rome
- Original raw-response path: `tests/mario-rossi-simulation-authoring-bundle.json`;
  subsequently replaced in place by the prompt `1.1.0` trial, so it is not a stable fixture
- Response size: 323,184 bytes

## Generated scope

- 3 day plans;
- 60 scenario activities;
- 41 personal process models;
- 41 process bindings.

## Unmodified first-pass result

Scenario validation completed with no errors and 15 resource-location warnings. Behavior
structure failed because `generatorVersion` was null. Compiler preflight independently
reported 10 `CROSS_BRANCH_DEPENDENCY` errors. No canonical authoring artifacts were
published.

An in-memory diagnostic that supplied only a temporary non-null generator version exposed
two additional `PROCESS_MOVEMENT_MISSING` errors in `wake_up` and
`wake_up_without_alarm`; the remaining 39 process models passed behavior validation.

## Interpretation

The LLM generated substantial, internally referenced content and complete activity
coverage, but prompt `1.0.0` did not reliably communicate provenance, universal movement
and compiler contingency constraints. This is a prompt/interface failure discovered by
the intended deterministic gates, not evidence that the invalid response is executable.

ADR-006 records the resulting prompt `1.1.0` and compilation-gated ingestion changes. The
compiler failure pattern remains covered by a minimal deterministic regression fixture;
researcher-supplied trial files are deliberately not test dependencies because later
trials may replace them in place.
