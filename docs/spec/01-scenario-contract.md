# Scenario contract 0.1.0

## Purpose

The scenario describes intended activities and the logical entities they reference. It does not contain executed timestamps, trajectories or sensor activations.

## Top-level sections

```text
schemaVersion
scenarioId
timeZone
startDate / endDate
seed
provenance
residents
locations
resources
days
```

## Entity policy

- `residentId`, `locationId`, `resourceId` and `activityId` are stable identifiers.
- Activity identifiers are unique across the entire scenario.
- Activity dependencies are currently restricted to the same day.
- Locations are logical: `room`, `external` or `transit`.
- Geometry and connectivity are deliberately absent from version `0.1.0`.

## Timing

Every activity provides:

- an earliest, preferred and latest start;
- a minimum, preferred and maximum duration.

The validator checks ordering and feasibility but does not choose an exact start. That operation belongs to the future plan compiler.

## Versioning

Breaking changes require a new schema version. Producers must include the exact `schemaVersion`; accepting unspecified or unknown versions is forbidden.

The generated schema is stored in `schemas/scenario-0.1.0.schema.json`.

