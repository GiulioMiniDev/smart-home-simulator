# Validation engine

## Responsibility

The validator decides whether a scenario is admissible according to a versioned contract. It is deterministic, read-only and independent from simulation.

## Levels

| Level | Examples |
|---|---|
| Structure | missing field, wrong type, invalid duration range |
| Referential | unknown actor, location, resource or dependency |
| Temporal | date outside range, dependency cycle, impossible precedence, fixed overlap |
| Semantic | participant duplicates actor, resource located elsewhere |

## Issue contract

Every issue contains:

```json
{
  "code": "UNKNOWN_ACTOR",
  "severity": "error",
  "level": "referential",
  "path": "$.days[0].activities[2].actorId",
  "message": "Activity 'a03' references unknown resident 'r9'."
}
```

Errors make the report invalid. Warnings do not, unless the CLI is invoked with `--warnings-as-errors`.

## Initial stable codes

```text
JSON_SYNTAX
STRUCTURE_INVALID
DUPLICATE_RESIDENT_ID
DUPLICATE_LOCATION_ID
DUPLICATE_RESOURCE_ID
DUPLICATE_DAY
DUPLICATE_ACTIVITY_ID
UNKNOWN_INITIAL_LOCATION
UNKNOWN_RESOURCE_LOCATION
UNKNOWN_ACTOR
UNKNOWN_PARTICIPANT
UNKNOWN_DESTINATION
UNKNOWN_REQUIRED_RESOURCE
UNKNOWN_DEPENDENCY
SELF_DEPENDENCY
DEPENDENCY_CYCLE
DAY_OUTSIDE_SCENARIO
IMPOSSIBLE_PRECEDENCE
FIXED_ACTIVITY_OVERLAP
ACTOR_REPEATED_AS_PARTICIPANT
RESOURCE_LOCATION_MISMATCH
```

Adding a code is backward compatible. Renaming or changing the meaning of a code requires a documented compatibility decision.

