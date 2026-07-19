# ADR-002: Freeze scenario and validation contracts 1.0.0

- **Status:** accepted
- **Date:** 2026-07-19

## Context

The validation milestone must become a dependable upstream boundary. Later work will certainly discover new compiler, environment and sensor needs, but retroactively changing the accepted input or report would make experiments irreproducible and force repeated work on Milestone 1.

## Decision

Freeze these public artifacts together:

- scenario semantics and `schemaVersion` `1.0.0`;
- `scenario-1.0.0.schema.json`;
- validation report semantics and `validatorVersion` `1.0.0`;
- `validation-report-1.0.0.schema.json`;
- registered issue codes and their severities;
- CLI exit-code behavior and deterministic report ordering.

A later milestone may consume these artifacts but may not alter them in place. New input capabilities require a new schema version, a separate model and an explicit migration. Existing `1.0.0` inputs must remain dispatchable under their original contract.

Implementation fixes are allowed only when they restore documented `1.0.0` behavior. A fix that changes externally observable admissibility or report meaning requires a validator version decision and regression fixture.

## Consequences

- Milestone 2 can depend on a stable accepted scenario.
- Old thesis experiments remain reproducible.
- New downstream needs cannot be smuggled into extensions as unofficial mandatory fields.
- Supporting multiple scenario versions later is explicit work rather than mutation of this milestone.
