# Validation engine 1.0.0

## Responsibility

The validator deterministically decides whether a scenario is admissible under contract `1.0.0`. It is read-only, has no random behavior and imports no compiler, simulator, geometry or sensor implementation.

It does not repair, schedule or execute a scenario. A valid report means “internally admissible”, not “behaviorally realistic”.

## Input pipeline

Validation is deliberately staged:

1. bounded file read, with a 50 MiB limit;
2. strict UTF-8 decoding;
3. JSON nesting bounded to 256 levels;
4. strict JSON parsing, rejecting duplicate keys and non-finite numbers;
5. exact schema-version dispatch;
6. strict Pydantic structural validation with unknown fields forbidden;
7. deterministic referential, temporal and semantic rules;
8. stable sorting and report serialization.

Failures are returned as reports rather than uncaught exceptions for missing files, unreadable inputs, encoding errors, JSON syntax and invalid scenarios.

## Validation levels

| Level | Responsibility |
|---|---|
| `structure` | JSON, types, required/unknown fields and local object invariants |
| `referential` | identifiers and cross-object references |
| `temporal` | simulation bounds, timezone offsets, precedence and definite conflicts |
| `semantic` | policies, fallback meaning, participant and resource compatibility |

The engine flags contradictions it can prove from fixed information. It does not reject merely possible overlaps between flexible activities; resolving those belongs to the plan compiler.

## Report contract

Every issue contains `code`, frozen `severity`, `level`, JSON-style `path`, human-readable `message` and machine-readable `details`.

```json
{
  "validatorVersion": "1.0.0",
  "valid": false,
  "schemaVersion": "1.0.0",
  "scenarioId": "example",
  "issues": [
    {
      "code": "UNKNOWN_ACTOR",
      "severity": "error",
      "level": "referential",
      "path": "$.days[0].activities[2].actorId",
      "message": "Activity 'a03' references unknown resident 'r9'.",
      "details": {}
    }
  ],
  "summary": {"errorCount": 1, "warningCount": 0}
}
```

Errors make the report invalid. Warnings remain valid unless the CLI uses `--warnings-as-errors`. The distributed output contract is `schemas/validation-report-1.0.0.schema.json`; the golden report in `tests/golden` protects ordering, aliases and serialization.

## Stable issue vocabulary

The authoritative registry is `src/smart_home_sim/domain/codes.py`. It contains 83 codes and is emitted as the `code` enumeration in the validation-report JSON Schema. Three have warning severity: `DUPLICATE_DECLARED_CONSTRAINT`, `RESOURCE_LOCATION_MISMATCH` and `UNUSED_COMMITMENT`; every other code is an error.

The test matrix executes every registered rule code and asserts that no emitted code or severity can exist outside the registry. Renaming a code, changing its severity or changing its established meaning is a breaking report-contract change.

## Quality gates

- every valid example exits `0` and every invalid example exits `1`;
- the representative week contains seven days and 173 activities and validates cleanly;
- both public JSON Schemas pass the Draft 2020-12 metaschema validator and exactly match the models;
- parser, model invariants, all issue codes, CLI modes and golden output are tested;
- line coverage must remain at least 95%;
- Ruff lint and formatting checks pass;
- the dependency graph contains no simulation, geometry or sensor runtime.
