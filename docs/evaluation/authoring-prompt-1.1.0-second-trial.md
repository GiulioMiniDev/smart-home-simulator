# Second external-LLM authoring trial — prompt 1.1.0

- Date: 2026-07-20
- Case: Mario Rossi, three complete days in Rome
- Response path at evaluation time: `tests/mario-rossi-simulation-authoring-bundle.json`

## Generated scope

- 3 day plans;
- 60 scenario activities;
- 41 personal process models;
- 41 process bindings.

## Unmodified first-pass result

- scenario errors: 0;
- scenario warnings: 0;
- compilation errors: 0;
- canonical plan digest:
  `77de0927f159b0fc461ad796a1fd378796d2b31815d72d55eb488d681e3621e1`;
- behavior errors: 76, all `ACTION_ARGUMENT_TYPE_MISMATCH`;
- published artifacts: 0.

The 76 failures affected 23 models and all used `activity_resource` for a parameter with
`referenceKind = capability` or `environment_entity`.

## Diagnostic isolation

Replacing only the incompatible expressions in memory with symbolic literal roles made
the entire bundle pass scenario validation, compilation and behavior validation with zero
errors and warnings. The original response was not modified or published.

ADR-007 records the resulting prompt `1.2.0`. Researcher-supplied trial paths remain
mutable and are not dependencies of the automated test suite.

## Repair-loop artifact

After ADR-008, the unchanged rejected response was processed by the public repair flow.
It deterministically produced:

- `tests/mario-rossi-simulation-authoring-ingestion-report.json`, containing the same 76
  errors;
- `tests/mario-rossi-simulation-authoring-repair-request.json`, attempt 1, request ID
  `repair_9b1b8011d09da276_attempt_1`;
- no canonical authoring output.

The request satisfies `AuthoringRepairRequest 1.0.0` and is ready to be supplied to an
external LLM. Like the response, these real-trial files remain evaluation artifacts and
are not test-suite dependencies.
