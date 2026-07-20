# ADR-006: Compilation-gated external-LLM authoring 1.1.0

- Status: accepted
- Date: 2026-07-20

## Context

The first real external-LLM trial used the self-contained prompt `1.0.0` to generate a
three-day Mario Rossi bundle. The response was valid under the scenario validator, but
failed later compiler preflight with ten `CROSS_BRANCH_DEPENDENCY` errors. It also omitted
a required provenance string and explicit movement in two wake-up models.

The trial showed that structural scenario validity and behavior compatibility are not
sufficient admission criteria for generated simulator inputs. It also showed that the
prompt did not communicate the frozen compiler's contingency-branch restrictions with
enough precision.

## Decision

1. Keep the transport bundle at `1.0.0`; its shape and nested frozen contracts do not
   change.
2. Preserve prompt `1.0.0` and introduce prompt `1.1.0` as the preferred version.
3. Fix authoring-workflow provenance values in prompt `1.1.0`, while retaining the actual
   external model name as separate provenance.
4. State the compiler rules for fallback targets and cross-branch dependencies explicitly.
5. Require one explicit movement action in every process model, calling out wake-up and
   other stationary-looking intents.
6. Run the complete deterministic compiler during authoring ingestion whenever the nested
   scenario is valid.
7. Introduce ingestion report `1.1.0`, adding a compilation stage, compilation error count
   and canonical-plan digest. Preserve the frozen `1.0.0` report schema unchanged.
8. Continue publishing only the two LLM-authored canonical documents. The plan is a
   deterministic derived artifact and can be reproduced with the existing `compile`
   command; ingestion uses it as an admission proof rather than a third authored output.

## Consequences

- A structurally valid but non-compilable LLM scenario can no longer be published by the
  authoring ingestor.
- Scenario, compiler and behavior issues are reported in one pass when the scenario is
  structurally valid.
- Prompt regressions are tested against the first real LLM response.
- The simulator's existing scenario, plan and personal-process contracts remain frozen and
  unchanged.
- A successful report includes the digest of the deterministic plan proven during
  ingestion, even though the plan file is not emitted by this command.
