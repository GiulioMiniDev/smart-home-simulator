# ADR-007: Reference-compatible authoring prompt 1.2.0

- Status: accepted
- Date: 2026-07-20

## Context

The second real external-LLM trial used prompt `1.1.0`. It corrected every first-trial
problem: provenance was complete, the scenario had no validation warning, compilation
succeeded, and movement coverage was complete. Behavior validation nevertheless rejected
76 action arguments across 23 models with `ACTION_ARGUMENT_TYPE_MISMATCH`.

All failures shared one cause: the LLM used `activity_resource`, which resolves a concrete
scenario resource, for action parameters whose catalog `referenceKind` was `capability` or
`environment_entity`. The catalog contained both pieces of information but the prompt did
not explicitly state their compatibility rule.

An in-memory diagnostic replaced only those 76 expressions with symbolic literal roles.
The unchanged scenario then passed validation and compilation, and the process package
passed with zero errors and warnings. This proved that the compatibility rule was the sole
remaining contract failure in the second trial.

## Decision

Preserve prompts `1.0.0` and `1.1.0` and introduce `1.2.0` as the preferred prompt. Embed
an explicit matrix between `ValueExpression.source` and action-parameter `referenceKind`,
including:

- `activity_location` for `location` or `none`;
- `activity_resource` for `resource` or `none`;
- `actor` for `resident` or `none`;
- meaningful symbolic literals for `capability` and `environment_entity`;
- declared scenario identifiers for literal location, resource, resident and external
  person references.

Include positive examples for movement, capability roles and environment-entity roles, a
negative example reproducing the trial failure, and an explicit final mismatch check.

## Consequences

- No JSON Schema, catalog, validator, compiler or runtime contract changes.
- The prompt explains a semantic relation already enforced by the behavior validator.
- Symbolic roles remain available for concrete binding in Milestone 4.
- The second trial remains an experimental artifact, not an automatically repaired input.
